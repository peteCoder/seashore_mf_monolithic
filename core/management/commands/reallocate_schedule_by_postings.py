"""
Management command: reallocate_schedule_by_postings
====================================================

Re-allocates LoanRepaymentSchedule.amount_paid across rows using the
shared oldest-first allocation algorithm — the same one
Loan.record_repayment() runs on every live repayment and
rebuild_loan_schedules.py uses for its bulk rebuilds (see
core/utils/repayment_allocation.py). This command exists to apply that
SAME reallocation to loans manually, on demand, WITHOUT also regenerating
schedule dates (due_date, first_repayment_date, holiday-landing
corrections) the way rebuild_loan_schedules.py does — useful when a loan's
dates are already correct and the only problem is which row a historical
payment landed on.

PROBLEM BEING FIXED
-------------------
An older version of record_repayment() could "anchor" a payment to
whichever schedule row's due_date was closest to the payment date instead
of always filling the oldest unpaid row first. That let a later
installment get marked 'paid' while earlier ones were skipped entirely —
a schedule showing 'Paid' after 'Overdue' rows, money that was collected
but landed on the wrong installment.

WHAT THIS COMMAND DOES
-----------------------
For every active/overdue/disbursed loan with approved postings:

1. Sums all approved postings into one total-received figure and
   reallocates every row from scratch, oldest installment first (see
   allocate_schedule_from_total()).
2. Compares the re-derived per-row amounts against what is currently
   stored and reports/updates any row that differs.

SAFE vs NEEDS REVIEW
---------------------
A loan is [SAFE] if the reallocation only fills previously-empty/partial
rows further — no row that's currently 'paid' gets undone. Those are
applied automatically on --commit.

A loan is [NEEDS REVIEW] if the reallocation would flip a currently-'paid'
row back to overdue/partial/pending — i.e. it exposes that the money
marked against that row actually belongs to an earlier, still-unpaid
installment. Since this changes what looks like a completed collection
into a missed one, these are SKIPPED unless --force is also passed, after
reviewing them individually with --loan-id.

SAFE TO RUN REPEATEDLY — all checks are idempotent.

Usage
-----
  python manage.py reallocate_schedule_by_postings --dry-run
  python manage.py reallocate_schedule_by_postings --dry-run --loan-id <UUID>
  python manage.py reallocate_schedule_by_postings --commit
  python manage.py reallocate_schedule_by_postings --commit --loan-id <UUID>
  python manage.py reallocate_schedule_by_postings --commit --force --loan-id <UUID>
"""

from decimal import Decimal
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule, LoanRepaymentPosting
from core.utils.repayment_allocation import allocate_schedule_from_total



