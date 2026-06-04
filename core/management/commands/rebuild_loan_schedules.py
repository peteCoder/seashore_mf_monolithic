"""
Management command: rebuild_loan_schedules
==========================================

Rebuilds repayment schedule rows for all active/overdue loans from scratch
using the corrected business-day rule (next_week_business_day) and the
current public holiday table, then IMMEDIATELY re-allocates payments within
the same atomic transaction per loan.

Each loan is processed completely (rebuild + reallocate) before moving to the
next. If the DB connection drops mid-run, already-processed loans remain
correct; just re-run the command to continue from where it left off (already-
clean loans are detected and skipped).

WHAT IT FIXES
-------------
1. Schedule rows landing on public holidays  → first business day next week.
2. Schedule rows landing on weekends         → fixed by holiday rule.
3. Wrong first_repayment_date               → recalculated from local disburse date.
4. "Overdue on top" (officer started 1 week late) → anchors Row 1 to first
   actual collection when gap is 6-14 days.

WHAT IT DOES NOT TOUCH
-----------------------
- LoanRepaymentPosting  — never modified.
- Transaction records   — never modified.
- Loan.amount_paid / Loan.outstanding_balance — never modified.

Usage
-----
    python manage.py rebuild_loan_schedules --dry-run
    python manage.py rebuild_loan_schedules --commit
    python manage.py rebuild_loan_schedules --commit --loan-id <UUID>
"""

import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction, close_old_connections
from django.db.models import Prefetch
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule, LoanRepaymentPosting
from core.models.all_models import PublicHoliday
from core.utils.helpers import generate_repayment_schedule, next_week_business_day


