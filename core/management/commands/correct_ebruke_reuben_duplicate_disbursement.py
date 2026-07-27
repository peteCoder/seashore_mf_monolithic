"""
Management command: correct_ebruke_reuben_duplicate_disbursement
==================================================================

Corrects a duplicate loan disbursement for Ebruke Reuben (Upper Ekenhuan
branch), loan LN20260724072928260425.

The "Disburse" action was submitted twice within ~3 seconds on
2026-07-26 (11:19:22 and 11:19:25) — Loan.disburse() only guards against
re-disbursement by checking the in-memory loan status, with no
database-level lock, so both near-simultaneous requests read the loan as
still 'approved' and each independently created a full disbursement
Transaction + journal entry. The loan's own amount_disbursed/
outstanding_balance are unaffected (disburse() assigns rather than
accumulates these), but Cash In Hand and Loan Receivable were each
posted twice — ₦400,000 total instead of ₦200,000 — which is why the
branch's Cash In Hand showed a negative balance around the 23rd.

Affected records
----------------
  Loan               : LN20260724072928260425
  Duplicate Transaction: 861359d1-4fb3-486c-addd-61dc582c8270 (the SECOND
                         of the two identical loan_disbursement transactions)
  Duplicate JournalEntry: 4ea15b0e-125c-4318-b5e7-b853e4383ed0 (JE-20260723-840767)

This command marks the SECOND (duplicate) journal entry as reversed —
which is all that's needed, since every account balance calculation in
this system (ChartOfAccounts.get_balance(), trial balance, GL reports)
sums only status='posted' journal lines — and marks the duplicate
Transaction as reversed too, for consistency in the transaction ledger.
Nothing is deleted; both stay visible with an audit note.

Usage
-----
  # Preview — no DB writes:
  python manage.py correct_ebruke_reuben_duplicate_disbursement --dry-run --user-email you@example.com

  # Apply the correction:
  python manage.py correct_ebruke_reuben_duplicate_disbursement --commit --user-email you@example.com
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_NUMBER      = 'LN20260724072928260425'
TRANSACTION_ID   = '861359d1-4fb3-486c-addd-61dc582c8270'
JOURNAL_ENTRY_ID = '4ea15b0e-125c-4318-b5e7-b853e4383ed0'
EXPECTED_AMOUNT  = Decimal('200000.00')


class Command(BaseCommand):
    help = 'Reverse the duplicate loan disbursement for Ebruke Reuben (LN20260724072928260425)'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true', help='Show what WOULD change, no writes')
        group.add_argument('--commit', action='store_true', help='Apply the correction')
        parser.add_argument(
            '--user-email', required=True,
            help='Email of the user this correction is attributed to (for the audit note)',
        )

    def handle(self, *args, **options):
        from core.models import Transaction, JournalEntry, Loan, User

        dry_run = options['dry_run']
        mode = 'DRY RUN (no changes written)' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(
            f'\n=== correct_ebruke_reuben_duplicate_disbursement  [{mode}] ===\n'
        ))

        try:
            reversed_by = User.objects.get(email=options['user_email'])
        except User.DoesNotExist:
            raise CommandError(f"No user found with email {options['user_email']!r}.")

        try:
            loan = Loan.objects.get(loan_number=LOAN_NUMBER)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_NUMBER} not found.')

        try:
            txn = Transaction.objects.get(id=TRANSACTION_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TRANSACTION_ID} not found.')

        try:
            je = JournalEntry.objects.get(id=JOURNAL_ENTRY_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JOURNAL_ENTRY_ID} not found.')

        # ── Safety checks — abort rather than guess if anything looks different ──
        self._assert(txn.loan_id, loan.id, 'Transaction.loan')
        self._assert(txn.transaction_type, 'loan_disbursement', 'Transaction.transaction_type')
        self._assert(txn.amount, EXPECTED_AMOUNT, 'Transaction.amount')
        self._assert(txn.status, 'completed', 'Transaction.status')
        self._assert(je.transaction_id, txn.id, 'JournalEntry.transaction')
        self._assert(je.entry_type, 'loan_disbursement', 'JournalEntry.entry_type')
        self._assert(je.status, 'posted', 'JournalEntry.status')

        # Exactly 2 loan_disbursement transactions should exist for this loan
        disbursement_count = Transaction.objects.filter(
            loan=loan, transaction_type='loan_disbursement',
        ).count()
        if disbursement_count != 2:
            raise CommandError(
                f'Expected exactly 2 loan_disbursement transactions for {LOAN_NUMBER}, '
                f'found {disbursement_count}. Aborting — investigate before proceeding.'
            )

        self.stdout.write(f'Loan               : {loan.loan_number} — {loan.client.get_full_name()}')
        self.stdout.write(f'  status           : {loan.status}')
        self.stdout.write(f'  amount_disbursed : {loan.amount_disbursed}  (unchanged by this fix)')
        self.stdout.write(f'  outstanding_bal  : {loan.outstanding_balance}  (unchanged by this fix)')
        self.stdout.write(f'\nDuplicate Transaction to reverse : {txn.id}')
        self.stdout.write(f'  amount           : {txn.amount}')
        self.stdout.write(f'  status           : {txn.status}  ->  reversed')
        self.stdout.write(f'\nDuplicate JournalEntry to reverse: {je.journal_number}')
        self.stdout.write(f'  status           : {je.status}  ->  reversed')
        for line in je.lines.select_related('account').all():
            self.stdout.write(
                f'    GL {line.account.gl_code} {line.account.account_name}: '
                f'debit={line.debit_amount} credit={line.credit_amount}'
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        reason = (
            'Duplicate disbursement — the "Disburse" action was submitted twice '
            'within a few seconds, creating two identical Transaction + '
            'JournalEntry postings for the same loan. This entry is the '
            'redundant second posting; the loan itself was only disbursed once.'
        )

        with db_transaction.atomic():
            je.reverse(reversed_by=reversed_by, reason=reason)

            txn.status = 'reversed'
            txn.notes = (
                (txn.notes + '\n' if txn.notes else '') +
                f"Reversed by {reversed_by.get_full_name()}. Reason: {reason}"
            )
            txn.save(update_fields=['status', 'notes', 'updated_at'])

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write(f'  JournalEntry {je.journal_number}: posted -> reversed')
        self.stdout.write(f'  Transaction {txn.id}: completed -> reversed')
        self.stdout.write(
            '  Cash In Hand and Loan Receivable balances now exclude this duplicate '
            'automatically (all balance queries filter on status=\'posted\').'
        )

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: expected {expected!r}, got {actual!r}. '
                f'Aborting — do NOT use --commit until this is resolved.'
            )
