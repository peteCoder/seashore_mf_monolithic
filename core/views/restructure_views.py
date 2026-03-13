"""
Loan Restructure Views
======================
Submit, review, and apply loan restructure requests.
"""

from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import Loan, LoanRestructureRequest
from core.forms.restructure_forms import LoanRestructureRequestForm, LoanRestructureReviewForm
from core.permissions import PermissionChecker
from core.services.notification_service import notify


# =============================================================================
# RESTRUCTURE REQUEST LIST  (manager+ only)
# =============================================================================

@login_required
def restructure_list(request):
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can view restructure requests.')

    qs = LoanRestructureRequest.objects.select_related(
        'loan', 'loan__client', 'loan__branch', 'requested_by', 'approved_by'
    )

    if checker.is_manager():
        qs = qs.filter(loan__branch=request.user.branch)

    filter_by = request.GET.get('filter', 'pending')
    if filter_by == 'pending':
        qs = qs.filter(approval_status='pending')
    elif filter_by in ('approved', 'rejected'):
        qs = qs.filter(approval_status=filter_by)

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'restructures/list.html', {
        'page_title': 'Loan Restructure Requests',
        'requests': page_obj,
        'filter_by': filter_by,
        'checker': checker,
        'pending_count': LoanRestructureRequest.objects.filter(approval_status='pending').count(),
    })


# =============================================================================
# SUBMIT RESTRUCTURE REQUEST (nested under loan)
# =============================================================================

@login_required
def loan_restructure_request(request, loan_id):
    loan = get_object_or_404(
        Loan.objects.select_related('client', 'branch', 'loan_product'),
        id=loan_id,
    )
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if loan.status not in ('active', 'overdue'):
        messages.error(request, 'Restructure requests can only be submitted for active or overdue loans.')
        return redirect('core:loan_detail', loan_id=loan.id)

    # Check if there is already a pending request
    existing = LoanRestructureRequest.objects.filter(loan=loan, approval_status='pending').first()

    if request.method == 'POST':
        form = LoanRestructureRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.loan = loan
            req.requested_by = request.user
            req.current_duration = loan.duration_months
            req.current_installment = loan.installment_amount
            req.approval_status = 'pending'
            req.save()
            messages.success(
                request,
                'Restructure request submitted. A manager will review it shortly.'
            )
            return redirect('core:loan_detail', loan_id=loan.id)
    else:
        form = LoanRestructureRequestForm()

    return render(request, 'restructures/form.html', {
        'page_title': f'Request Loan Restructure — {loan.loan_number}',
        'loan': loan,
        'form': form,
        'existing': existing,
    })


# =============================================================================
# RESTRUCTURE REQUEST DETAIL
# =============================================================================

@login_required
def restructure_detail(request, request_id):
    req = get_object_or_404(
        LoanRestructureRequest.objects.select_related(
            'loan', 'loan__client', 'loan__branch', 'requested_by', 'approved_by'
        ),
        id=request_id,
    )
    checker = PermissionChecker(request.user)

    if not (checker.can_view_loan(req.loan) or checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    return render(request, 'restructures/detail.html', {
        'page_title': f'Restructure Request — {req.loan.loan_number}',
        'req': req,
        'loan': req.loan,
        'checker': checker,
    })


# =============================================================================
# APPROVE / REJECT RESTRUCTURE REQUEST
# =============================================================================

@login_required
@transaction.atomic
def restructure_approve(request, request_id):
    req = get_object_or_404(
        LoanRestructureRequest.objects.select_related(
            'loan', 'loan__client', 'loan__branch', 'requested_by'
        ),
        id=request_id,
    )
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can approve restructure requests.')

    if checker.is_manager() and req.loan.branch != request.user.branch:
        raise PermissionDenied('You can only approve restructure requests for your branch.')

    if req.approval_status != 'pending':
        messages.error(request, 'This request is no longer pending.')
        return redirect('core:restructure_list')

    if request.method == 'POST':
        form = LoanRestructureReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            review_notes = form.cleaned_data.get('review_notes', '')

            if decision == 'approve':
                req.approval_status = 'approved'
                req.approved_by = request.user
                req.approved_at = timezone.now()
                req.save()
                _execute_restructure(req)
                messages.success(
                    request,
                    f'Restructure approved. Loan {req.loan.loan_number} terms updated.'
                )
                notify(
                    user=req.requested_by,
                    notification_type='loan_approved',
                    title='Restructure Approved',
                    message=f'Your restructure request for loan {req.loan.loan_number} has been approved.',
                    related_loan=req.loan,
                    related_client=req.loan.client,
                )
            else:
                req.approval_status = 'rejected'
                req.approved_by = request.user
                req.approved_at = timezone.now()
                req.rejection_reason = review_notes
                req.save()
                messages.warning(request, 'Restructure request rejected.')
                notify(
                    user=req.requested_by,
                    notification_type='loan_rejected',
                    title='Restructure Rejected',
                    message=(
                        f'Your restructure request for loan {req.loan.loan_number} was rejected. '
                        f'Reason: {review_notes or "No reason given"}'
                    ),
                    related_loan=req.loan,
                    related_client=req.loan.client,
                    is_urgent=True,
                )

            return redirect('core:restructure_list')
    else:
        form = LoanRestructureReviewForm()

    return render(request, 'restructures/approve.html', {
        'page_title': f'Review Restructure — {req.loan.loan_number}',
        'req': req,
        'loan': req.loan,
        'form': form,
        'checker': checker,
    })


# =============================================================================
# REJECT SHORTCUT (separate URL → reuses same approval view logic)
# =============================================================================

@login_required
@transaction.atomic
def restructure_reject(request, request_id):
    """Redirect to the approval page (decision = reject handled there)."""
    return restructure_approve(request, request_id)


# =============================================================================
# PRIVATE: Execute the restructure on the loan
# =============================================================================

def _execute_restructure(req):
    """Apply approved restructure changes directly to the loan record."""
    loan = req.loan

    if req.restructure_type == 'extend_duration' and req.proposed_duration:
        loan.duration_months = req.proposed_duration
        # Recalculate installment: outstanding balance / remaining months
        if req.proposed_duration > 0:
            loan.installment_amount = (
                loan.outstanding_balance / Decimal(req.proposed_duration)
            ).quantize(Decimal('0.01'))
        loan.save(update_fields=['duration_months', 'installment_amount', 'updated_at'])

    elif req.restructure_type == 'reduce_installment' and req.proposed_installment:
        loan.installment_amount = req.proposed_installment
        loan.save(update_fields=['installment_amount', 'updated_at'])

    elif req.restructure_type == 'payment_holiday' and req.proposed_duration:
        # Advance next_repayment_date by the holiday months
        if loan.next_repayment_date:
            loan.next_repayment_date = loan.next_repayment_date + relativedelta(
                months=req.proposed_duration
            )
        else:
            loan.next_repayment_date = date.today() + relativedelta(months=req.proposed_duration)
        loan.save(update_fields=['next_repayment_date', 'updated_at'])

    elif req.restructure_type == 'capitalize_arrears':
        # If overdue, reset status to active (arrears already reflected in outstanding_balance)
        if loan.status == 'overdue':
            loan.status = 'active'
            loan.save(update_fields=['status', 'updated_at'])