class Command(BaseCommand):
    help = (
        'Re-allocate schedule row payments by posting date instead of oldest-first, '
        'fixing rows that show overdue despite having a nearby collection.'
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true',
                          help='Show what would change without writing to the DB')
        mode.add_argument('--commit', action='store_true',
                          help='Apply the changes')
        parser.add_argument('--loan-id', metavar='UUID',
                            help='Process a single loan only')
        parser.add_argument('--force', action='store_true',
                            help='Also apply changes where currently-paid rows '
                                 'would become overdue (exposes missed collections). '
                                 'Use --loan-id to review individual loans first.')

    def handle(self, *args, **options):
        dry_run  = options['dry_run']
        loan_id  = options.get('loan_id')
        force    = options.get('force', False)
        today    = timezone.now().date()
        mode     = 'DRY RUN' if dry_run else ('COMMIT --force' if force else 'COMMIT')

        self.stdout.write(self.style.WARNING(
            f'\n=== reallocate_schedule_by_postings [{mode}] ===\n'
        ))

        # ── Load loans + schedules + postings in bulk ─────────────────────
        schedule_prefetch = Prefetch(
            'repayment_schedule',
            queryset=LoanRepaymentSchedule.objects.order_by('installment_number'),
            to_attr='ordered_schedule',
        )
        posting_prefetch = Prefetch(
            'repayment_postings',
            queryset=LoanRepaymentPosting.objects.filter(
                status='approved'
            ).order_by('payment_date', 'created_at'),
            to_attr='approved_postings',
        )

        loan_qs = Loan.objects.filter(
            status__in=['active', 'overdue', 'disbursed'],
        ).prefetch_related(schedule_prefetch, posting_prefetch)

        if loan_id:
            loan_qs = loan_qs.filter(id=loan_id)

        total_loans         = loan_qs.count()
        safe_loans          = 0
        safe_rows           = 0
        review_loans        = 0
        review_rows         = 0
        rows_inspected      = 0
        review_loan_list    = []

        scope = f'loan {loan_id}' if loan_id else f'{total_loans} active/overdue loans'
        self.stdout.write(f'Scope : {scope}\n')

        for loan in loan_qs:
            rows     = loan.ordered_schedule
            postings = loan.approved_postings

            if not rows or not postings:
                continue

            rows_inspected += len(rows)
            changes = _compute_reallocation(rows, postings, today)
            if not changes:
                continue

            # Classify: does any currently-paid row lose its paid status?
            has_unpay = any(
                old_s == 'paid' and new_s in ('overdue', 'partial', 'pending')
                for _, _, _, old_s, new_s in changes
            )
            needs_review = has_unpay

            label = '[NEEDS REVIEW]' if needs_review else '[SAFE]'
            label_style = self.style.WARNING(label) if needs_review else self.style.SUCCESS(label)

            self.stdout.write(
                f'{label_style} LOAN {loan.loan_number} -- '
                f'{loan.client.get_full_name() if loan.client else "?"}'
            )
            for row, old_paid, new_paid, old_status, new_status in changes:
                flag = ' *** UN-PAYING' if (old_status == 'paid' and new_status != 'paid') else \
                       '  -> CLEARED'  if (old_status in ('overdue','partial') and new_status == 'paid') else ''
                self.stdout.write(
                    f'  Row {row.installment_number:>3} (due {row.due_date}): '
                    f'paid {old_paid} -> {new_paid}  '
                    f'status {old_status} -> {new_status}{flag}'
                )

            # ── Apply ─────────────────────────────────────────────────────
            should_apply = not dry_run and (not needs_review or force)
            if should_apply:
                with db_transaction.atomic():
                    for row, old_paid, new_paid, old_status, new_status in changes:
                        row.amount_paid = new_paid
                        if new_paid == Decimal('0.00'):
                            row.paid_date = None
                        elif new_paid >= (row.total_amount + row.penalty_amount) and not row.paid_date:
                            row.paid_date = today
                        row.save(update_fields=[
                            'amount_paid', 'paid_date',
                            'outstanding_amount', 'status', 'updated_at',
                        ])

            if needs_review:
                review_loans += 1
                review_rows  += len(changes)
                review_loan_list.append(loan.loan_number)
            else:
                safe_loans += 1
                safe_rows  += len(changes)

        # ── Summary ───────────────────────────────────────────────────────
        self.stdout.write(f'\n{"-" * 60}')
        self.stdout.write(f'Loans processed           : {total_loans}')
        self.stdout.write(f'Rows inspected            : {rows_inspected}')
        self.stdout.write(
            self.style.SUCCESS(f'[SAFE]   loans/rows changed   : {safe_loans} / {safe_rows}')
        )
        self.stdout.write(
            self.style.WARNING(f'[REVIEW] loans/rows skipped   : {review_loans} / {review_rows}')
        )

        if review_loan_list and not force:
            self.stdout.write(
                '\n[NEEDS REVIEW] loans have paid rows that would become overdue '
                '(missed collections exposed).\n'
                'These were SKIPPED. Use --loan-id <UUID> to review each one,\n'
                'then re-run with --commit --force to apply after verifying.\n'
            )
            self.stdout.write('Skipped loans:')
            for ln in review_loan_list:
                self.stdout.write(f'  {ln}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete -- no changes written. Re-run with --commit to apply.\n'
            ))
        elif not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'\n[OK] Safe re-allocation applied: {safe_rows} row(s) across '
                f'{safe_loans} loan(s).\n'
            ))


# =============================================================================
# CORE ALGORITHM
# =============================================================================

def _compute_reallocation(rows, postings, today):
    """
    Given a loan's schedule rows (ordered by installment_number) and its
    approved postings (ordered by payment_date), compute the correct
    per-row amount_paid via the shared oldest-first allocation algorithm
    (allocate_schedule_from_total — the same one record_repayment() and
    rebuild_loan_schedules.py use).

    Returns a list of (row, old_amount_paid, new_amount_paid,
                        old_status, new_status)
    for every row where the new allocation differs from what is stored.
    """
    total_received = sum(p.amount for p in postings)

    # Capture "before" state up front — allocate_schedule_from_total() may
    # mutate row.paid_date on the same objects (harmless in dry-run since
    # nothing is saved unless the caller explicitly does so), but
    # amount_paid/computed_status must be read as they stood beforehand.
    old_paid_by_id   = {r.id: r.amount_paid for r in rows}
    old_status_by_id = {r.id: r.computed_status for r in rows}
    row_total_by_id  = {r.id: r.total_amount + r.penalty_amount for r in rows}

    schedule_changes, _next_due = allocate_schedule_from_total(
        rows, total_received, today,
    )

    changes = []
    for row, new_paid in schedule_changes:
        full = row_total_by_id[row.id]
        if new_paid >= full:
            new_status = 'paid'
        elif new_paid > Decimal('0.00'):
            new_status = 'partial'
        elif row.due_date < today:
            new_status = 'overdue'
        else:
            new_status = 'pending'

        changes.append((
            row, old_paid_by_id[row.id], new_paid,
            old_status_by_id[row.id], new_status,
        ))

    return changes
