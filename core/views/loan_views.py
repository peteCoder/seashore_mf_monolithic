"""
Loan Views
==========

Views for loan management including creation, approval, disbursement, and repayment posting
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum, F, Case, When, DecimalField
from django.utils import timezone
from decimal import Decimal

from core.models import Loan, LoanRepaymentPosting, Transaction, Client, Branch, LoanProduct, Guarantor, Collateral, FollowUpTask, PaymentPromise, LoanInsuranceClaim
from core.utils.accounting_helpers import create_journal_entry
from core.forms.loan_forms import (
    LoanApplicationForm, LoanFeePaymentForm, LoanApprovalForm,
    LoanDisbursementForm, LoanRepaymentPostingForm, BulkLoanRepaymentPostingForm,
    ApproveRepaymentPostingForm, LoanSearchForm, GuarantorForm
)
from core.permissions import PermissionChecker
from core.services.notification_service import notify, notify_role


# =============================================================================
# LOAN LIST
# =============================================================================

@login_required
def loan_list(request):
    """
    Display paginated list of loans with filters

    Permissions:
    - All authenticated users
    - Filtered by branch/client access
    """
    checker = PermissionChecker(request.user)

    # Base queryset with permissions
    loans = Loan.objects.select_related(
        'client', 'branch', 'loan_product', 'created_by'
    ).all()

    # Permission-based filtering
    if checker.is_staff():
        loans = loans.filter(client__assigned_staff=request.user)
    elif checker.is_manager():
        loans = loans.filter(branch=request.user.branch)
    # Admin/Director see all

    # Search form
    search_form = LoanSearchForm(request.GET or None)

    # Apply filters
    if search_form.is_valid():
        search = search_form.cleaned_data.get('search')
        if search:
            loans = loans.filter(
                Q(loan_number__icontains=search) |
                Q(client__first_name__icontains=search) |
                Q(client__last_name__icontains=search) |
                Q(client__client_id__icontains=search)
            )

        status = search_form.cleaned_data.get('status')
        if status:
            loans = loans.filter(status=status)

        branch = search_form.cleaned_data.get('branch')
        if branch:
            loans = loans.filter(branch=branch)

        loan_product = search_form.cleaned_data.get('loan_product')
        if loan_product:
            loans = loans.filter(loan_product=loan_product)

        date_from = search_form.cleaned_data.get('date_from')
        if date_from:
            loans = loans.filter(application_date__date__gte=date_from)

        date_to = search_form.cleaned_data.get('date_to')
        if date_to:
            loans = loans.filter(application_date__date__lte=date_to)

    # Annotate with payment progress
    loans = loans.annotate(
        payment_progress=Case(
            When(total_repayment=0, then=0),
            default=(F('amount_paid') / F('total_repayment')) * 100,
            output_field=DecimalField()
        )
    ).order_by('-application_date')

    # Pagination
    paginator = Paginator(loans, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Summary stats
    summary = {
        'total_count': loans.count(),
        'pending_approval': loans.filter(status='pending_approval').count(),
        'active_count': loans.filter(status='active').count(),
        'overdue': loans.filter(status='overdue').count(),
        'total_disbursed': loans.filter(
            status__in=['active', 'overdue', 'completed']
        ).aggregate(Sum('amount_disbursed'))['amount_disbursed__sum'] or Decimal('0.00'),
        'total_outstanding': loans.filter(
            status__in=['active', 'overdue']
        ).aggregate(Sum('outstanding_balance'))['outstanding_balance__sum'] or Decimal('0.00'),
    }

    context = {
        'page_title': 'Loans',
        'loans': page_obj,
        'search_form': search_form,
        'summary': summary,
        'checker': checker,
    }

    return render(request, 'loans/list.html', context)


# =============================================================================
# LOAN DETAIL
# =============================================================================

@login_required
def loan_detail(request, loan_id):
    """
    Display loan details with repayment schedule

    Permissions:
    - Must have permission to view this loan
    """
    loan = get_object_or_404(
        Loan.objects.select_related(
            'client', 'branch', 'loan_product', 'created_by',
            'approved_by', 'disbursed_by', 'linked_account'
        ),
        id=loan_id
    )

    checker = PermissionChecker(request.user)

    # Permission check
    if checker.is_staff():
        if loan.client.assigned_staff != request.user:
            raise PermissionDenied("You don't have permission to view this loan")
    elif checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You don't have permission to view this loan")
    # Admin/Director can view all

    # Generate repayment schedule
    from core.utils.helpers import generate_repayment_schedule
    repayment_schedule = generate_repayment_schedule(loan)

    # Get repayment postings
    repayment_postings = loan.repayment_postings.select_related(
        'submitted_by', 'reviewed_by', 'transaction'
    ).order_by('-submitted_at')[:10]

    # Get transactions
    transactions = loan.transactions.select_related(
        'processed_by'
    ).order_by('-created_at')[:10]

    # Calculate summary
    summary = {
        'days_since_disbursement': (
            (timezone.now().date() - loan.disbursement_date.date()).days
            if loan.disbursement_date else None
        ),
        'days_until_completion': (
            (loan.final_repayment_date - timezone.now().date()).days
            if loan.final_repayment_date and loan.final_repayment_date > timezone.now().date()
            else None
        ),
        'payment_progress_pct': loan.payment_progress_percentage,
        'pending_postings': loan.repayment_postings.filter(status='pending').count(),
    }

    # Get guarantor information
    guarantors = loan.guarantors.select_related('linked_client').all()
    required_guarantors = loan.loan_product.required_guarantors
    current_guarantor_count = guarantors.count()
    guarantors_complete = current_guarantor_count >= required_guarantors

    # Collections: follow-up tasks and payment promises for this loan
    followup_tasks = FollowUpTask.objects.filter(loan=loan).select_related(
        'assigned_to', 'created_by'
    ).order_by('due_date')

    payment_promises = PaymentPromise.objects.filter(loan=loan).select_related(
        'recorded_by'
    ).order_by('promise_date')

    # Insurance claims for this loan
    insurance_claims = LoanInsuranceClaim.objects.filter(loan=loan).select_related(
        'filed_by', 'reviewed_by', 'paid_by'
    ).order_by('-created_at')

    active_insurance_claim = insurance_claims.filter(
        status__in=['submitted', 'under_review', 'approved']
    ).first()

    context = {
        'page_title': f'Loan {loan.loan_number}',
        'loan': loan,
        'repayment_schedule': repayment_schedule,
        'repayment_postings': repayment_postings,
        'transactions': transactions,
        'summary': summary,
        'checker': checker,
        'guarantors': guarantors,
        'required_guarantors': required_guarantors,
        'current_guarantor_count': current_guarantor_count,
        'guarantors_complete': guarantors_complete,
        'followup_tasks': followup_tasks,
        'payment_promises': payment_promises,
        'insurance_claims': insurance_claims,
        'active_insurance_claim': active_insurance_claim,
        'today': timezone.now().date(),
    }

    return render(request, 'loans/detail.html', context)


# =============================================================================
# LOAN CREATE
# =============================================================================

@login_required
@transaction.atomic
def loan_create(request):
    """
    Create a new loan application

    Permissions:
    - All staff can create loans

    Flow:
    1. Create loan with status='pending_fees'
    2. Redirect to fee payment page
    """
    checker = PermissionChecker(request.user)

    if request.method == 'POST':
        form = LoanApplicationForm(request.POST, request.FILES, user=request.user)

        if form.is_valid():
            loan = form.save(commit=False)
            loan.created_by = request.user
            loan.status = 'pending_fees'

            # Set branch from user if not specified
            if not loan.branch_id:
                loan.branch = request.user.branch

            loan.save()

            # Notify branch manager of new loan application
            notify_role(
                roles='manager',
                branch=loan.branch,
                notification_type='loan_applied',
                title='New Loan Application',
                message=f'A new loan application {loan.loan_number} of ₦{loan.principal_amount:,.2f} has been submitted for client {loan.client.get_full_name()}.',
                related_loan=loan,
                related_client=loan.client,
                exclude_user=request.user,
            )

            # Check if guarantors are required
            required_guarantors = loan.loan_product.required_guarantors
            if required_guarantors > 0:
                messages.success(
                    request,
                    f'Loan application {loan.loan_number} created successfully. '
                    f'Please add {required_guarantors} guarantor(s) for this loan.'
                )
                return redirect('core:loan_guarantors', loan_id=loan.id)
            else:
                messages.success(
                    request,
                    f'Loan application {loan.loan_number} created successfully. '
                    f'Please proceed to pay upfront fees of ₦{loan.total_upfront_fees:,.2f}.'
                )
                return redirect('core:loan_pay_fees', loan_id=loan.id)
    else:
        initial = {}
        client_id = request.GET.get('client')
        if client_id:
            initial['client'] = client_id
        form = LoanApplicationForm(user=request.user, initial=initial)

    context = {
        'page_title': 'Create Loan Application',
        'form': form,
        'show_calculator': True,
        'checker': checker,
    }

    return render(request, 'loans/form.html', context)


# =============================================================================
# LOAN PAY FEES
# =============================================================================

@login_required
@transaction.atomic
def loan_pay_fees(request, loan_id):
    """
    Pay loan application fees

    Permissions:
    - Staff who created loan or has permission to view it

    Flow:
    1. Show fee breakdown
    2. Collect payment details
    3. Call loan.pay_fees() which creates transaction
    4. Status changes to 'pending_approval'
    """
    loan = get_object_or_404(Loan, id=loan_id)
    checker = PermissionChecker(request.user)

    # Permission check
    if checker.is_staff():
        if loan.client.assigned_staff != request.user:
            raise PermissionDenied("You don't have permission to access this loan")
    elif checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You don't have permission to access this loan")

    if loan.fees_paid:
        messages.warning(request, "Fees have already been paid for this loan.")
        return redirect('core:loan_detail', loan_id=loan.id)

    if loan.status != 'pending_fees':
        messages.error(request, "Cannot pay fees for this loan at this time.")
        return redirect('core:loan_detail', loan_id=loan.id)

    # Check if required guarantors are provided
    required_guarantors = loan.loan_product.required_guarantors
    current_guarantors = loan.guarantors.count()
    if required_guarantors > 0 and current_guarantors < required_guarantors:
        messages.warning(
            request,
            f"This loan requires {required_guarantors} guarantor(s). "
            f"Currently {current_guarantors} guarantor(s) added. "
            f"Please add the remaining guarantor(s) before paying fees."
        )
        return redirect('core:loan_guarantors', loan_id=loan.id)

    if request.method == 'POST':
        form = LoanFeePaymentForm(request.POST, loan=loan)

        if form.is_valid():
            payment_details = (
                f"Method: {form.cleaned_data['payment_method']}, "
                f"Ref: {form.cleaned_data.get('payment_reference', 'N/A')}, "
                f"{form.cleaned_data.get('payment_details', '')}"
            )

            success, message = loan.pay_fees(
                processed_by=request.user,
                payment_details=payment_details
            )

            if success:
                messages.success(request, f"Fees paid successfully. {message}")
                return redirect('core:loan_detail', loan_id=loan.id)
            else:
                messages.error(request, f"Failed to pay fees: {message}")
    else:
        form = LoanFeePaymentForm(loan=loan)

    # Calculate fee breakdown from loan product
    fee_breakdown = []
    if loan.loan_product:
        fees = loan.loan_product.calculate_fees(loan.principal_amount)

        if loan.loan_product.risk_premium_enabled:
            rate_display = f"{float(loan.loan_product.risk_premium_rate) * 100:.2f}%"
            if loan.loan_product.risk_premium_calculation != 'percentage':
                rate_display = "Flat"
            fee_breakdown.append({
                'name': 'Risk Premium',
                'rate': rate_display,
                'amount': fees.get('risk_premium_fee', Decimal('0.00'))
            })

        if loan.loan_product.rp_income_enabled:
            rate_display = f"{float(loan.loan_product.rp_income_rate) * 100:.2f}%"
            if loan.loan_product.rp_income_calculation != 'percentage':
                rate_display = "Flat"
            fee_breakdown.append({
                'name': 'RP Income',
                'rate': rate_display,
                'amount': fees.get('rp_income_fee', Decimal('0.00'))
            })

        if loan.loan_product.tech_fee_enabled:
            rate_display = f"{float(loan.loan_product.tech_fee_rate) * 100:.2f}%"
            if loan.loan_product.tech_fee_calculation != 'percentage':
                rate_display = "Flat"
            fee_breakdown.append({
                'name': 'Tech Fee',
                'rate': rate_display,
                'amount': fees.get('tech_fee', Decimal('0.00'))
            })

        if loan.loan_product.loan_form_fee_enabled:
            fee_breakdown.append({
                'name': 'Loan Form Fee',
                'rate': 'Fixed',
                'amount': fees.get('loan_form_fee', Decimal('0.00'))
            })

    context = {
        'page_title': f'Pay Fees - {loan.loan_number}',
        'loan': loan,
        'form': form,
        'checker': checker,
        'fee_breakdown': fee_breakdown,
    }

    return render(request, 'loans/pay_fees.html', context)


# =============================================================================
# LOAN APPROVE
# =============================================================================

@login_required
@transaction.atomic
def loan_approve(request, loan_id):
    """
    Approve or reject a loan application

    Permissions:
    - Only managers/directors/admins
    - Must have approval permission
    """
    loan = get_object_or_404(Loan, id=loan_id)
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied("You don't have permission to approve loans")

    # Permission check for branch
    if checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You can only approve loans for your branch")

    if loan.status != 'pending_approval':
        messages.error(request, f"Cannot approve loan with status: {loan.get_status_display()}")
        return redirect('core:loan_detail', loan_id=loan.id)

    # Check if required guarantors are provided
    required_guarantors = loan.loan_product.required_guarantors
    current_guarantors = loan.guarantors.count()
    guarantors_complete = current_guarantors >= required_guarantors

    if required_guarantors > 0 and not guarantors_complete:
        messages.error(
            request,
            f"Cannot approve loan. This loan requires {required_guarantors} guarantor(s) "
            f"but only {current_guarantors} have been added. "
            f"Please add the required guarantors before approval."
        )
        return redirect('core:loan_guarantors', loan_id=loan.id)

    # Check collateral requirements
    if loan.loan_product.requires_collateral:
        collaterals = loan.collaterals.filter(status__in=['verified', 'pending'])
        if not collaterals.exists():
            messages.error(
                request,
                "Cannot approve loan. This loan product requires collateral. "
                "Please add at least one collateral item before approval."
            )
            return redirect('core:loan_collaterals', loan_id=loan.id)

        min_ratio = loan.loan_product.min_collateral_value_ratio
        if min_ratio and min_ratio > Decimal('0.00'):
            total_value = collaterals.aggregate(
                total=Sum('value')
            )['total'] or Decimal('0.00')
            required_value = loan.principal_amount * min_ratio
            if total_value < required_value:
                messages.error(
                    request,
                    f"Collateral value (₦{total_value:,.2f}) is below the required minimum of "
                    f"₦{required_value:,.2f} ({min_ratio * 100:.0f}% of ₦{loan.principal_amount:,.2f} principal). "
                    f"Please add more collateral."
                )
                return redirect('core:loan_collaterals', loan_id=loan.id)

    if request.method == 'POST':
        form = LoanApprovalForm(request.POST, loan=loan)

        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            if decision == 'approve':
                approval_date = form.cleaned_data.get('approval_date')
                success, message = loan.approve(approved_by=request.user, approval_date=approval_date)
                if success:
                    messages.success(request, f"Loan approved successfully. {message}")
                    notify(
                        user=loan.created_by,
                        notification_type='loan_approved',
                        title='Loan Approved',
                        message=f'Loan {loan.loan_number} for {loan.client.get_full_name()} has been approved.',
                        related_loan=loan,
                        related_client=loan.client,
                    )
                    notify_role(
                        roles='manager',
                        branch=loan.branch,
                        notification_type='loan_approved',
                        title='Loan Approved',
                        message=f'Loan {loan.loan_number} of ₦{loan.principal_amount:,.2f} for {loan.client.get_full_name()} has been approved by {request.user.get_full_name()}.',
                        related_loan=loan,
                        related_client=loan.client,
                        exclude_user=request.user,
                    )
                    return redirect('core:loan_detail', loan_id=loan.id)
                else:
                    messages.error(request, f"Failed to approve loan: {message}")
            else:
                success, message = loan.reject(rejected_by=request.user, reason=notes, approval_date=approval_date)
                if success:
                    messages.success(request, f"Loan rejected. {message}")
                    notify(
                        user=loan.created_by,
                        notification_type='loan_rejected',
                        title='Loan Rejected',
                        message=f'Loan {loan.loan_number} for {loan.client.get_full_name()} has been rejected. Reason: {notes or "No reason given"}',
                        related_loan=loan,
                        related_client=loan.client,
                        is_urgent=True,
                    )
                    notify_role(
                        roles='manager',
                        branch=loan.branch,
                        notification_type='loan_rejected',
                        title='Loan Rejected',
                        message=f'Loan {loan.loan_number} for {loan.client.get_full_name()} was rejected by {request.user.get_full_name()}. Reason: {notes or "No reason given"}',
                        related_loan=loan,
                        related_client=loan.client,
                        is_urgent=True,
                        exclude_user=request.user,
                    )
                    return redirect('core:loan_detail', loan_id=loan.id)
                else:
                    messages.error(request, f"Failed to reject loan: {message}")
    else:
        form = LoanApprovalForm(loan=loan)

    # Get guarantor information for the template
    guarantors = loan.guarantors.select_related('linked_client').all()

    context = {
        'page_title': f'Approve Loan - {loan.loan_number}',
        'loan': loan,
        'form': form,
        'checker': checker,
        'guarantors': guarantors,
        'required_guarantors': required_guarantors,
        'current_guarantors': current_guarantors,
        'guarantors_complete': guarantors_complete,
    }

    return render(request, 'loans/approve.html', context)


# =============================================================================
# LOAN DISBURSE
# =============================================================================

@login_required
@transaction.atomic
def loan_disburse(request, loan_id):
    """
    Disburse an approved loan

    Permissions:
    - Only users with disburse_loans permission (Manager+)
    """
    loan = get_object_or_404(Loan, id=loan_id)
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied("You don't have permission to disburse loans")

    # Permission check for branch
    if checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You can only disburse loans for your branch")

    if loan.status != 'approved':
        messages.error(request, f"Cannot disburse loan with status: {loan.get_status_display()}")
        return redirect('core:loan_detail', loan_id=loan.id)

    if request.method == 'POST':
        form = LoanDisbursementForm(request.POST, loan=loan)

        if form.is_valid():
            # Update loan with disbursement details
            loan.bank_name = form.cleaned_data.get('bank_name', '')
            loan.bank_account_number = form.cleaned_data.get('bank_account_number', '')
            loan.bank_account_name = form.cleaned_data.get('bank_account_name', '')
            loan.disbursement_notes = form.cleaned_data.get('disbursement_notes', '')

            success, message = loan.disburse(
                disbursed_by=request.user,
                method=form.cleaned_data['disbursement_method'],
                reference=form.cleaned_data.get('disbursement_reference', ''),
                disbursement_date=form.cleaned_data.get('disbursement_date'),
            )

            if success:
                messages.success(request, f"Loan disbursed successfully. {message}")
                notify(
                    user=loan.created_by,
                    notification_type='loan_disbursed',
                    title='Loan Disbursed',
                    message=f'Loan {loan.loan_number} (₦{loan.amount_disbursed:,.2f}) for {loan.client.get_full_name()} has been disbursed.',
                    related_loan=loan,
                    related_client=loan.client,
                )
                if loan.client.assigned_staff and loan.client.assigned_staff != loan.created_by:
                    notify(
                        user=loan.client.assigned_staff,
                        notification_type='loan_disbursed',
                        title='Loan Disbursed',
                        message=f'Loan {loan.loan_number} (₦{loan.amount_disbursed:,.2f}) for your client {loan.client.get_full_name()} has been disbursed.',
                        related_loan=loan,
                        related_client=loan.client,
                    )
                notify_role(
                    roles='manager',
                    branch=loan.branch,
                    notification_type='loan_disbursed',
                    title='Loan Disbursed',
                    message=f'Loan {loan.loan_number} of ₦{loan.amount_disbursed:,.2f} for {loan.client.get_full_name()} has been disbursed by {request.user.get_full_name()}.',
                    related_loan=loan,
                    related_client=loan.client,
                    exclude_user=request.user,
                )
                return redirect('core:loan_detail', loan_id=loan.id)
            else:
                messages.error(request, f"Failed to disburse loan: {message}")
    else:
        form = LoanDisbursementForm(loan=loan)

    context = {
        'page_title': f'Disburse Loan - {loan.loan_number}',
        'loan': loan,
        'form': form,
        'checker': checker,
    }

    return render(request, 'loans/disburse.html', context)


# =============================================================================
# LOAN REPAYMENT POST (Single)
# =============================================================================

@login_required
@transaction.atomic
def loan_repayment_post(request, loan_id=None):
    """
    Post a single loan repayment

    Permissions:
    - All staff can post repayments

    Flow:
    1. Staff enters repayment details
    2. Creates LoanRepaymentPosting with status='pending'
    3. Awaits manager/director/admin approval
    """
    checker = PermissionChecker(request.user)

    loan = None
    if loan_id:
        loan = get_object_or_404(Loan, id=loan_id)

        # Permission check
        if checker.is_staff():
            if loan.client.assigned_staff != request.user:
                raise PermissionDenied("You don't have permission to access this loan")
        elif checker.is_manager():
            if loan.branch != request.user.branch:
                raise PermissionDenied("You don't have permission to access this loan")

    if request.method == 'POST':
        form = LoanRepaymentPostingForm(request.POST, user=request.user)

        if form.is_valid():
            posting = form.save(commit=False)
            posting.submitted_by = request.user
            posting.status = 'pending'

            # If posting from a specific loan page, set the loan
            if loan:
                posting.loan = loan

            posting.save()

            # Notify managers in both the staff's branch and the client's branch
            branches_to_notify = set()
            if request.user.branch:
                branches_to_notify.add(request.user.branch)
            if posting.loan.client.branch:
                branches_to_notify.add(posting.loan.client.branch)
            for branch in branches_to_notify:
                notify_role(
                    roles='manager',
                    branch=branch,
                    notification_type='repayment_posted',
                    title='Repayment Posted — Awaiting Approval',
                    message=(
                        f'{request.user.get_full_name()} posted a repayment of '
                        f'{posting.amount} for loan {posting.loan.loan_number} '
                        f'(client: {posting.loan.client.get_full_name()}). '
                        f'Awaiting your approval.'
                    ),
                    related_loan=posting.loan,
                    related_client=posting.loan.client,
                )

            messages.success(
                request,
                f'Repayment posting {posting.posting_ref} submitted successfully. '
                f'Awaiting approval from manager/director.'
            )

            return redirect('core:loan_repayment_list')
    else:
        initial = {}
        if loan:
            initial['loan'] = loan
            initial['amount'] = loan.installment_amount

        form = LoanRepaymentPostingForm(initial=initial, user=request.user)

    context = {
        'page_title': 'Post Loan Repayment',
        'form': form,
        'loan': loan,
        'checker': checker,
    }

    return render(request, 'loans/repayment_post.html', context)


# =============================================================================
# LOAN REPAYMENT POST BULK
# =============================================================================

@login_required
@transaction.atomic
def loan_repayment_post_bulk(request):
    """
    Post multiple loan repayments at once

    Permissions:
    - All staff can post repayments

    Flow:
    1. Staff selects loans from table and enters amounts
    2. Creates multiple LoanRepaymentPosting records
    3. All await approval
    """
    checker = PermissionChecker(request.user)

    # Get active/overdue loans for this user
    base_queryset = Loan.objects.filter(
        status__in=['active', 'overdue']
    ).select_related('client', 'branch', 'loan_product')

    if checker.is_staff():
        loans = base_queryset.filter(client__assigned_staff=request.user)
    elif checker.is_manager():
        loans = base_queryset.filter(branch=request.user.branch)
    else:
        loans = base_queryset

    loans = loans.order_by('-disbursement_date')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        payment_date = request.POST.get('payment_date')
        payment_reference = request.POST.get('payment_reference', '')

        # Collect selected loans and amounts
        created_postings = []
        errors = []

        for key, value in request.POST.items():
            if key.startswith('loan_'):
                loan_id = value
                amount_key = f'amount_{loan_id}'
                amount = request.POST.get(amount_key)

                if amount and float(amount) > 0:
                    try:
                        loan = Loan.objects.get(id=loan_id)

                        # Validate amount
                        amount_decimal = Decimal(amount)
                        if amount_decimal > loan.outstanding_balance:
                            errors.append(
                                f"{loan.loan_number}: Amount exceeds outstanding balance"
                            )
                            continue

                        # Create posting
                        posting = LoanRepaymentPosting.objects.create(
                            loan=loan,
                            amount=amount_decimal,
                            payment_method=payment_method,
                            payment_reference=payment_reference,
                            payment_date=payment_date,
                            submitted_by=request.user,
                            status='pending'
                        )
                        created_postings.append(posting)

                    except Loan.DoesNotExist:
                        errors.append(f"Loan {loan_id} not found")
                    except Exception as e:
                        errors.append(f"Error processing loan {loan_id}: {str(e)}")

        if created_postings:
            # Notify managers in the staff's branch and all clients' branches
            branches_to_notify = set()
            if request.user.branch:
                branches_to_notify.add(request.user.branch)
            for p in created_postings:
                if p.loan.client.branch:
                    branches_to_notify.add(p.loan.client.branch)
            for branch in branches_to_notify:
                notify_role(
                    roles='manager',
                    branch=branch,
                    notification_type='repayment_posted',
                    title='Repayments Posted — Awaiting Approval',
                    message=(
                        f'{request.user.get_full_name()} posted {len(created_postings)} '
                        f'repayment(s). Awaiting your approval.'
                    ),
                )

            messages.success(
                request,
                f'Successfully posted {len(created_postings)} repayment(s). '
                f'Awaiting approval from manager/director.'
            )

        if errors:
            for error in errors:
                messages.warning(request, error)

        if created_postings or errors:
            return redirect('core:loan_repayment_list')

        messages.error(request, "No repayments were selected or amounts entered.")

    context = {
        'page_title': 'Bulk Post Loan Repayments',
        'loans': loans,
        'checker': checker,
        'today': timezone.now().date().isoformat(),
    }

    return render(request, 'loans/repayment_post_bulk.html', context)


# =============================================================================
# LOAN REPAYMENT LIST
# =============================================================================

@login_required
def loan_repayment_list(request):
    """
    List all loan repayment postings

    Permissions:
    - All staff see their own postings
    - Managers/Directors/Admins see all postings for their scope
    """
    checker = PermissionChecker(request.user)

    # Base queryset
    postings = LoanRepaymentPosting.objects.select_related(
        'loan', 'client', 'branch', 'submitted_by', 'reviewed_by'
    ).all()

    # Permission filtering
    if checker.is_staff():
        postings = postings.filter(
            Q(submitted_by=request.user) |
            Q(loan__client__assigned_staff=request.user)
        )
    elif checker.is_manager():
        postings = postings.filter(branch=request.user.branch)
    # Admin/Director see all

    # Filter by status
    status_filter = request.GET.get('status', 'pending')
    if status_filter:
        postings = postings.filter(status=status_filter)

    # Order by submission date
    postings = postings.order_by('-submitted_at')

    # Pagination
    paginator = Paginator(postings, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Summary
    all_postings = LoanRepaymentPosting.objects.all()
    if checker.is_staff():
        all_postings = all_postings.filter(
            Q(submitted_by=request.user) |
            Q(loan__client__assigned_staff=request.user)
        )
    elif checker.is_manager():
        all_postings = all_postings.filter(branch=request.user.branch)

    summary = {
        'total_count': all_postings.count(),
        'pending_count': all_postings.filter(status='pending').count(),
        'approved_count': all_postings.filter(status='approved').count(),
        'rejected_count': all_postings.filter(status='rejected').count(),
        'pending_amount': all_postings.filter(status='pending').aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0.00'),
        'approved_amount': all_postings.filter(status='approved').aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0.00'),
    }

    context = {
        'page_title': 'Loan Repayment Postings',
        'postings': page_obj,
        'status_filter': status_filter,
        'summary': summary,
        'checker': checker,
    }

    return render(request, 'loans/repayment_list.html', context)


# =============================================================================
# LOAN REPAYMENT APPROVE (Single)
# =============================================================================

@login_required
@transaction.atomic
def loan_repayment_approve(request, posting_id):
    """
    Approve or reject a single repayment posting

    Permissions:
    - Only managers/directors/admins

    Flow:
    1. Show posting details
    2. Manager approves or rejects
    3. If approved: posting.approve() → loan.record_repayment() → create transaction
    4. If rejected: posting.reject() → store reason
    """
    posting = get_object_or_404(
        LoanRepaymentPosting.objects.select_related(
            'loan', 'client', 'branch', 'submitted_by'
        ),
        id=posting_id
    )

    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied("You don't have permission to approve repayments")

    # Check branch access
    if checker.is_manager() and posting.branch != request.user.branch:
        raise PermissionDenied("You can only approve repayments for your branch")

    if posting.status != 'pending':
        messages.error(
            request,
            f"Cannot process posting with status: {posting.get_status_display()}"
        )
        return redirect('core:loan_repayment_list')

    if request.method == 'POST':
        form = ApproveRepaymentPostingForm(request.POST, posting=posting)

        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            try:
                if decision == 'approve':
                    posting.approve(
                        approved_by=request.user,
                        transaction_date=form.cleaned_data.get('transaction_date'),
                    )
                    messages.success(
                        request,
                        f'Repayment posting {posting.posting_ref} approved successfully. '
                        f'Loan balance updated.'
                    )
                    # Notify the submitter
                    posting.loan.refresh_from_db(fields=['status'])
                    if posting.loan.status == 'completed':
                        notify(
                            user=posting.submitted_by,
                            notification_type='loan_completed',
                            title='Loan Fully Repaid',
                            message=f'Loan {posting.loan.loan_number} for {posting.loan.client.get_full_name()} is now fully repaid.',
                            related_loan=posting.loan,
                            related_client=posting.loan.client,
                        )
                    else:
                        notify(
                            user=posting.submitted_by,
                            notification_type='transaction_approved',
                            title='Repayment Approved',
                            message=f'Repayment posting {posting.posting_ref} of ₦{posting.amount:,.2f} for loan {posting.loan.loan_number} has been approved.',
                            related_loan=posting.loan,
                            related_client=posting.loan.client,
                        )
                    notify_role(
                        roles='manager',
                        branch=posting.loan.branch,
                        notification_type='transaction_approved',
                        title='Repayment Approved',
                        message=f'Repayment posting {posting.posting_ref} of ₦{posting.amount:,.2f} for loan {posting.loan.loan_number} ({posting.loan.client.get_full_name()}) approved by {request.user.get_full_name()}.',
                        related_loan=posting.loan,
                        related_client=posting.loan.client,
                        exclude_user=request.user,
                    )
                else:
                    posting.reject(rejected_by=request.user, reason=notes)
                    messages.success(
                        request,
                        f'Repayment posting {posting.posting_ref} rejected.'
                    )
                    notify(
                        user=posting.submitted_by,
                        notification_type='transaction_rejected',
                        title='Repayment Rejected',
                        message=f'Repayment posting {posting.posting_ref} for loan {posting.loan.loan_number} was rejected. Reason: {notes or "No reason given"}',
                        related_loan=posting.loan,
                        related_client=posting.loan.client,
                        is_urgent=True,
                    )
                    notify_role(
                        roles='manager',
                        branch=posting.loan.branch,
                        notification_type='transaction_rejected',
                        title='Repayment Rejected',
                        message=f'Repayment posting {posting.posting_ref} for loan {posting.loan.loan_number} ({posting.loan.client.get_full_name()}) was rejected by {request.user.get_full_name()}. Reason: {notes or "No reason given"}',
                        related_loan=posting.loan,
                        related_client=posting.loan.client,
                        is_urgent=True,
                        exclude_user=request.user,
                    )

                return redirect('core:loan_repayment_list')

            except ValidationError as e:
                messages.error(request, str(e))
    else:
        form = ApproveRepaymentPostingForm(posting=posting)

    context = {
        'page_title': f'Approve Repayment - {posting.posting_ref}',
        'posting': posting,
        'form': form,
        'loan': posting.loan,
        'checker': checker,
    }

    return render(request, 'loans/repayment_approve.html', context)


# =============================================================================
# LOAN REPAYMENT APPROVE BULK
# =============================================================================

@login_required
@transaction.atomic
def loan_repayment_approve_bulk(request):
    """
    Approve multiple repayment postings at once

    Permissions:
    - Only managers/directors/admins
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied("You don't have permission to approve repayments")

    # Base queryset: only pending postings within the user's scope
    postings_qs = LoanRepaymentPosting.objects.filter(status='pending')

    if checker.is_manager():
        postings_qs = postings_qs.filter(branch=request.user.branch)

    postings_qs = postings_qs.select_related('loan', 'client', 'submitted_by')

    if request.method == 'POST':
        selected_ids = request.POST.getlist('posting_ids')
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')

        if not selected_ids:
            messages.error(request, "Please select at least one posting")
            return redirect('core:loan_repayment_approve_bulk')

        selected_postings = postings_qs.filter(id__in=selected_ids)

        success_count = 0
        error_count = 0
        errors = []

        for posting in selected_postings:
            try:
                if action == 'approve':
                    posting.approve(approved_by=request.user)
                    success_count += 1
                elif action == 'reject':
                    posting.reject(rejected_by=request.user, reason=notes)
                    success_count += 1
            except ValidationError as e:
                error_count += 1
                errors.append(f"{posting.posting_ref}: {str(e)}")

        if success_count:
            messages.success(
                request,
                f'Successfully processed {success_count} repayment posting(s).'
            )

        if error_count:
            messages.warning(
                request,
                f'{error_count} posting(s) failed: ' + ', '.join(errors[:5])
            )

        return redirect('core:loan_repayment_list')

    # GET: filter to only the IDs selected on the list page
    ids_param = request.GET.get('ids', '')
    if ids_param:
        selected_ids = [i.strip() for i in ids_param.split(',') if i.strip()]
        postings_qs = postings_qs.filter(id__in=selected_ids)

    total_amount = postings_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    unique_loans_count = postings_qs.values('loan').distinct().count()

    context = {
        'page_title': 'Bulk Approve Repayments',
        'postings': postings_qs,
        'checker': checker,
        'total_amount': total_amount,
        'unique_loans_count': unique_loans_count,
    }

    return render(request, 'loans/repayment_approve_bulk.html', context)


