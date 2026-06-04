"""
Management command: fix_grace_period_schedule
==============================================

Fixes loans where grace_period_days=7 on Regular Loan / Med Loan caused the
first repayment date to land 14–18 days after disbursement (grace + 1 period)
instead of the correct 7–9 days (just 1 period, no grace).

ROOT CAUSE
----------
LoanProduct.grace_period_days was set to 7 for Regular Loan and Med Loan.
disburse() does:
    schedule_start = disbursement_date + grace_period_days   # +7 days
    first_repayment = calculate_next_payment_date(schedule_start) # +7 more days
Total: disbursement + 14 days instead of disbursement + 7 days.

WHAT THIS COMMAND DOES
-----------------------
1. Sets grace_period_days=0 on Regular Loan and Med Loan (affects new loans).
2. For every active/overdue loan with these products whose first_repayment_date
   is 10+ days after disbursement:
   a. Recomputes the correct first_repayment_date (grace=0, using holidays).
   b. Shifts ALL schedule rows forward/backward by the difference.
   c. Updates Loan.first_repayment_date, next_repayment_date,
      final_repayment_date by the same amount.

After running this command, run:
    python manage.py reallocate_schedule_by_postings --commit
to re-allocate payments using date-matched logic.

Usage
-----
    python manage.py fix_grace_period_schedule --dry-run
    python manage.py fix_grace_period_schedule --dry-run --loan-id <UUID>
    python manage.py fix_grace_period_schedule --commit
    python manage.py fix_grace_period_schedule --commit --loan-id <UUID>
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.utils import timezone

from core.models import Loan, LoanProduct, LoanRepaymentSchedule
from core.models.all_models import PublicHoliday
from core.utils.helpers import next_business_day

# Products whose grace_period_days introduced the double-period bug.
AFFECTED_PRODUCT_NAMES = ['Regular Loan', 'Med Loan']

# Only fix loans where the gap between disbursement and first scheduled
# repayment is at least this many days (catches the 14–18 day cases).
MIN_GAP_DAYS = 10


class Command(BaseCommand):
    help = (
        'Fix schedules that started 14 days after disbursement instead of 7 '
        'due to grace_period_days=7 doubling the first payment period.'
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true',
                          help='Show changes without writing to DB')
        mode.add_argument('--commit', action='store_true',
                          help='Apply the changes')
        parser.add_argument('--loan-id', metavar='UUID',
                            help='Process a single loan only')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        loan_id = options.get('loan_id')
        mode = 'DRY RUN' if dry_run else 'COMMIT'

        self.stdout.write(self.style.WARNING(
            f'\n=== fix_grace_period_schedule [{mode}] ===\n'
        ))

        # Load holidays once for all date calculations.
        holidays = set(PublicHoliday.objects.values_list('date', flat=True))

        # ------------------------------------------------------------------ #
        # Step 1 — Fix LoanProduct.grace_period_days                         #
        # ------------------------------------------------------------------ #
        affected_products = LoanProduct.objects.filter(
            name__in=AFFECTED_PRODUCT_NAMES,
            grace_period_days__gt=0,
        )
        if affected_products.exists():
            self.stdout.write('Loan products to fix:')
            for lp in affected_products:
                self.stdout.write(
                    f'  {lp.name!r}: grace_period_days={lp.grace_period_days} -> 0'
                )
            if not dry_run:
                affected_products.update(grace_period_days=0)
                self.stdout.write(self.style.SUCCESS('  -> grace_period_days set to 0'))
        else:
            self.stdout.write('  (No products need grace_period_days fix)\n')

        # ------------------------------------------------------------------ #
        # Step 2 — Fix existing loan schedules                                #
        # ------------------------------------------------------------------ #
        all_affected_products = LoanProduct.objects.filter(
            name__in=AFFECTED_PRODUCT_NAMES
        )

        schedule_prefetch = Prefetch(
            'repayment_schedule',
            queryset=LoanRepaymentSchedule.objects.order_by('installment_number'),
            to_attr='ordered_schedule',
        )

        loan_qs = Loan.objects.filter(
            loan_product__in=all_affected_products,
            status__in=['active', 'overdue'],
        ).select_related('loan_product').prefetch_related(schedule_prefetch)

        if loan_id:
            loan_qs = loan_qs.filter(id=loan_id)

        total_loans = loan_qs.count()
        loans_fixed = 0
        rows_fixed = 0

        self.stdout.write(f'\nScope: {total_loans} active/overdue loan(s) with affected products\n')

        for loan in loan_qs:
            if not loan.disbursement_date or not loan.first_repayment_date:
                continue

            # Use local (Nigeria) date, matching the fixed disburse() logic.
            disburse_date = timezone.localtime(loan.disbursement_date).date()
            current_first = loan.first_repayment_date
            gap = (current_first - disburse_date).days

            if gap < MIN_GAP_DAYS:
                continue  # Already correct (was disbursed before the bug)

            # Correct first_repayment_date: no grace period, just 1 weekly period
            correct_first = next_business_day(
                disburse_date + timedelta(weeks=1), holidays
            )
            shift = current_first - correct_first  # positive = rows are too late

            if shift.days <= 0:
                continue  # Nothing to fix

            rows = loan.ordered_schedule
            client_name = loan.client.get_full_name() if loan.client else '?'

            self.stdout.write(
                f'LOAN {loan.loan_number} -- {client_name}  '
                f'[gap={gap}d, shift=-{shift.days}d]'
            )
            self.stdout.write(
                f'  first_repayment: {current_first} -> {correct_first}'
            )
            if rows:
                new_last = rows[-1].due_date - shift
                self.stdout.write(
                    f'  last_row       : {rows[-1].due_date} -> {new_last}'
                )
            self.stdout.write(f'  rows           : {len(rows)}')

            if not dry_run:
                with db_transaction.atomic():
                    # Shift all schedule rows
                    for row in rows:
                        row.due_date = row.due_date - shift
                    if rows:
                        LoanRepaymentSchedule.objects.bulk_update(rows, ['due_date'])

                    # Update loan-level date fields
                    update_fields = ['updated_at']
                    loan.first_repayment_date = correct_first
                    update_fields.append('first_repayment_date')

                    if loan.next_repayment_date:
                        loan.next_repayment_date = loan.next_repayment_date - shift
                        update_fields.append('next_repayment_date')

                    if loan.final_repayment_date:
                        loan.final_repayment_date = loan.final_repayment_date - shift
                        update_fields.append('final_repayment_date')

                    loan.save(update_fields=update_fields)

            loans_fixed += 1
            rows_fixed += len(rows)

        # ------------------------------------------------------------------ #
        # Summary                                                             #
        # ------------------------------------------------------------------ #
        self.stdout.write(f'\n{"-" * 60}')
        self.stdout.write(
            f'Loans {"to fix" if dry_run else "fixed"} : {loans_fixed}'
        )
        self.stdout.write(
            f'Rows  {"to fix" if dry_run else "fixed"} : {rows_fixed}'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete — no changes written.\n'
                'Re-run with --commit to apply, then run:\n'
                '  python manage.py reallocate_schedule_by_postings --commit\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n[OK] {loans_fixed} loan(s) fixed.\n'
                'Now run:\n'
                '  python manage.py reallocate_schedule_by_postings --commit\n'
                'to re-allocate payments by date.\n'
            ))