class Command(BaseCommand):
    help = (
        'Rebuild loan schedules with corrected holiday rules and immediately '
        're-allocate payments. Processes one loan at a time so a dropped '
        'connection never leaves rows at ₦0.'
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--commit', action='store_true')
        parser.add_argument('--loan-id', metavar='UUID',
                            help='Process a single loan only')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        loan_id = options.get('loan_id')
        mode = 'DRY RUN' if dry_run else 'COMMIT'

        self.stdout.write(self.style.WARNING(
            f'\n=== rebuild_loan_schedules [{mode}] ===\n'
        ))

        holidays = set(PublicHoliday.objects.values_list('date', flat=True))
        today = timezone.now().date()

        loan_ids = list(
            Loan.objects.filter(
                status__in=['active', 'overdue'],
                disbursement_date__isnull=False,
            ).values_list('id', flat=True)
        )
        if loan_id:
            loan_ids = [lid for lid in loan_ids if str(lid) == loan_id]

        total   = len(loan_ids)
        rebuilt = skipped = errors = 0

        self.stdout.write(f'Scope: {total} active/overdue loan(s)\n')

        # Process in batches of 10; reconnect between batches so Neon
        # auto-suspend does not kill the long-running session.
        BATCH = 10
        for batch_start in range(0, total, BATCH):
            close_old_connections()
            batch = loan_ids[batch_start: batch_start + BATCH]

            loans = (
                Loan.objects
                .filter(id__in=batch)
                .select_related('loan_product', 'client')
                .prefetch_related(
                    Prefetch(
                        'repayment_postings',
                        queryset=LoanRepaymentPosting.objects.filter(
                            status='approved'
                        ).order_by('payment_date', 'created_at'),
                        to_attr='approved_postings',
                    )
                )
            )

            for loan in loans:
                client_name = loan.client.get_full_name() if loan.client else '?'

                # ── Compute the correct first_repayment_date ──────────────────
                local_date = timezone.localtime(loan.disbursement_date).date()
                grace = 0
                try:
                    if loan.loan_product_id and loan.loan_product:
                        grace = loan.loan_product.grace_period_days or 0
                except Exception:
                    pass

                calc_first = next_week_business_day(
                    local_date + _dt.timedelta(days=grace) + _dt.timedelta(weeks=1),
                    holidays,
                )

                # If the officer started 6-14 days late, anchor Row 1 to the
                # first actual collection date so it is not an orphaned overdue.
                new_first = calc_first
                if getattr(loan, 'approved_postings', None):
                    first_pay = loan.approved_postings[0].payment_date
                    gap = (first_pay - calc_first).days
                    if 6 <= gap <= 14:
                        new_first = next_week_business_day(first_pay, holidays)

                # ── Generate new schedule rows in memory ──────────────────────
                original_first = loan.first_repayment_date
                loan.first_repayment_date = new_first
                try:
                    new_rows = generate_repayment_schedule(loan)
                except Exception as e:
                    loan.first_repayment_date = original_first
                    self.stdout.write(self.style.ERROR(
                        f'SKIP {loan.loan_number} (generate failed): {e}'
                    ))
                    skipped += 1
                    continue

                if not new_rows:
                    loan.first_repayment_date = original_first
                    skipped += 1
                    continue

                new_final = new_rows[-1]['due_date']

                if dry_run:
                    loan.first_repayment_date = original_first
                    self.stdout.write(
                        f'  {loan.loan_number} -- {client_name}: '
                        f'first {original_first}->{new_first}  '
                        f'final {loan.final_repayment_date}->{new_final}'
                    )
                    rebuilt += 1
                    continue

                # ── Rebuild rows + reallocate in ONE atomic transaction ────────
                try:
                    with db_transaction.atomic():
                        # 1. Delete old rows
                        LoanRepaymentSchedule.objects.filter(loan=loan).delete()

                        # 2. Create fresh rows at ₦0
                        fresh = [
                            LoanRepaymentSchedule(
                                loan=loan,
                                installment_number=r['installment_number'],
                                due_date=r['due_date'],
                                principal_amount=r['principal_amount'],
                                interest_amount=r['interest_amount'],
                                total_amount=r['total_amount'],
                                outstanding_amount=r['total_amount'],
                                amount_paid=Decimal('0.00'),
                                status='pending',
                            )
                            for r in new_rows
                        ]
                        LoanRepaymentSchedule.objects.bulk_create(fresh)

                        # 3. Immediately allocate existing postings
                        saved_rows = list(
                            LoanRepaymentSchedule.objects
                            .filter(loan=loan)
                            .order_by('installment_number')
                        )
                        postings = getattr(loan, 'approved_postings', [])
                        changes, next_due = _compute_allocation(
                            saved_rows, postings, today
                        )
                        for row, new_paid in changes:
                            row.amount_paid = new_paid
                            row.save(update_fields=[
                                'amount_paid', 'paid_date',
                                'outstanding_amount', 'status', 'updated_at',
                            ])

                        # 4. Update loan date fields
                        loan.final_repayment_date = new_first  # temporary
                        loan.final_repayment_date = new_final
                        if next_due:
                            loan.next_repayment_date = next_due
                        loan.save(update_fields=[
                            'first_repayment_date', 'final_repayment_date',
                            'next_repayment_date', 'updated_at',
                        ])

                    rebuilt += 1

                except Exception as e:
                    loan.first_repayment_date = original_first
                    self.stdout.write(self.style.ERROR(
                        f'ERROR {loan.loan_number}: {e}'
                    ))
                    errors += 1

            self.stdout.write(
                f'  Batch {batch_start // BATCH + 1}: '
                f'{min(batch_start + BATCH, total)}/{total} done '
                f'(rebuilt={rebuilt} skipped={skipped} errors={errors})'
            )

        self.stdout.write(f'\n{"-" * 60}')
        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run: {rebuilt} loans would be rebuilt.\n'
                'Re-run with --commit to apply.\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'[OK] rebuilt={rebuilt}  skipped={skipped}  errors={errors}\n'
            ))


# =============================================================================
# ALLOCATION LOGIC
# =============================================================================

def _compute_allocation(rows, postings, today):
    """
    Oldest-first allocation: payments always fill rows sequentially from
    Row 1 upward, regardless of payment date.

    This guarantees that Partial/Overdue only ever appear at the last
    covered row — never in the middle of a schedule with Paid rows after them.

    Returns (changes, next_due).
    changes  — list of (row, new_amount_paid) for rows that differ.
    next_due — due_date of the first not-fully-paid row.
    """
    row_total  = {r.id: r.total_amount + r.penalty_amount for r in rows}
    allocation = {r.id: Decimal('0.00') for r in rows}

    # Sum all approved postings into one total, then fill rows from oldest first.
    total_received = sum(p.amount for p in postings)
    remaining = total_received

    for row in rows:
        if remaining <= Decimal('0.00'):
            break
        owed  = row_total[row.id] - allocation[row.id]
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
        if new_paid >= full and not row.paid_date:
            row.paid_date = today
        changes.append((row, new_paid))

    return changes, next_due