# =============================================================================
# LOAN PRODUCT API
# =============================================================================

@login_required
def loan_product_api(request, product_id):
    """
    API endpoint to get loan product details for frontend calculator

    Returns JSON with:
    - Interest rate
    - Fee details with percentages
    - Loan limits
    """
    from django.http import JsonResponse

    try:
        product = LoanProduct.objects.get(id=product_id, is_active=True)
    except LoanProduct.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

    # Calculate fees for example principal (will be recalculated with actual principal)
    fees = product.calculate_fees(Decimal('10000'))  # Example calculation

    data = {
        'id': str(product.id),
        'name': product.name,
        'code': product.code,
        'loan_type': product.loan_type,
        'loan_type_display': product.get_loan_type_display(),
        'repayment_frequency':         product.repayment_frequency,
        'repayment_frequency_display': product.get_repayment_frequency_display(),

        # Interest rates
        'monthly_interest_rate': float(product.monthly_interest_rate),
        'annual_interest_rate': float(product.annual_interest_rate),
        'interest_calculation_method': product.interest_calculation_method,

        # Loan limits
        'min_principal': float(product.min_principal_amount),
        'max_principal': float(product.max_principal_amount),
        'min_duration_months': product.min_duration_months,
        'max_duration_months': product.max_duration_months,

        # Fee details
        'fees': {
            'risk_premium': {
                'enabled': product.risk_premium_enabled,
                'rate': float(product.risk_premium_rate) if product.risk_premium_enabled else 0,
                'rate_percent': float(product.risk_premium_rate * 100) if product.risk_premium_enabled else 0,
                'calculation': product.risk_premium_calculation if product.risk_premium_enabled else 'none',
            },
            'rp_income': {
                'enabled': product.rp_income_enabled,
                'rate': float(product.rp_income_rate) if product.rp_income_enabled else 0,
                'rate_percent': float(product.rp_income_rate * 100) if product.rp_income_enabled else 0,
                'calculation': product.rp_income_calculation if product.rp_income_enabled else 'none',
            },
            'tech_fee': {
                'enabled': product.tech_fee_enabled,
                'rate': float(product.tech_fee_rate) if product.tech_fee_enabled else 0,
                'rate_percent': float(product.tech_fee_rate * 100) if product.tech_fee_enabled else 0,
                'calculation': product.tech_fee_calculation if product.tech_fee_enabled else 'none',
            },
            'loan_form_fee': {
                'enabled': product.loan_form_fee_enabled,
                'amount': float(product.loan_form_fee_amount) if product.loan_form_fee_enabled else 0,
            },
        },

        # Requirements
        'requires_collateral': product.requires_collateral,
        'requires_guarantors': product.required_guarantors,
        'requires_insurance': product.requires_insurance,
        'min_membership_months': product.min_membership_months,
        'grace_period_days': product.grace_period_days,

        # Description
        'description': product.description or '',
    }

    return JsonResponse(data)


