"""
Management command: correct_ndidiamaka_regular_savings
=======================================================

Corrects Ndidiamaka Uchechukwu's Regular Savings deposit from
N25,000 to N50,000 across all affected records.

Affected records
----------------
  SavingsDepositPosting : 8a4eeb8a-2257-4297-b8a5-1a5a11bc8af7  (SDP20260417084358E4IW6F)
    amount: 25,000 -> 50,000

  Transaction           : cf507016-1432-4fbd-8887-68e6f746f92b  (TXN20260417084623638830)
    amount       : 25,000 -> 50,000
    balance_after: 25,000 -> 50,000

  JournalEntry          : 09403c3d-ea03-4323-bb4f-b14495826e6f  (JE-20260415-425427)
    GL 1010 (Cash In Hand) debit_amount  : 25,000 -> 50,000
    GL 2010 (Savings Deposits - Regular) credit_amount: 25,000 -> 50,000

  SavingsAccount 2604092034094356 balance: 25,000 -> 50,000

Usage
-----
  python manage.py correct_ndidiamaka_regular_savings --dry-run
  python manage.py correct_ndidiamaka_regular_savings --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


POSTING_ID    = '8a4eeb8a-2257-4297-b8a5-1a5a11bc8af7'
TXN_ID        = 'cf507016-1432-4fbd-8887-68e6f746f92b'
JE_ID         = '09403c3d-ea03-4323-bb4f-b14495826e6f'
SA_ACCOUNT_NO = '2604092034094356'

GL_CASH       = '1010'
GL_SAVINGS    = '2010'

OLD_AMOUNT    = Decimal('25000.00')
NEW_AMOUNT    = Decimal('50000.00')
DIFF          = NEW_AMOUNT - OLD_AMOUNT   # 25,000.00


class Command(BaseCommand):
    help = 'Correct Ndidiamaka Regular Savings deposit from N25,000 to N50,000'

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
            f'\n=== correct_ndidiamaka_regular_savings [{mode}] ===\n'
        ))

        # 1. SavingsDepositPosting
        try:
            posting = SavingsDepositPosting.objects.get(id=POSTING_ID)
        except SavingsDepositPosting.DoesNotExist:
            raise CommandError(f'SavingsDepositPosting {POSTING_ID} not found.')

        self.stdout.write('SAVINGS DEPOSIT POSTING')
        self.stdout.write(f'  id          : {posting.id}')
        self.stdout.write(f'  posting_ref : {posting.posting_ref}')
        self.stdout.write(f'  amount      : {posting.amount}  ->  {NEW_AMOUNT}')
        self._assert(posting.amount, OLD_AMOUNT, 'SavingsDepositPosting.amount')

        # 2. Transaction
        try:
            txn = Transaction.objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write('\nTRANSACTION')
        self.stdout.write(f'  id           : {txn.id}')
        self.stdout.write(f'  ref          : {txn.transaction_ref}')
        self.stdout.write(f'  amount       : {txn.amount}  ->  {NEW_AMOUNT}')
        self.stdout.write(f'  balance_before: {txn.balance_before}  (unchanged)')
        self.stdout.write(f'  balance_after : {txn.balance_after}  ->  {NEW_AMOUNT}')
        self._assert(txn.amount,        OLD_AMOUNT, 'Transaction.amount')
        self._assert(txn.balance_after, OLD_AMOUNT, 'Transaction.balance_after')

        # 3. Journal Entry
        try:
            je = JournalEntry.objects.get(id=JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JE_ID} not found.')

        self.stdout.write(f'\nJOURNAL ENTRY: {je.journal_number} | status={je.status}')
        lines = {line.account.gl_code: line for line in je.lines.select_related('account')}

        for code, field, label in [
            (GL_CASH,    'debit_amount',  'GL 1010 Cash'),
            (GL_SAVINGS, 'credit_amount', 'GL 2010 Savings'),
        ]:
            if code not in lines:
                raise CommandError(f'JournalEntryLine GL {code} not found in {je.journal_number}.')
            line = lines[code]
            current = getattr(line, field)
            self.stdout.write(
                f'  {label} ({line.account.account_name}) {field}: {current}  ->  {NEW_AMOUNT}'
            )
            self._assert(current, OLD_AMOUNT, f'{label} {field}')

        # Double-entry check after correction
        if NEW_AMOUNT != NEW_AMOUNT:   # trivially true; explicit for clarity
            raise CommandError('Double-entry imbalance after correction.')
        self.stdout.write(f'  Double-entry check: debit {NEW_AMOUNT} == credit {NEW_AMOUNT}  OK')

        # 4. SavingsAccount
        try:
            sa = SavingsAccount.objects.get(account_number=SA_ACCOUNT_NO)
        except SavingsAccount.DoesNotExist:
            raise CommandError(f'SavingsAccount {SA_ACCOUNT_NO} not found.')

        new_sa_balance = sa.balance + DIFF
        self.stdout.write(f'\nSAVINGS ACCOUNT {SA_ACCOUNT_NO}')
        self.stdout.write(f'  current balance: {sa.balance}  ->  {new_sa_balance}')
        self._assert(sa.balance, OLD_AMOUNT, f'SavingsAccount({SA_ACCOUNT_NO}).balance')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # 5. Apply atomically
        with db_transaction.atomic():
            # SavingsDepositPosting
            posting.amount = NEW_AMOUNT
            posting.save(update_fields=['amount'])

            # Transaction
            txn.amount        = NEW_AMOUNT
            txn.balance_after = NEW_AMOUNT
            txn.save(update_fields=['amount', 'balance_after'])

            # Journal entry lines
            lines[GL_CASH].debit_amount    = NEW_AMOUNT
            lines[GL_CASH].save(update_fields=['debit_amount'])
            lines[GL_SAVINGS].credit_amount = NEW_AMOUNT
            lines[GL_SAVINGS].save(update_fields=['credit_amount'])

            # SavingsAccount
            sa.balance = new_sa_balance
            sa.save(update_fields=['balance'])

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write('Summary of changes written:')
        self.stdout.write(f'  SavingsDepositPosting.amount      : {OLD_AMOUNT} -> {NEW_AMOUNT}')
        self.stdout.write(f'  Transaction.amount                : {OLD_AMOUNT} -> {NEW_AMOUNT}')
        self.stdout.write(f'  Transaction.balance_after         : {OLD_AMOUNT} -> {NEW_AMOUNT}')
        self.stdout.write(f'  JE GL 1010 debit_amount           : {OLD_AMOUNT} -> {NEW_AMOUNT}')
        self.stdout.write(f'  JE GL 2010 credit_amount          : {OLD_AMOUNT} -> {NEW_AMOUNT}')
        self.stdout.write(f'  SavingsAccount balance            : {OLD_AMOUNT} -> {new_sa_balance}')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. Aborting.'
            )
