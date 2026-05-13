"""
Management command: delete_itohan_deposit
=========================================

Hard-deletes an erroneous N10,500.00 Regular Savings deposit for
Itohan Erhunmwense and zeroes the savings account balance.

Records deleted (in FK order)
------------------------------
  core_journalentryline  35289b71  GL 2010 credit 10,500
  core_journalentryline  3d57afc1  GL 1010 debit  10,500
  core_journalentry      8fe276aa  (JE-20260427-751810)
  core_transaction       3eb3ef6b  (TXN20260428072231565955)

Records updated
---------------
  core_savingsaccount    e36b9b5d  (2603281054124064)
    balance: 10,500 -> 0.00

Records NOT touched
-------------------
  Client 418dcdb5 (Itohan Erhunmwense) and all her other records.

Usage
-----
  python manage.py delete_itohan_deposit --dry-run
  python manage.py delete_itohan_deposit --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction as db_transaction


TXN_ID = '3eb3ef6b-ff73-47d4-b8ba-d87f55185f81'
JE_ID  = '8fe276aa-17b2-4618-b73c-ea3aa22ff97f'
SA_ID  = 'e36b9b5d-dbf2-4733-a58b-5a4b15d53804'

AMOUNT     = Decimal('10500.00')
OLD_BALANCE = Decimal('10500.00')
NEW_BALANCE = Decimal('0.00')


class Command(BaseCommand):
    help = 'Hard-delete Itohan Erhunmwense erroneous N10,500 savings deposit'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import Transaction, JournalEntry, SavingsAccount

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== delete_itohan_deposit [{mode}] ===\n'))

        # 1. Transaction
        try:
            txn = Transaction.all_objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write('TRANSACTION (will be DELETED)')
        self.stdout.write(f'  id            : {txn.id}')
        self.stdout.write(f'  ref           : {txn.transaction_ref}')
        self.stdout.write(f'  amount        : {txn.amount}')
        self.stdout.write(f'  balance_before: {txn.balance_before}')
        self.stdout.write(f'  balance_after : {txn.balance_after}')
        self._assert(txn.amount, AMOUNT, 'Transaction.amount')
        if str(txn.savings_account_id) != SA_ID:
            raise CommandError(
                f'Transaction savings_account_id {txn.savings_account_id} != {SA_ID}. Aborting.'
            )

        # 2. Journal Entry
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
                f'debit={line.debit_amount}  credit={line.credit_amount}  id={line.id}'
            )
            total_debit  += line.debit_amount
            total_credit += line.credit_amount
        if total_debit != AMOUNT or total_credit != AMOUNT:
            raise CommandError(
                f'JE balance mismatch: debit={total_debit} credit={total_credit}, '
                f'expected {AMOUNT} each. Aborting.'
            )
        self.stdout.write(f'  Balance check: debit {total_debit} == credit {total_credit}  OK')

        # 3. Savings Account
        try:
            sa = SavingsAccount.objects.get(id=SA_ID)
        except SavingsAccount.DoesNotExist:
            raise CommandError(f'SavingsAccount {SA_ID} not found.')

        self.stdout.write(f'\nSAVINGS ACCOUNT (balance will be zeroed)')
        self.stdout.write(f'  id             : {sa.id}')
        self.stdout.write(f'  account_number : {sa.account_number}')
        self.stdout.write(f'  balance        : {sa.balance}  ->  {NEW_BALANCE}')
        self._assert(sa.balance, OLD_BALANCE, f'SavingsAccount.balance')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # 4. Apply atomically
        with db_transaction.atomic():
            with connection.cursor() as cur:
                # Delete JE lines first
                cur.execute(
                    'DELETE FROM core_journalentryline WHERE journal_entry_id = %s', [JE_ID]
                )
                lines_deleted = cur.rowcount
                self.stdout.write(f'\nDeleted {lines_deleted} journal line(s).')

                # Delete JE (references transaction via FK)
                cur.execute('DELETE FROM core_journalentry WHERE id = %s', [JE_ID])
                self.stdout.write(f'Deleted JE {je.journal_number}.')

                # Delete Transaction
                cur.execute('DELETE FROM core_transaction WHERE id = %s', [TXN_ID])
                self.stdout.write(f'Deleted Transaction {txn.transaction_ref}.')

            # Zero the savings account balance via ORM
            sa.balance = NEW_BALANCE
            sa.save(update_fields=['balance'])
            self.stdout.write(f'SavingsAccount {sa.account_number} balance set to {NEW_BALANCE}.')

            # Verify everything is gone
            with connection.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM core_transaction WHERE id = %s', [TXN_ID])
                if cur.fetchone()[0] != 0:
                    raise CommandError('Transaction still present after delete. Rolling back.')
                cur.execute('SELECT COUNT(*) FROM core_journalentry WHERE id = %s', [JE_ID])
                if cur.fetchone()[0] != 0:
                    raise CommandError('JournalEntry still present after delete. Rolling back.')

        self.stdout.write(self.style.SUCCESS('\nHard deletion complete.\n'))
        self.stdout.write('Summary:')
        self.stdout.write(f'  JE lines (2)                            - DELETED')
        self.stdout.write(f'  JournalEntry {JE_ID} ({je.journal_number}) - DELETED')
        self.stdout.write(f'  Transaction  {TXN_ID}       - DELETED')
        self.stdout.write(f'  SavingsAccount {sa.account_number} balance: {OLD_BALANCE} -> {NEW_BALANCE}')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. Aborting.'
            )