# =============================================================================
# LOAN GUARANTORS
# =============================================================================

@login_required
def loan_guarantors(request, loan_id):
    """
    Manage guarantors for a loan

    Shows current guarantors, how many are required,
    and allows adding/removing guarantors
    """
    loan = get_object_or_404(
        Loan.objects.select_related('client', 'loan_product', 'branch'),
        id=loan_id
    )

    checker = PermissionChecker(request.user)

    # Permission check
    if checker.is_staff():
        if loan.client.assigned_staff != request.user:
            raise PermissionDenied("You don't have permission to access this loan")
    elif checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You don't have permission to access this loan")

    # Get guarantors for this loan
    guarantors = loan.guarantors.select_related('linked_client', 'branch').all()

    # Calculate guarantor requirements
    required_guarantors = loan.loan_product.required_guarantors
    current_count = guarantors.count()
    remaining_count = max(0, required_guarantors - current_count)
    is_complete = current_count >= required_guarantors

    # Calculate total guaranteed amount
    total_guaranteed = guarantors.aggregate(Sum('guarantee_amount'))['guarantee_amount__sum'] or Decimal('0.00')

    context = {
        'page_title': f'Guarantors - {loan.loan_number}',
        'loan': loan,
        'guarantors': guarantors,
        'required_guarantors': required_guarantors,
        'current_count': current_count,
        'remaining_count': remaining_count,
        'is_complete': is_complete,
        'total_guaranteed': total_guaranteed,
        'checker': checker,
        'can_add_more': current_count < required_guarantors or not required_guarantors,
        'can_proceed_to_fees': is_complete and loan.status == 'pending_fees',
    }

    return render(request, 'loans/guarantors.html', context)


