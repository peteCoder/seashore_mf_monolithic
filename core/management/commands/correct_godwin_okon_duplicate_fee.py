"""
Management command: correct_godwin_okon_duplicate_fee
=======================================================

Removes a duplicate 'charges_at_disbursement' (upfront fees) Transaction
and its Journal Entry for Godwin Okon's loan LN20260903144908193611.

Root cause: loan_pay_fees() (core/views/loan_views.py) fetches the Loan
once per request and only checks the in-memory `fees_paid` flag before
calling Loan.pay_fees() — it never re-checks under a row lock. A double
form submission (double-click) on the "Pay Fees" button let two requests
both read fees_paid=False and each create their own Transaction + posted
JournalEntry, 2 seconds apart. Confirmed this is an isolated incident —
no other loan in the system has more than one charges_at_disbursement
transaction.

Both duplicate journal entries are individually balanced (debits ==
credits == 8,150.00 each), so hard-deleting one duplicate pair in full
(Transaction + JournalEntry + its JournalEntryLines) leaves every account
still in balance — there is nothing else to adjust:
  - Loan.total_upfront_fees was never doubled (it's a fixed fee-schedule
    field, unrelated to how many payment transactions exist for it).
  - Loan.fees_transaction already points at the transaction we're KEEPING
    (352762bf...), so the Loan record itself needs no changes.
  - Upfront fees only touch Cash (1010) and fee-income accounts — never
    Loan Receivable / outstanding_balance — so loan.outstanding_balance is
    unaffected either way.

Affected records
-----------------
  Client            : Godwin Okon (4954171d-3322-4d0e-abbe-5e7649c0c0ab)
  Loan              : LN20260903144908193611 (bc3976ff-eb5f-4a68-84ba-883df51d1be4)

  KEEP  Transaction : 352762bf-00d5-419f-82f9-144aef73adb0 (TXN20260904092630561648)
        JournalEntry: afaafc0e-184a-4440-a5dd-fdd26b349bc0 (JE-20260903-234815)
        — this is the one Loan.fees_transaction already points to.

  DELETE Transaction: b8b9d041-183f-4162-840d-88cb9a8065ef (TXN20260904092628582628)
         JournalEntry: 176d1e36-a975-4b0f-91bd-4ae2bbfd686a (JE-20260903-022063)
         (+ its 7 JournalEntryLine rows, cascade-deleted with the entry)

Uses hard_delete() (bypasses BaseModel's default soft-delete) so the
duplicate cannot resurface in any report that queries all_objects.

Usage
-----
  # Preview - no DB writes:
  python manage.py correct_godwin_okon_duplicate_fee --dry-run

  # Apply the correction:
  python manage.py correct_godwin_okon_duplicate_fee --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


CLIENT_ID = '4954171d-3322-4d0e-abbe-5e7649c0c0ab'
LOAN_ID   = 'bc3976ff-eb5f-4a68-84ba-883df51d1be4'

KEEP_TXN_ID = '352762bf-00d5-419f-82f9-144aef73adb0'
KEEP_JE_ID  = 'afaafc0e-184a-4440-a5dd-fdd26b349bc0'

DELETE_TXN_ID = 'b8b9d041-183f-4162-840d-88cb9a8065ef'
DELETE_JE_ID  = '176d1e36-a975-4b0f-91bd-4ae2bbfd686a'

EXPECTED_AMOUNT = Decimal('8150.00')


class Command(BaseCommand):
    help = "Remove Godwin Okon's duplicate upfront-fees transaction and journal entry"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                           help='Show what WOULD be changed without writing to the database')
        group.add_argument('--commit', action='store_true',
                           help='Apply the correction to the database')

    def handle(self, *args, **options):
        from core.models import Loan, Transaction, JournalEntry, JournalEntryLine

        dry_run = options['dry_run']
        mode = 'DRY RUN (no changes written)' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== correct_godwin_okon_duplicate_fee  [{mode}] ===\n'))

        # ── 1. Loan ──────────────────────────────────────────────────────────
        try:
            loan = Loan.objects.select_related('client').get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        if str(loan.client_id) != CLIENT_ID:
            raise CommandError(
                f'Loan {LOAN_ID} belongs to client {loan.client_id}, expected {CLIENT_ID}. Aborting.'
            )

        self.stdout.write(f'Loan               : {loan.loan_number} ({loan.id})')
        self.stdout.write(f'Client             : {loan.client.get_full_name()}')
        self.stdout.write(f'Loan.fees_paid     : {loan.fees_paid}')
        self.stdout.write(f'Loan.fees_transaction_id: {loan.fees_transaction_id}')

        self._assert(loan.fees_paid, True, 'Loan.fees_paid')
        self._assert(str(loan.fees_transaction_id), KEEP_TXN_ID, 'Loan.fees_transaction_id')

        # ── 2. Transaction to KEEP ──────────────────────────────────────────────
        try:
            keep_txn = Transaction.objects.get(id=KEEP_TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction to KEEP ({KEEP_TXN_ID}) not found.')
        self._assert(keep_txn.amount, EXPECTED_AMOUNT, 'KEEP Transaction.amount')
        self._assert(keep_txn.transaction_type, 'charges_at_disbursement', 'KEEP Transaction.transaction_type')
        self._assert(str(keep_txn.loan_id), LOAN_ID, 'KEEP Transaction.loan_id')

        try:
            keep_je = JournalEntry.objects.get(id=KEEP_JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry to KEEP ({KEEP_JE_ID}) not found.')
        self._assert(str(keep_je.transaction_id), KEEP_TXN_ID, 'KEEP JournalEntry.transaction_id')
        self._assert(keep_je.status, 'posted', 'KEEP JournalEntry.status')

        keep_debits  = sum((l.debit_amount for l in keep_je.lines.all()), Decimal('0.00'))
        keep_credits = sum((l.credit_amount for l in keep_je.lines.all()), Decimal('0.00'))
        if keep_debits != keep_credits:
            raise CommandError(
                f'KEEP journal entry {keep_je.journal_number} is already out of balance '
                f'(debits={keep_debits}, credits={keep_credits}) — aborting, this needs manual review.'
            )
        self.stdout.write(
            f'\nKEEPING   Transaction {keep_txn.transaction_ref} / '
            f'JournalEntry {keep_je.journal_number} '
            f'(debits={keep_debits} == credits={keep_credits}, balanced OK)'
        )

        # ── 3. Transaction to DELETE ────────────────────────────────────────────
        try:
            del_txn = Transaction.objects.get(id=DELETE_TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction to DELETE ({DELETE_TXN_ID}) not found.')
        self._assert(del_txn.amount, EXPECTED_AMOUNT, 'DELETE Transaction.amount')
        self._assert(del_txn.transaction_type, 'charges_at_disbursement', 'DELETE Transaction.transaction_type')
        self._assert(str(del_txn.loan_id), LOAN_ID, 'DELETE Transaction.loan_id')

        try:
            del_je = JournalEntry.objects.get(id=DELETE_JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry to DELETE ({DELETE_JE_ID}) not found.')
        self._assert(str(del_je.transaction_id), DELETE_TXN_ID, 'DELETE JournalEntry.transaction_id')
        self._assert(del_je.status, 'posted', 'DELETE JournalEntry.status')

        del_lines = list(del_je.lines.select_related('account').all())
        del_debits  = sum((l.debit_amount for l in del_lines), Decimal('0.00'))
        del_credits = sum((l.credit_amount for l in del_lines), Decimal('0.00'))
        if del_debits != del_credits:
            raise CommandError(
                f'DELETE journal entry {del_je.journal_number} is already out of balance '
                f'(debits={del_debits}, credits={del_credits}) — aborting, this needs manual review.'
            )
        self.stdout.write(
            f'DELETING  Transaction {del_txn.transaction_ref} / '
            f'JournalEntry {del_je.journal_number} '
            f'(debits={del_debits} == credits={del_credits}, balanced OK — removing it keeps the books balanced)'
        )
        self.stdout.write(f'\n  {len(del_lines)} journal lines to be removed (cascade with the entry):')
        for l in del_lines:
            side = f'debit {l.debit_amount}' if l.debit_amount else f'credit {l.credit_amount}'
            self.stdout.write(f'    GL {l.account.gl_code} {l.account.account_name}: {side}')

        # Safety: the two must not be the same row, and the survivor must
        # genuinely be the one referenced by the loan (already asserted above).
        if DELETE_TXN_ID == KEEP_TXN_ID:
            raise CommandError('KEEP and DELETE transaction IDs are identical — aborting.')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # ── 4. Apply — hard delete the duplicate, keep everything else ─────────
        with db_transaction.atomic():
            je_number = del_je.journal_number
            txn_ref = del_txn.transaction_ref

            del_je.hard_delete()      # cascades to its JournalEntryLine rows
            del_txn.hard_delete()

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write('Summary of changes written:')
        self.stdout.write(f'  Deleted Transaction   : {txn_ref} ({DELETE_TXN_ID})')
        self.stdout.write(f'  Deleted JournalEntry  : {je_number} ({DELETE_JE_ID}) and its {len(del_lines)} lines')
        self.stdout.write(f'  Kept Transaction      : {keep_txn.transaction_ref} ({KEEP_TXN_ID})')
        self.stdout.write(f'  Kept JournalEntry     : {keep_je.journal_number} ({KEEP_JE_ID})')
        self.stdout.write(f'  Loan.fees_transaction : unchanged, already points at the kept transaction')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected!r}, got {actual!r}. '
                f'Aborting - do NOT use --commit until this is resolved.'
            )
