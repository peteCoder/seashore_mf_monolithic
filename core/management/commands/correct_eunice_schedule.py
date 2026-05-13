"""
Management command: correct_eunice_schedule
============================================

Shifts every due_date in Eunice Osaro's loan repayment schedule
forward by 7 days to account for the grace period that was set
after the schedule was generated.

Loan : ae2e1f66-216b-4ac8-bc11-c949235e8ec9  (LN20260430122851347915)

Before -> After
  Row  1 : 2026-05-05 -> 2026-05-12
  Row  2 : 2026-05-12 -> 2026-05-19
  ...
  Row 24 : 2026-10-13 -> 2026-10-20

Amounts and all other fields are unchanged.
No repayments have been made, so this is safe.

Usage
-----
  python manage.py correct_eunice_schedule --dry-run
  python manage.py correct_eunice_schedule --commit
"""

import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID      = 'ae2e1f66-216b-4ac8-bc11-c949235e8ec9'
EXPECTED_N   = 24
SHIFT_DAYS   = datetime.timedelta(days=7)

OLD_FIRST    = datetime.date(2026, 5, 5)
NEW_FIRST    = datetime.date(2026, 5, 12)
OLD_LAST     = datetime.date(2026, 10, 13)
NEW_LAST     = datetime.date(2026, 10, 20)


class Command(BaseCommand):
    help = 'Shift Eunice Osaro loan schedule dates by +7 days (May 5 -> May 12 first installment)'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import Loan, LoanRepaymentSchedule

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(
            f'\n=== correct_eunice_schedule [{mode}] ===\n'
        ))

        # Fetch loan
        try:
            loan = Loan.objects.get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        self.stdout.write(f'Loan : {loan.loan_number}')
        self.stdout.write(f'Client: {loan.client}')
        self.stdout.write(f'Status: {loan.status}')
        self.stdout.write(f'Amount paid: {loan.amount_paid}  (must be 0.00)')

        if loan.amount_paid != 0:
            raise CommandError(
                f'Loan has amount_paid={loan.amount_paid}. '
                f'Cannot shift dates on a partially repaid loan. Aborting.'
            )

        # Fetch schedule rows
        rows = list(
            LoanRepaymentSchedule.objects.filter(loan=loan).order_by('installment_number')
        )
        if len(rows) != EXPECTED_N:
            raise CommandError(
                f'Expected {EXPECTED_N} schedule rows, found {len(rows)}. Aborting.'
            )

        # Safety checks
        if rows[0].due_date != OLD_FIRST:
            raise CommandError(
                f'Row 1 due_date is {rows[0].due_date}, expected {OLD_FIRST}. Aborting.'
            )
        if rows[-1].due_date != OLD_LAST:
            raise CommandError(
                f'Row 24 due_date is {rows[-1].due_date}, expected {OLD_LAST}. Aborting.'
            )
        for row in rows:
            if row.amount_paid != 0:
                raise CommandError(
                    f'Row #{row.installment_number} has amount_paid={row.amount_paid}. Aborting.'
                )
            if row.status != 'pending':
                raise CommandError(
                    f'Row #{row.installment_number} has status={row.status!r} (expected pending). Aborting.'
                )

        self.stdout.write(f'\nShifting {EXPECTED_N} rows by +7 days:\n')
        self.stdout.write(f'  Row  1: {OLD_FIRST} -> {NEW_FIRST}')
        self.stdout.write(f'  Row  2: {rows[1].due_date} -> {rows[1].due_date + SHIFT_DAYS}')
        self.stdout.write(f'  ...')
        self.stdout.write(f'  Row 24: {OLD_LAST} -> {NEW_LAST}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # Apply atomically
        with db_transaction.atomic():
            for row in rows:
                row.due_date = row.due_date + SHIFT_DAYS
                row.save(update_fields=['due_date'])

        # Verify
        updated = LoanRepaymentSchedule.objects.filter(loan=loan).order_by('installment_number')
        first_date = updated.first().due_date
        last_date  = updated.last().due_date

        if first_date != NEW_FIRST or last_date != NEW_LAST:
            raise CommandError(
                f'Post-commit verification failed: first={first_date} last={last_date}'
            )

        self.stdout.write(self.style.SUCCESS('\nSchedule updated successfully.\n'))
        self.stdout.write(f'  First installment : {first_date}')
        self.stdout.write(f'  Last  installment : {last_date}')
        self.stdout.write(f'  All {EXPECTED_N} rows shifted by +7 days.')