@login_required
@transaction.atomic
def loan_add_guarantor(request, loan_id):
    """
    Add a guarantor to a loan
    """
    loan = get_object_or_404(
        Loan.objects.select_related('client', 'loan_product', 'branch'),
        id=loan_id
    )

    checker = PermissionChecker(request.user)

    # Permission check
    if checker.is_staff():
        if loan.client.assigned_staff != request.user:
            raise PermissionDenied("You don't have permission to access this loan")
    elif checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You don't have permission to access this loan")

    # Check if loan can still have guarantors added
    if loan.status not in ['pending_fees', 'pending_approval']:
        messages.error(request, "Cannot add guarantors to this loan at this stage.")
        return redirect('core:loan_guarantors', loan_id=loan.id)

    # Calculate current vs required
    current_count = loan.guarantors.count()
    required_count = loan.loan_product.required_guarantors
    guarantor_number = current_count + 1

    if request.method == 'POST':
        form = GuarantorForm(request.POST, request.FILES, loan=loan, user=request.user)

        if form.is_valid():
            guarantor = form.save()

            messages.success(
                request,
                f'Guarantor {guarantor.name} added successfully.'
            )

            # Check if all guarantors are now complete
            new_count = loan.guarantors.count()
            if new_count >= required_count:
                messages.info(
                    request,
                    f'All {required_count} required guarantors have been added. '
                    f'You can now proceed to pay fees.'
                )
                return redirect('core:loan_guarantors', loan_id=loan.id)
            else:
                remaining = required_count - new_count
                messages.info(
                    request,
                    f'{remaining} more guarantor(s) required.'
                )
                return redirect('core:loan_add_guarantor', loan_id=loan.id)
    else:
        form = GuarantorForm(loan=loan, user=request.user)

    default_guarantee_amount = (
        loan.principal_amount / Decimal(str(loan.loan_product.required_guarantors or 1))
    ).quantize(Decimal('0.01'))

    context = {
        'page_title': f'Add Guarantor {guarantor_number} - {loan.loan_number}',
        'loan': loan,
        'form': form,
        'guarantor_number': guarantor_number,
        'required_count': required_count,
        'current_count': current_count,
        'checker': checker,
        'default_guarantee_amount': default_guarantee_amount,
    }

    return render(request, 'loans/guarantor_form.html', context)


