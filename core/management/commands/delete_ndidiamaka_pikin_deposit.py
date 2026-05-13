"""
Management command: delete_ndidiamaka_pikin_deposit
====================================================

Deletes an erroneous N33,750.00 deposit that was posted to Ndidiamaka
Uchechukwu's Children Savings account instead of not existing at all.

Records removed
---------------
  SavingsDepositPosting : 7ca2dd0e-03a1-44f6-b9d3-37a39e51d272  (SDP20260417084531M7WI3P)
  Transaction           : 9badab2c-d86b-4256-beb6-622a55220479  (TXN20260417084651785627)
  JournalEntry          : bd86d415-ff73-4553-afd1-84e7f0fbcfd9  (JE-20260415-891556)
    JournalEntryLine 207b19e9 - GL 1010 debit  33,750
    JournalEntryLine b96048c8 - GL 2040 credit 33,750

  SavingsAccount 2604170844474236 balance: 33,750 -> 0.00

Usage
-----
  python manage.py delete_ndidiamaka_pikin_deposit --dry-run
  python manage.py delete_ndidiamaka_pikin_deposit --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


POSTING_ID    = '7ca2dd0e-03a1-44f6-b9d3-37a39e51d272'
TXN_ID        = '9badab2c-d86b-4256-beb6-622a55220479'
JE_ID         = 'bd86d415-ff73-4553-afd1-84e7f0fbcfd9'
SA_ACCOUNT_NO = '2604170844474236'

AMOUNT        = Decimal('33750.00')
OLD_SA_BAL    = Decimal('33750.00')
NEW_SA_BAL    = Decimal('0.00')


class Command(BaseCommand):
    help = 'Delete erroneous Ndidiamaka Children Savings deposit (N33,750)'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import (
            SavingsDepositPosting, Transaction, JournalEntry, SavingsAccount
        )

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(
            f'\n=== delete_ndidiamaka_pikin_deposit [{mode}] ===\n'
        ))

        # 1. SavingsDepositPosting
        try:
            posting = SavingsDepositPosting.objects.get(id=POSTING_ID)
        except SavingsDepositPosting.DoesNotExist:
            raise CommandError(f'SavingsDepositPosting {POSTING_ID} not found.')

        self.stdout.write('SAVINGS DEPOSIT POSTING (will be DELETED)')
        self.stdout.write(f'  id          : {posting.id}')
        self.stdout.write(f'  posting_ref : {posting.posting_ref}')
        self.stdout.write(f'  amount      : {posting.amount}')
        self.stdout.write(f'  status      : {posting.status}')
        self._assert(posting.amount, AMOUNT, 'SavingsDepositPosting.amount')

        # 2. Transaction
        try:
            txn = Transaction.objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write('\nTRANSACTION (will be DELETED)')
        self.stdout.write(f'  id     : {txn.id}')
        self.stdout.write(f'  ref    : {txn.transaction_ref}')
        self.stdout.write(f'  amount : {txn.amount}')
        self._assert(txn.amount, AMOUNT, 'Transaction.amount')

        # 3. Journal Entry
        try:
            je = JournalEntry.objects.get(id=JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JE_ID} not found.')

        lines = list(je.lines.select_related('account'))
        self.stdout.write(f'\nJOURNAL ENTRY (will be DELETED): {je.journal_number}')
        total_debit = total_credit = Decimal('0.00')
        for line in lines:
            self.stdout.write(
                f'  GL {line.account.gl_code} ({line.account.account_name}): '
                f'debit={line.debit_amount}  credit={line.credit_amount}'
            )
            total_debit  += line.debit_amount
            total_credit += line.credit_amount
        if total_debit != AMOUNT or total_credit != AMOUNT:
            raise CommandError(
                f'JE balance mismatch: debit={total_debit} credit={total_credit} '
                f'expected {AMOUNT} each. Aborting.'
            )
        self.stdout.write(f'  Balance check: debit {total_debit} == credit {total_credit}  OK')

        # 4. SavingsAccount
        try:
            sa = SavingsAccount.objects.get(account_number=SA_ACCOUNT_NO)
        except SavingsAccount.DoesNotExist:
            raise CommandError(f'SavingsAccount {SA_ACCOUNT_NO} not found.')

        self.stdout.write(f'\nSAVINGS ACCOUNT {SA_ACCOUNT_NO}')
        self.stdout.write(f'  balance: {sa.balance}  ->  {NEW_SA_BAL}')
        self._assert(sa.balance, OLD_SA_BAL, f'SavingsAccount({SA_ACCOUNT_NO}).balance')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # 5. Apply atomically
        with db_transaction.atomic():
            # Revert savings account balance first
            sa.balance = NEW_SA_BAL
            sa.save(update_fields=['balance'])

            # Delete JE lines, JE, transaction, posting
            je.lines.all().delete()
            je.delete()
            txn.delete()
            posting.delete()

        self.stdout.write(self.style.SUCCESS('\nDeletion applied successfully.\n'))
        self.stdout.write('Summary:')
        self.stdout.write(f'  SavingsDepositPosting {POSTING_ID} - DELETED')
        self.stdout.write(f'  Transaction {TXN_ID} - DELETED')
        self.stdout.write(f'  JournalEntry {JE_ID} ({je.journal_number}) - DELETED')
        self.stdout.write(f'  SavingsAccount {SA_ACCOUNT_NO} balance: {OLD_SA_BAL} -> {NEW_SA_BAL}')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. Aborting.'
            )
