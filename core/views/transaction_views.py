"""
Transaction Views
=================

Views for displaying transaction details
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied

from core.models import Transaction
from core.permissions import PermissionChecker


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

    context = {
        'page_title': f'Transaction Details: {transaction.transaction_ref}',
        'transaction': transaction,
    }

    return render(request, 'transactions/detail.html', context)