@login_required
@transaction.atomic
def loan_edit_guarantor(request, loan_id, guarantor_id):
    """
    Edit an existing guarantor
    """
    loan = get_object_or_404(Loan, id=loan_id)
    guarantor = get_object_or_404(Guarantor, id=guarantor_id, loan=loan)

    checker = PermissionChecker(request.user)

    # Permission check
    if checker.is_staff():
        if loan.client.assigned_staff != request.user:
            raise PermissionDenied("You don't have permission to access this loan")
    elif checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You don't have permission to access this loan")

    # Check if loan can be edited
    if loan.status not in ['pending_fees', 'pending_approval']:
        messages.error(request, "Cannot edit guarantors for this loan at this stage.")
        return redirect('core:loan_guarantors', loan_id=loan.id)

    if request.method == 'POST':
        form = GuarantorForm(request.POST, request.FILES, instance=guarantor, loan=loan, user=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, f'Guarantor {guarantor.name} updated successfully.')
            return redirect('core:loan_guarantors', loan_id=loan.id)
    else:
        form = GuarantorForm(instance=guarantor, loan=loan, user=request.user)

    context = {
        'page_title': f'Edit Guarantor - {loan.loan_number}',
        'loan': loan,
        'guarantor': guarantor,
        'form': form,
        'is_edit': True,
        'checker': checker,
    }

    return render(request, 'loans/guarantor_form.html', context)


