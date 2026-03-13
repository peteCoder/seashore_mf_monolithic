"""
Loan Insurance Claim Views
==========================
Status flow: submitted → under_review → approved → paid (or rejected).

Journal on payout:
    Dr 1010 Cash In Hand             [payout_amount]
    Cr 1810 Loan Receivable          [min(payout_amount, outstanding_balance)]
    Cr 1820 Interest Receivable      [min(remainder, accrued_interest_balance)]  if > 0
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from core.models import LoanInsuranceClaim, Loan
from core.forms.insurance_forms import (
    InsuranceClaimFileForm, InsuranceClaimReviewForm, InsuranceClaimPayoutForm
)
from core.permissions import PermissionChecker
from core.utils.accounting_helpers import create_journal_entry
from core.services.notification_service import notify, notify_role


@login_required
def insurance_claim_list(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    qs = LoanInsuranceClaim.objects.select_related(
        'loan', 'loan__client', 'loan__branch', 'filed_by', 'reviewed_by',
    )
    if checker.is_manager():
        qs = qs.filter(loan__branch=request.user.branch)

    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(status=status_filter)

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 25)
    page_obj  = paginator.get_page(request.GET.get('page'))

    return render(request, 'insurance/list.html', {
        'page_title':    'Loan Insurance Claims',
        'claims':        page_obj,
        'status_filter': status_filter,
        'checker':       checker,
    })


@login_required
def loan_file_insurance_claim(request, loan_id):
    """File a new insurance claim against a specific loan."""
    loan = get_object_or_404(
        Loan.objects.select_related('client', 'branch', 'loan_product'),
        id=loan_id,
    )
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied
    if checker.is_manager() and loan.branch != request.user.branch:
        raise PermissionDenied

    # Validate insurance requirement
    if not loan.loan_product.requires_insurance:
        messages.error(
            request,
            'This loan product does not require insurance. No claim can be filed.'
        )
        return redirect('core:loan_detail', loan_id=loan.id)

    # Check for existing active claim
    active_claim = LoanInsuranceClaim.objects.filter(
        loan=loan, status__in=['submitted', 'under_review', 'approved']
    ).first()
    if active_claim:
        messages.warning(
            request,
            f'An active claim ({active_claim.claim_ref}) already exists for this loan.'
        )
        return redirect('core:insurance_claim_detail', claim_id=active_claim.id)

    if loan.status not in ('active', 'overdue', 'disbursed'):
        messages.error(request, 'Insurance claims can only be filed for active or overdue loans.')
        return redirect('core:loan_detail', loan_id=loan.id)

    if request.method == 'POST':
        form = InsuranceClaimFileForm(request.POST)
        if form.is_valid():
            claim = form.save(commit=False)
            claim.loan      = loan
            claim.filed_by  = request.user
            claim.status    = 'submitted'
            claim.save()
            messages.success(request, f'Insurance claim {claim.claim_ref} filed successfully.')
            notify_role(
                roles=['director', 'admin'],
                notification_type='insurance_claim_filed',
                title='Insurance Claim Filed',
                message=(
                    f'{request.user.get_full_name()} filed insurance claim {claim.claim_ref} '
                    f'for loan {loan.loan_number} ({loan.client.get_full_name()}). '
                    f'Claim amount: ₦{claim.claim_amount:,.2f}. Please review.'
                ),
                related_loan=loan,
                related_client=loan.client,
                is_urgent=True,
            )
            return redirect('core:insurance_claim_detail', claim_id=claim.id)
    else:
        form = InsuranceClaimFileForm(initial={'claim_amount': loan.outstanding_balance})

    return render(request, 'insurance/file_claim.html', {
        'page_title': f'File Insurance Claim — {loan.loan_number}',
        'loan':       loan,
        'form':       form,
        'checker':    checker,
    })


@login_required
def insurance_claim_detail(request, claim_id):
    claim = get_object_or_404(
        LoanInsuranceClaim.objects.select_related(
            'loan', 'loan__client', 'loan__branch',
            'filed_by', 'reviewed_by', 'paid_by', 'payout_journal',
        ),
        id=claim_id,
    )
    checker = PermissionChecker(request.user)
    if checker.is_manager() and claim.loan.branch != request.user.branch:
        raise PermissionDenied
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    return render(request, 'insurance/detail.html', {
        'page_title': f'Insurance Claim — {claim.claim_ref}',
        'claim':      claim,
        'loan':       claim.loan,
        'checker':    checker,
    })


@login_required
@transaction.atomic
def insurance_claim_review(request, claim_id):
    """Director/Admin: approve or reject a claim."""
    claim = get_object_or_404(
        LoanInsuranceClaim.objects.select_related('loan', 'loan__branch', 'loan__client'),
        id=claim_id,
    )
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can review insurance claims.')
    if checker.is_manager() and claim.loan.branch != request.user.branch:
        raise PermissionDenied('You can only review claims for loans in your branch.')

    if claim.status not in ('submitted', 'under_review'):
        messages.error(
            request,
            f'Claim is "{claim.get_status_display()}" and cannot be reviewed.'
        )
        return redirect('core:insurance_claim_detail', claim_id=claim.id)

    if request.method == 'POST':
        form = InsuranceClaimReviewForm(request.POST)
        if form.is_valid():
            decision     = form.cleaned_data['decision']
            review_notes = form.cleaned_data.get('review_notes', '')

            claim.reviewed_by  = request.user
            claim.reviewed_at  = timezone.now()
            claim.review_notes = review_notes

            if decision == 'approve':
                claim.status = 'approved'
                messages.success(request, f'Claim {claim.claim_ref} approved. Record payout when funds are received.')
                claim.save(update_fields=[
                    'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'
                ])
                notify(
                    user=claim.filed_by,
                    notification_type='insurance_claim_approved',
                    title='Insurance Claim Approved',
                    message=(
                        f'Insurance claim {claim.claim_ref} for loan {claim.loan.loan_number} '
                        f'has been approved. A payout will be processed soon.'
                    ),
                    related_loan=claim.loan,
                    related_client=claim.loan.client,
                )
            else:
                claim.status = 'rejected'
                messages.warning(request, f'Claim {claim.claim_ref} rejected.')
                claim.save(update_fields=[
                    'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'
                ])
                notify(
                    user=claim.filed_by,
                    notification_type='insurance_claim_rejected',
                    title='Insurance Claim Rejected',
                    message=(
                        f'Insurance claim {claim.claim_ref} for loan {claim.loan.loan_number} '
                        f'has been rejected. Notes: {review_notes or "No notes provided"}.'
                    ),
                    related_loan=claim.loan,
                    related_client=claim.loan.client,
                    is_urgent=True,
                )

            return redirect('core:insurance_claim_detail', claim_id=claim.id)
    else:
        # Auto-advance from submitted to under_review when opened for review
        if claim.status == 'submitted':
            claim.status = 'under_review'
            claim.save(update_fields=['status', 'updated_at'])
        form = InsuranceClaimReviewForm()

    return render(request, 'insurance/review.html', {
        'page_title': f'Review Claim — {claim.claim_ref}',
        'claim':      claim,
        'loan':       claim.loan,
        'form':       form,
        'checker':    checker,
    })


@login_required
@transaction.atomic
def insurance_claim_record_payout(request, claim_id):
    """
    Director/Admin: record the payout received from the insurer.

    Posts journal:
        Dr 1010 Cash In Hand             [payout_amount]
        Cr 1810 Loan Receivable          [min(payout, outstanding_balance)]
        Cr 1820 Interest Receivable      [remainder capped at accrued_interest, if > 0]

    Updates loan balances. Marks loan as 'completed' if outstanding_balance zeroed.
    """
    claim = get_object_or_404(
        LoanInsuranceClaim.objects.select_related('loan', 'loan__branch', 'loan__client'),
        id=claim_id,
    )
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can record insurance payouts.')
    if checker.is_manager() and claim.loan.branch != request.user.branch:
        raise PermissionDenied('You can only record payouts for loans in your branch.')

    if claim.status != 'approved':
        messages.error(request, 'Only approved claims can have a payout recorded.')
        return redirect('core:insurance_claim_detail', claim_id=claim.id)

    loan = claim.loan

    if request.method == 'POST':
        form = InsuranceClaimPayoutForm(request.POST)
        if form.is_valid():
            payout_amount = form.cleaned_data['payout_amount']
            payout_notes  = form.cleaned_data.get('payout_notes', '')

            outstanding = loan.outstanding_balance
            accrued     = loan.accrued_interest_balance

            principal_credit = min(payout_amount, outstanding)
            interest_credit  = Decimal('0.00')
            remainder = payout_amount - principal_credit
            if remainder > 0 and accrued > 0:
                interest_credit = min(remainder, accrued)

            lines = [
                {
                    'account_code': '1010',
                    'debit':   float(payout_amount),
                    'credit':  0,
                    'description': f'Insurance payout — {claim.claim_ref}',
                    'client': loan.client,
                },
            ]
            if principal_credit > 0:
                lines.append({
                    'account_code': '1810',
                    'debit':  0,
                    'credit': float(principal_credit),
                    'description': f'Insurance: clear loan receivable — {loan.loan_number}',
                    'client': loan.client,
                })
            if interest_credit > 0:
                lines.append({
                    'account_code': '1820',
                    'debit':  0,
                    'credit': float(interest_credit),
                    'description': f'Insurance: clear interest receivable — {loan.loan_number}',
                    'client': loan.client,
                })

            try:
                journal = create_journal_entry(
                    entry_type='insurance_payout',
                    transaction_date=timezone.now().date(),
                    branch=loan.branch,
                    description=f'Insurance Payout: {claim.claim_ref} — {loan.loan_number}',
                    created_by=request.user,
                    lines=lines,
                    loan=loan,
                    reference_number=claim.claim_ref,
                    auto_post=True,
                )
            except (ValidationError, Exception) as exc:
                messages.error(request, f'Journal entry failed: {exc}')
                return redirect('core:insurance_claim_detail', claim_id=claim.id)

            # Update claim
            claim.payout_amount  = payout_amount
            claim.payout_journal = journal
            claim.paid_by        = request.user
            claim.paid_at        = timezone.now()
            claim.status         = 'paid'
            if payout_notes:
                claim.review_notes = (
                    (claim.review_notes + '\n' + payout_notes).strip()
                    if claim.review_notes else payout_notes
                )
            claim.save(update_fields=[
                'payout_amount', 'payout_journal', 'paid_by', 'paid_at',
                'status', 'review_notes', 'updated_at',
            ])

            # Update loan balances
            new_outstanding = max(Decimal('0.00'), outstanding - principal_credit)
            new_accrued     = max(Decimal('0.00'), accrued - interest_credit)
            loan.outstanding_balance      = new_outstanding
            loan.accrued_interest_balance = new_accrued

            if new_outstanding == Decimal('0.00'):
                loan.status          = 'completed'
                loan.completion_date = timezone.now()
                loan.save(update_fields=[
                    'outstanding_balance', 'accrued_interest_balance',
                    'status', 'completion_date', 'updated_at',
                ])
            else:
                loan.save(update_fields=[
                    'outstanding_balance', 'accrued_interest_balance', 'updated_at',
                ])

            messages.success(
                request,
                f'Payout of ₦{payout_amount:,.2f} recorded. '
                f'Journal {journal.journal_number} posted.'
            )
            notify(
                user=claim.filed_by,
                notification_type='insurance_claim_paid',
                title='Insurance Claim Paid',
                message=(
                    f'Insurance payout of ₦{payout_amount:,.2f} has been recorded '
                    f'for claim {claim.claim_ref} on loan {loan.loan_number}.'
                    + (' Loan is now fully settled.' if new_outstanding == Decimal('0.00') else '')
                ),
                related_loan=loan,
                related_client=loan.client,
            )
            return redirect('core:insurance_claim_detail', claim_id=claim.id)
    else:
        form = InsuranceClaimPayoutForm(initial={'payout_amount': claim.claim_amount})

    return render(request, 'insurance/record_payout.html', {
        'page_title': f'Record Payout — {claim.claim_ref}',
        'claim':      claim,
        'loan':       loan,
        'form':       form,
        'checker':    checker,
    })
