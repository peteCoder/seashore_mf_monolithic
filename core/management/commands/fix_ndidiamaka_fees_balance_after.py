"""
Management command: fix_ndidiamaka_fees_balance_after
======================================================

After the principal correction the fees transaction amount was updated
from N9,150 to N17,900 but the stored balance_after field was not
updated.  This command patches that single field.

  Transaction : 32ea6c33-e444-4924-a1df-a9e88c72ab67  (TXN20260417081643008087)
  balance_before : 0.00  (unchanged)
  balance_after  : 9,150.00  ->  17,900.00

Usage
-----
  python manage.py fix_ndidiamaka_fees_balance_after --dry-run
  python manage.py fix_ndidiamaka_fees_balance_after --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


TXN_ID        = '32ea6c33-e444-4924-a1df-a9e88c72ab67'
OLD_BAL_AFTER = Decimal('9150.00')
NEW_BAL_AFTER = Decimal('17900.00')
EXPECTED_AMOUNT = Decimal('17900.00')


class Command(BaseCommand):
    help = 'Fix balance_after on Ndidiamaka fees transaction (9150 -> 17900)'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import Transaction

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== fix_ndidiamaka_fees_balance_after [{mode}] ===\n'))

        try:
            txn = Transaction.objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write(f'  ref           : {txn.transaction_ref}')
        self.stdout.write(f'  amount        : {txn.amount}  (must be {EXPECTED_AMOUNT})')
        self.stdout.write(f'  balance_before: {txn.balance_before}  (unchanged)')
        self.stdout.write(f'  balance_after : {txn.balance_after}  ->  {NEW_BAL_AFTER}')

        if txn.amount != EXPECTED_AMOUNT:
            raise CommandError(
                f'Transaction.amount is {txn.amount}, expected {EXPECTED_AMOUNT}. '
                f'Run correct_ndidiamaka_fees --commit first.'
            )
        if txn.balance_after != OLD_BAL_AFTER:
            raise CommandError(
                f'balance_after is {txn.balance_after}, expected {OLD_BAL_AFTER}. Aborting.'
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        with db_transaction.atomic():
            txn.balance_after = NEW_BAL_AFTER
            txn.save(update_fields=['balance_after'])

        self.stdout.write(self.style.SUCCESS('\nDone.'))
        self.stdout.write(f'  Transaction.balance_after: {OLD_BAL_AFTER} -> {NEW_BAL_AFTER}')