@login_required
@transaction.atomic
def loan_delete_guarantor(request, loan_id, guarantor_id):
    """
    Delete a guarantor from a loan
    """
    loan = get_object_or_404(Loan, id=loan_id)
    guarantor = get_object_or_404(Guarantor, id=guarantor_id, loan=loan)

    checker = PermissionChecker(request.user)

    # Permission check
    if checker.is_staff():
        if loan.client.assigned_staff != request.user:
            raise PermissionDenied("You don't have permission to access this loan")
    elif checker.is_manager():
        if loan.branch != request.user.branch:
            raise PermissionDenied("You don't have permission to access this loan")

    # Check if loan can be edited
    if loan.status not in ['pending_fees', 'pending_approval']:
        messages.error(request, "Cannot remove guarantors from this loan at this stage.")
        return redirect('core:loan_guarantors', loan_id=loan.id)

    if request.method == 'POST':
        guarantor_name = guarantor.name
        guarantor.delete()
        messages.success(request, f'Guarantor {guarantor_name} removed successfully.')
        return redirect('core:loan_guarantors', loan_id=loan.id)

    context = {
        'page_title': f'Delete Guarantor - {loan.loan_number}',
        'loan': loan,
        'guarantor': guarantor,
        'checker': checker,
    }

    return render(request, 'loans/guarantor_delete.html', context)


