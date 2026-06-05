"""
Transaction Views
=================

Views for displaying and reversing transaction details
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from core.models import Transaction, JournalEntry
from core.permissions import PermissionChecker
from core.services.reversal_service import reverse_transaction, REVERSIBLE_TYPES


# =============================================================================
# TRANSACTION DETAIL VIEW
# =============================================================================

@login_required
def transaction_detail(request, transaction_id):
    """
    View detailed information about a specific transaction

    Permissions: All authenticated users can view transactions
    """
    transaction = get_object_or_404(
        Transaction.objects.select_related(
            'client',
            'savings_account',
            'loan',
            'branch',
            'processed_by',
            'approved_by'
        ),
        id=transaction_id
    )

    checker = PermissionChecker(request.user)

    # Check if user has permission to view this transaction
    # Staff can only view transactions from their branch
    if not checker.is_admin_or_director():
        if checker.is_manager():
            if transaction.branch != request.user.branch:
                messages.error(request, 'You do not have permission to view this transaction.')
                raise PermissionDenied
        elif checker.is_staff():
            # Staff can only view transactions for their assigned clients
            if transaction.client and transaction.client.assigned_staff != request.user:
                messages.error(request, 'You do not have permission to view this transaction.')
                raise PermissionDenied

    linked_journals = JournalEntry.objects.filter(transaction=transaction).select_related('branch')

    context = {
        'page_title': f'Transaction Details: {transaction.transaction_ref}',
        'transaction': transaction,
        'linked_journals': linked_journals,
        'can_reverse': (
            transaction.status == 'completed' and
            transaction.transaction_type in REVERSIBLE_TYPES
        ),
    }

    return render(request, 'transactions/detail.html', context)


# =============================================================================
# TRANSACTION REVERSAL VIEW
# =============================================================================

@login_required
def transaction_reverse(request, transaction_id):
    """
    Reverse a completed transaction.
    Accessible to managers, admins, and directors only.
    """
    checker = PermissionChecker(request.user)
    if not checker.is_admin_or_director():
        raise PermissionDenied("Only HR, directors, and admins can reverse transactions.")

    txn = get_object_or_404(
        Transaction.objects.select_related(
            'client', 'savings_account', 'loan', 'branch', 'processed_by',
        ),
        id=transaction_id,
    )

    if txn.status != 'completed':
        messages.error(request, f'This transaction cannot be reversed (status: {txn.get_status_display()}).')
        return redirect('core:transaction_detail', transaction_id=txn.id)

    if txn.transaction_type not in REVERSIBLE_TYPES:
        messages.error(request, f'Reversal is not supported for {txn.get_transaction_type_display()} transactions.')
        return redirect('core:transaction_detail', transaction_id=txn.id)

    linked_journals = JournalEntry.objects.filter(transaction=txn).select_related('branch')

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'A reason is required to reverse a transaction.')
        else:
            try:
                reversal = reverse_transaction(txn=txn, reversed_by=request.user, reason=reason)
                messages.success(
                    request,
                    f'Transaction {txn.transaction_ref} reversed successfully. '
                    f'Reversal ref: {reversal.transaction_ref}.'
                )
                return redirect('core:transaction_detail', transaction_id=txn.id)
            except Exception as exc:
                messages.error(request, f'Reversal failed: {exc}')

    context = {
        'page_title': f'Reverse Transaction — {txn.transaction_ref}',
        'txn': txn,
        'linked_journals': linked_journals,
        'checker': checker,
    }
    return render(request, 'transactions/reverse.html', context)
