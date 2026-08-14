"""
Repayment schedule allocation
==============================

Single source of truth for turning "total amount ever received on a loan"
into a per-installment amount_paid/status/paid_date state.

WHY THIS EXISTS
---------------
record_repayment() used to allocate incrementally: on each new payment, walk
the currently-unpaid rows oldest-first and add just this payment's cash to
them. That's correct *only if every prior payment was also allocated
correctly* — if an older/buggy code path (or a manual correction) ever
misapplied a historical payment to the wrong row, the incremental approach
has no way to notice or repair it. A row already marked 'paid' is excluded
from all future allocation, so a wrong allocation stays wrong forever, and
the schedule can end up showing a 'Paid' row sitting after 'Overdue' rows —
money that landed on a later installment while earlier ones were skipped.

allocate_schedule_from_total() instead treats the schedule as a pure
function of ONE number: the total amount ever received on the loan. Every
call recomputes every row's amount_paid from scratch, oldest row first,
with no memory of the previous (possibly wrong) state. This makes the
schedule self-healing: any historical misallocation gets corrected the very
next time a payment is recorded on that loan, by construction, without a
separate manual rebuild.

Used by:
  - Loan.record_repayment()                          (every live repayment)
  - management/commands/rebuild_loan_schedules.py     (bulk/manual rebuild)
"""
from decimal import Decimal


def allocate_schedule_from_total(rows, total_received, completion_date):
    """
    Recompute amount_paid for every row from the loan's total amount
    received, allocated oldest-installment-first.

    Args:
        rows: schedule rows for ONE loan, already ordered by
            installment_number ascending. Every row is considered — not
            just currently-unpaid ones — because a row currently marked
            'paid' may need to be corrected back down if it was previously
            misallocated (see module docstring).
        total_received: Decimal — total amount ever received on the loan
            (e.g. Loan.amount_paid, or the sum of approved postings).
        completion_date: date to stamp on any row that newly becomes fully
            paid by this allocation and doesn't already have a paid_date.
            Callers that know the exact payment date should pass that;
            callers doing a bulk/manual rebuild with no single payment date
            to point to should pass today's date.

    Returns:
        (changes, next_due)
        changes  — [(row, new_amount_paid), ...] for rows whose amount_paid
                   actually changed (row objects are mutated in place with
                   the new amount_paid/paid_date — caller still needs to
                   .save() each one to persist).
        next_due — due_date of the first row that isn't fully paid after
                   this allocation, or None if every row is fully paid.
    """
    row_total  = {r.id: r.total_amount + r.penalty_amount for r in rows}
    allocation = {r.id: Decimal('0.00') for r in rows}

    remaining = Decimal(str(total_received))
    if remaining < 0:
        remaining = Decimal('0.00')

    for row in rows:
        if remaining <= Decimal('0.00'):
            break
        owed = row_total[row.id] - allocation[row.id]
        if owed <= 0:
            continue
        apply = min(remaining, owed)
        allocation[row.id] += apply
        remaining -= apply

    changes  = []
    next_due = None
    for row in rows:
        new_paid = allocation[row.id].quantize(Decimal('0.01'))
        full     = row_total[row.id]

        if next_due is None and new_paid < full:
            next_due = row.due_date

        if new_paid == row.amount_paid:
            continue

        if new_paid >= full:
            if not row.paid_date:
                row.paid_date = completion_date
        else:
            # Row is no longer fully paid (only possible if it had been
            # incorrectly marked paid before) — clear any stale paid_date
            # rather than leave it pointing at a completion that, per the
            # corrected allocation, didn't actually happen on this row.
            row.paid_date = None

        changes.append((row, new_paid))

    return changes, next_due