# =============================================================================
# BAD DEBT WRITE-OFF
# =============================================================================

@login_required
@transaction.atomic
def loan_write_off(request, loan_id):
    """
    Write off a loan as bad debt.

    Creates a journal entry:
      Dr 5050 Bad Debt Expense    = outstanding_balance + accrued_interest_balance
      Cr 1810 Loan Receivable     = outstanding_balance
      Cr 1820 Interest Receivable = accrued_interest_balance (if > 0)

    Sets loan.status = 'written_off' and zeroes the balances.

    Permissions: Director and Admin only.
    """
    checker = PermissionChecker(request.user)
    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors, HR Managers, and Administrators can write off loans.')
        raise PermissionDenied

    loan = get_object_or_404(
        Loan.objects.select_related('client', 'branch', 'loan_product'),
        id=loan_id,
    )

    if loan.status == 'written_off':
        messages.warning(request, 'This loan has already been written off.')
        return redirect('core:loan_detail', loan_id=loan.id)

    if loan.status not in ['active', 'overdue']:
        messages.error(request, f'Cannot write off a loan with status "{loan.get_status_display()}".')
        return redirect('core:loan_detail', loan_id=loan.id)

    outstanding = loan.outstanding_balance
    accrued = loan.accrued_interest_balance
    total_write_off = outstanding + accrued

    if total_write_off <= Decimal('0.00'):
        messages.error(request, 'This loan has no outstanding balance to write off.')
        return redirect('core:loan_detail', loan_id=loan.id)

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'Please provide a reason for the write-off.')
        else:
            try:
                today = timezone.now().date()
                ref = f'WRITE-OFF-{loan.loan_number}'

                lines = [
                    {
                        'account_code': '5050',
                        'debit': float(total_write_off),
                        'credit': 0,
                        'description': f'Bad debt write-off — {loan.loan_number}',
                        'client': loan.client,
                    },
                    {
                        'account_code': '1810',
                        'debit': 0,
                        'credit': float(outstanding),
                        'description': f'Loan principal written off — {loan.loan_number}',
                        'client': loan.client,
                    },
                ]
                if accrued > Decimal('0.00'):
                    lines.append({
                        'account_code': '1820',
                        'debit': 0,
                        'credit': float(accrued),
                        'description': f'Accrued interest written off — {loan.loan_number}',
                        'client': loan.client,
                    })

                create_journal_entry(
                    entry_type='other',
                    transaction_date=today,
                    branch=loan.branch,
                    description=f'Bad debt write-off: {loan.loan_number} — {reason[:100]}',
                    created_by=request.user,
                    lines=lines,
                    loan=loan,
                    reference_number=ref,
                    auto_post=True,
                )

                loan.status = 'written_off'
                loan.outstanding_balance = Decimal('0.00')
                loan.accrued_interest_balance = Decimal('0.00')
                loan.save(update_fields=['status', 'outstanding_balance', 'accrued_interest_balance', 'updated_at'])

                messages.success(
                    request,
                    f'Loan {loan.loan_number} has been written off. '
                    f'Journal entry {ref} posted.'
                )
                return redirect('core:loan_detail', loan_id=loan.id)

            except Exception as exc:
                messages.error(request, f'Write-off failed: {exc}')

    context = {
        'page_title': f'Write Off Loan — {loan.loan_number}',
        'loan': loan,
        'outstanding': outstanding,
        'accrued': accrued,
        'total_write_off': total_write_off,
        'checker': checker,
    }
    return render(request, 'loans/write_off.html', context)
