"""
Transaction Reversal Service
=============================
Reverses a completed transaction:
  - Marks the original transaction as 'reversed'
  - Creates a matching reversal transaction record
  - Reverses all journal entries tied to the transaction
  - For loan_repayment: restores outstanding_balance & repayment schedule rows
  - For deposit:        reduces savings account balance
  - For withdrawal:     adds back to savings account balance
"""

from decimal import Decimal
import datetime as _dt

from django.db import transaction as db_transaction
from django.utils import timezone

from core.models import (
    Transaction, JournalEntry, Loan,
    SavingsAccount, LoanRepaymentSchedule,
)


REVERSIBLE_TYPES = {'loan_repayment', 'deposit', 'withdrawal'}


@db_transaction.atomic
def reverse_transaction(txn, reversed_by, reason):
    """
    Fully reverse a completed transaction.

    Args:
        txn:          Transaction instance (must be status='completed')
        reversed_by:  User performing the reversal
        reason:       Reason string (required)

    Returns:
        reversal_txn: The new reversal Transaction record

    Raises:
        ValueError: if the transaction cannot be reversed
    """
    txn = Transaction.objects.select_for_update().get(pk=txn.pk)

    if txn.status != 'completed':
        raise ValueError(f"Only completed transactions can be reversed (status: {txn.status})")

    if txn.transaction_type not in REVERSIBLE_TYPES:
        raise ValueError(
            f"Reversal is not supported for '{txn.transaction_type}' transactions."
        )

    # Map the reversal transaction type
    reversal_type_map = {
        'loan_repayment': 'reversal',
        'deposit':        'reversal',
        'withdrawal':     'reversal',
    }

    reversal_txn = Transaction.objects.create(
        transaction_type=reversal_type_map[txn.transaction_type],
        amount=txn.amount,
        principal_amount=txn.principal_amount,
        interest_amount=txn.interest_amount,
        client=txn.client,
        savings_account=txn.savings_account,
        loan=txn.loan,
        branch=txn.branch,
        processed_by=reversed_by,
        description=f"Reversal of {txn.transaction_ref}: {reason}",
        reversed_transaction=txn,
        status='completed',
        transaction_date=timezone.now(),
    )

    # Reverse every posted journal entry linked to the original transaction
    for je in JournalEntry.objects.filter(transaction=txn, status='posted'):
        je.reverse(reversed_by=reversed_by, reason=reason)

    # Mark original as reversed
    txn.status = 'reversed'
    txn.notes = (
        (txn.notes + '\n' if txn.notes else '') +
        f"Reversed by {reversed_by.get_full_name()} on "
        f"{timezone.now().strftime('%Y-%m-%d %H:%M')}. Reason: {reason}"
    )
    txn.save(update_fields=['status', 'notes', 'updated_at'])

    # --- financial impact ---
    if txn.transaction_type == 'loan_repayment':
        _restore_loan_repayment(txn, reversal_txn)
    elif txn.transaction_type == 'deposit':
        _restore_savings_deposit(txn, reversal_txn)
    elif txn.transaction_type == 'withdrawal':
        _restore_savings_withdrawal(txn, reversal_txn)

    return reversal_txn


def _restore_loan_repayment(txn, reversal_txn):
    """Restore loan outstanding balance and repayment schedule rows."""
    loan = Loan.objects.select_for_update().get(pk=txn.loan_id)

    if txn.balance_before is not None:
        loan.outstanding_balance = txn.balance_before
    else:
        loan.outstanding_balance = loan.outstanding_balance + txn.amount
    loan.amount_paid = max(Decimal('0.00'), loan.amount_paid - txn.amount)

    if loan.status == 'completed' and loan.outstanding_balance > Decimal('0.00'):
        loan.status = 'active'
        loan.completion_date = None

    loan.save(update_fields=[
        'outstanding_balance', 'amount_paid', 'status',
        'completion_date', 'updated_at',
    ])

    remaining = txn.amount
    rows = (
        LoanRepaymentSchedule.objects
        .select_for_update()
        .filter(loan=loan, amount_paid__gt=Decimal('0.00'))
        .order_by('-installment_number')
    )

    today = timezone.now().date()
    for row in rows:
        if remaining <= Decimal('0.00'):
            break
        reduction = min(row.amount_paid, remaining)
        row.amount_paid -= reduction
        remaining -= reduction

        if row.amount_paid <= Decimal('0.00'):
            row.amount_paid = Decimal('0.00')
            row.outstanding_amount = row.total_amount
            row.paid_date = None
            row.status = 'overdue' if row.due_date < today else 'pending'
        else:
            row.outstanding_amount = row.total_amount - row.amount_paid
            row.status = 'partial'

        row.save(update_fields=[
            'amount_paid', 'outstanding_amount', 'paid_date', 'status', 'updated_at',
        ])

    reversal_txn.balance_before = txn.balance_after
    reversal_txn.balance_after = loan.outstanding_balance
    reversal_txn.save(update_fields=['balance_before', 'balance_after'])


def _restore_savings_deposit(txn, reversal_txn):
    """Reduce savings balance to undo a deposit."""
    account = SavingsAccount.objects.select_for_update().get(pk=txn.savings_account_id)
    account.balance = max(Decimal('0.00'), account.balance - txn.amount)
    account.save(update_fields=['balance', 'updated_at'])

    reversal_txn.balance_before = account.balance + txn.amount
    reversal_txn.balance_after = account.balance
    reversal_txn.save(update_fields=['balance_before', 'balance_after'])


def _restore_savings_withdrawal(txn, reversal_txn):
    """Add back the withdrawn amount to savings balance."""
    account = SavingsAccount.objects.select_for_update().get(pk=txn.savings_account_id)
    account.balance += txn.amount
    account.save(update_fields=['balance', 'updated_at'])

    reversal_txn.balance_before = account.balance - txn.amount
    reversal_txn.balance_after = account.balance
    reversal_txn.save(update_fields=['balance_before', 'balance_after'])
