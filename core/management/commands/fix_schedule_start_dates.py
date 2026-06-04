"""
Management command: fix_schedule_start_dates
=============================================

Fixes loans where the repayment schedule starts before the first actual
collection was made, causing the oldest rows to appear as "overdue" even
though the loan officer started collecting the following week.

ROOT CAUSE
----------
When a loan is disbursed, the schedule is generated with the first due date
based on the product's grace period (typically 7 days = 1 week after
disbursement).  In practice, many loan officers begin collecting the NEXT
week (2 weeks after disbursement), leaving the first scheduled row as a
"permanently missed" installment that the oldest-first allocator silently
absorbs.

EXAMPLE
-------
  Loan disbursed : Apr 23  (grace period = 7 days)
  First due row  : Apr 30  (7 days after disbursement)
  First payment  : May 07  (14 days after disbursement — officer started 1 week late)

  With oldest-first allocation the May 07 payment covers Apr 30's row.
  Clients see Rows 4 & 5 (May 21 / May 29) as overdue even though the officer
  collected on those exact dates.

WHAT THIS COMMAND DOES
-----------------------
For every active/overdue loan:
1. Finds the first approved posting date (the real first collection date).
2. Compares it to the first schedule row's due_date.
3. If the gap is 6–14 days (i.e., one full week late), shifts ALL schedule
   rows forward by that same gap (days).
4. Updates Loan.first_repayment_date, next_repayment_date, final_repayment_date
   to match.

After running this command, run:
  python manage.py reallocate_schedule_by_postings --commit
to re-allocate payments using date-matched logic.

Usage
-----
  python manage.py fix_schedule_start_dates --dry-run
  python manage.py fix_schedule_start_dates --dry-run --loan-id <UUID>
  python manage.py fix_schedule_start_dates --commit
  python manage.py fix_schedule_start_dates --commit --loan-id <UUID>
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule, LoanRepaymentPosting


# Only shift when the first payment arrived 6–14 days after the first due row.
# A gap of exactly 7 days = officer started exactly 1 week late (most common).
# We cap at 14 days to avoid accidentally shifting loans that were genuinely
# late by more than 2 weeks.
MIN_GAP_DAYS = 6
MAX_GAP_DAYS = 14


class Command(BaseCommand):
    help = (
        'Shift schedule start dates forward to match the actual first collection '
        'date for loans where the officer started collecting one week late.'
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
        mode    = 'DRY RUN' if dry_run else 'COMMIT'

        self.stdout.write(self.style.WARNING(
            f'\n=== fix_schedule_start_dates [{mode}] ===\n'
        ))

        # Load in bulk — 2 queries total
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
            to_attr='approved_postings_list',
        )

        loan_qs = Loan.objects.filter(
            status__in=['active', 'overdue', 'disbursed'],
        ).prefetch_related(schedule_prefetch, posting_prefetch)

        if loan_id:
            loan_qs = loan_qs.filter(id=loan_id)

        total_loans   = loan_qs.count()
        loans_shifted = 0
        rows_shifted  = 0

        self.stdout.write(f'Scope: {total_loans} active/overdue loans\n')

        gap_distribution = {}

        for loan in loan_qs:
            rows     = loan.ordered_schedule
            postings = loan.approved_postings_list

            if not rows or not postings:
                continue

            first_row_date    = rows[0].due_date
            first_posting_date = postings[0].payment_date

            gap = (first_posting_date - first_row_date).days

            if not (MIN_GAP_DAYS <= gap <= MAX_GAP_DAYS):
                continue

            shift = timedelta(days=gap)
            gap_distribution[gap] = gap_distribution.get(gap, 0) + 1

            client_name = loan.client.get_full_name() if loan.client else '?'
            self.stdout.write(
                f'LOAN {loan.loan_number} -- {client_name}  '
                f'[gap={gap}d, shift=+{gap}d]'
            )
            self.stdout.write(
                f'  First row : {first_row_date} -> {first_row_date + shift}'
            )
            self.stdout.write(
                f'  Last row  : {rows[-1].due_date} -> {rows[-1].due_date + shift}'
            )
            self.stdout.write(
                f'  Rows      : {len(rows)}'
            )

            if not dry_run:
                with db_transaction.atomic():
                    # Shift all schedule rows
                    for row in rows:
                        row.due_date = row.due_date + shift
                        # Don't touch amount_paid, status, outstanding — those
                        # are handled by reallocate_schedule_by_postings
                    LoanRepaymentSchedule.objects.bulk_update(rows, ['due_date'])

                    # Update loan-level date fields
                    update_fields = ['updated_at']
                    if loan.first_repayment_date:
                        loan.first_repayment_date += shift
                        update_fields.append('first_repayment_date')
                    if loan.next_repayment_date:
                        loan.next_repayment_date += shift
                        update_fields.append('next_repayment_date')
                    if loan.final_repayment_date:
                        loan.final_repayment_date += shift
                        update_fields.append('final_repayment_date')
                    loan.save(update_fields=update_fields)

            loans_shifted += 1
            rows_shifted  += len(rows)

        # Summary
        self.stdout.write(f'\n{"-" * 60}')
        self.stdout.write(f'Loans {"to shift" if dry_run else "shifted"} : {loans_shifted}')
        self.stdout.write(f'Rows  {"to shift" if dry_run else "shifted"} : {rows_shifted}')

        if gap_distribution:
            self.stdout.write('\nGap distribution:')
            for g, count in sorted(gap_distribution.items()):
                self.stdout.write(f'  {g:>2} days late: {count} loan(s)')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete -- no changes written.\n'
                'Re-run with --commit to apply, then run:\n'
                '  python manage.py reallocate_schedule_by_postings --commit\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n[OK] {loans_shifted} loan(s) shifted.\n'
                'Now run:\n'
                '  python manage.py reallocate_schedule_by_postings --commit\n'
                'to re-allocate payments by date.\n'
            ))
