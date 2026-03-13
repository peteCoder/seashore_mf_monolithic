"""
Loan Penalty Views
==================
Create, waive, and mark-paid loan penalties.
"""

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Loan, LoanPenalty
from core.forms.penalty_forms import LoanPenaltyForm, LoanPenaltyWaiveForm
from core.permissions import PermissionChecker
from core.utils.accounting_helpers import create_journal_entry, get_cash_account_for_branch


# =============================================================================
# LIST PENALTIES FOR A LOAN
# =============================================================================

@login_required
def loan_penalties(request, loan_id):
    loan = get_object_or_404(
        Loan.objects.select_related('client', 'branch', 'loan_product'),
        id=loan_id,
    )
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    penalties = loan.penalties.select_related('waived_by', 'created_by').order_by('-created_at')

    from django.db.models import Sum
    summary = {
        'total': penalties.count(),
        'outstanding': penalties.filter(is_paid=False, is_waived=False).aggregate(
            t=Sum('amount')
        )['t'] or Decimal('0.00'),
        'paid': penalties.filter(is_paid=True).aggregate(t=Sum('amount'))['t'] or Decimal('0.00'),
        'waived': penalties.filter(is_waived=True).aggregate(t=Sum('amount'))['t'] or Decimal('0.00'),
    }

    return render(request, 'loans/penalties.html', {
        'page_title': f'Penalties — {loan.loan_number}',
        'loan': loan,
        'penalties': penalties,
        'summary': summary,
        'checker': checker,
    })


# =============================================================================
# ADD PENALTY
# =============================================================================

@login_required
def loan_add_penalty(request, loan_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if request.method == 'POST':
        form = LoanPenaltyForm(request.POST)
        if form.is_valid():
            penalty = form.save(commit=False)
            penalty.loan = loan
            penalty.created_by = request.user
            penalty.save()
            messages.success(
                request,
                f'Penalty of ₦{penalty.amount:,.2f} ({penalty.get_penalty_type_display()}) added to loan {loan.loan_number}.'
            )
            return redirect('core:loan_penalties', loan_id=loan.id)
    else:
        form = LoanPenaltyForm()

    return render(request, 'loans/penalty_form.html', {
        'page_title': f'Add Penalty — {loan.loan_number}',
        'loan': loan,
        'form': form,
    })


# =============================================================================
# WAIVE PENALTY
# =============================================================================

@login_required
def loan_waive_penalty(request, loan_id, penalty_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    penalty = get_object_or_404(LoanPenalty, id=penalty_id, loan=loan)
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can waive penalties.')

    if penalty.is_paid or penalty.is_waived:
        messages.error(request, 'This penalty has already been paid or waived.')
        return redirect('core:loan_penalties', loan_id=loan.id)

    if request.method == 'POST':
        form = LoanPenaltyWaiveForm(request.POST)
        if form.is_valid():
            penalty.waive(waived_by=request.user, reason=form.cleaned_data['waiver_reason'])
            messages.success(
                request,
                f'Penalty of ₦{penalty.amount:,.2f} waived successfully.'
            )
            return redirect('core:loan_penalties', loan_id=loan.id)
    else:
        form = LoanPenaltyWaiveForm()

    return render(request, 'loans/penalty_waive.html', {
        'page_title': f'Waive Penalty — {loan.loan_number}',
        'loan': loan,
        'penalty': penalty,
        'form': form,
    })


# =============================================================================
# MARK PENALTY AS PAID  (creates journal entry)
# =============================================================================

@login_required
@require_POST
@transaction.atomic
def loan_mark_penalty_paid(request, loan_id, penalty_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    penalty = get_object_or_404(LoanPenalty, id=penalty_id, loan=loan)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if penalty.is_paid:
        messages.error(request, 'This penalty has already been paid.')
        return redirect('core:loan_penalties', loan_id=loan.id)

    if penalty.is_waived:
        messages.error(request, 'This penalty has been waived and cannot be marked as paid.')
        return redirect('core:loan_penalties', loan_id=loan.id)

    try:
        cash_account = get_cash_account_for_branch(loan.branch)

        create_journal_entry(
            entry_type='penalty_payment',
            transaction_date=timezone.now().date(),
            branch=loan.branch,
            description=f'Penalty payment — Loan {loan.loan_number} ({penalty.get_penalty_type_display()})',
            created_by=request.user,
            lines=[
                {
                    'account_code': cash_account.gl_code,
                    'debit': penalty.amount,
                    'credit': 0,
                    'description': f'Cash received: penalty on loan {loan.loan_number}',
                    'client': loan.client,
                },
                {
                    'account_code': '4170',   # Late Payment Fee Income
                    'debit': 0,
                    'credit': penalty.amount,
                    'description': f'Penalty income: {penalty.get_penalty_type_display()} — {loan.loan_number}',
                    'client': loan.client,
                },
            ],
            loan=loan,
            auto_post=True,
        )

        penalty.mark_paid()
        messages.success(
            request,
            f'Penalty of ₦{penalty.amount:,.2f} marked as paid. Journal entry posted.'
        )
    except Exception as exc:
        messages.error(request, f'Failed to record penalty payment: {exc}')

    return redirect('core:loan_penalties', loan_id=loan.id)
