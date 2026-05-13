"""
Management command: correct_jamani_repayment
============================================

Corrects a wrongly entered loan repayment for Jamani Happiness.

Wrong amount : ₦9,833.33  (principal ₦8,333.33 + interest ₦1,500.00)
Correct amount: ₦9,900.00  (principal ₦8,400.00  + interest ₦1,500.00)

Affected records
----------------
  Transaction        : 6ba0af79-3168-4295-bf86-dc903072b21d
  JournalEntry       : a26ab3e0-fa55-4705-abd5-8cea9bce93fd  (JE-20260410-497599)
  LoanRepaymentPosting: derived from the transaction above
  Loan               : derived from the repayment posting above

Usage
-----
  # Preview — no DB writes:
  python manage.py correct_jamani_repayment --dry-run

  # Apply the correction:
  python manage.py correct_jamani_repayment --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


TRANSACTION_ID    = '6ba0af79-3168-4295-bf86-dc903072b21d'
JOURNAL_ENTRY_ID  = 'a26ab3e0-fa55-4705-abd5-8cea9bce93fd'

OLD_TOTAL     = Decimal('9833.33')
NEW_TOTAL     = Decimal('9900.00')
DIFF          = NEW_TOTAL - OLD_TOTAL           # 66.67

OLD_PRINCIPAL = Decimal('8333.33')
NEW_PRINCIPAL = OLD_PRINCIPAL + DIFF            # 8400.00

OLD_INTEREST  = Decimal('1500.00')
NEW_INTEREST  = OLD_INTEREST                    # unchanged

# GL codes to locate the correct lines
GL_CASH        = '1010'
GL_PRINCIPAL   = '1810'
GL_INTEREST    = '4010'


class Command(BaseCommand):
    help = 'Correct Jamani Happiness repayment from ₦9,833.33 to ₦9,900.00'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what WOULD be changed without writing to the database',
        )
        group.add_argument(
            '--commit',
            action='store_true',
            help='Apply the correction to the database',
        )

    def handle(self, *args, **options):
        from core.models import Transaction, JournalEntry, JournalEntryLine, LoanRepaymentPosting

        dry_run = options['dry_run']
        mode    = 'DRY RUN (no changes written)' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== correct_jamani_repayment  [{mode}] ===\n'))

        # ── 1. Fetch Transaction ───────────────────────────────────────────────
        try:
            txn = Transaction.objects.get(id=TRANSACTION_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TRANSACTION_ID} not found.')

        self.stdout.write('TRANSACTION')
        self.stdout.write(f'  id              : {txn.id}')
        self.stdout.write(f'  ref             : {txn.transaction_ref}')
        self.stdout.write(f'  amount          : {txn.amount}  ->  {NEW_TOTAL}')
        self.stdout.write(f'  principal_amount: {txn.principal_amount}  ->  {NEW_PRINCIPAL}')
        self.stdout.write(f'  interest_amount : {txn.interest_amount}  ->  {NEW_INTEREST}')
        self._assert(txn.amount,          OLD_TOTAL,     'Transaction.amount')
        self._assert(txn.principal_amount, OLD_PRINCIPAL, 'Transaction.principal_amount')
        self._assert(txn.interest_amount,  OLD_INTEREST,  'Transaction.interest_amount')

        # ── 2. Fetch LoanRepaymentPosting ─────────────────────────────────────
        postings = LoanRepaymentPosting.objects.filter(loan=txn.loan)
        # Find the posting whose amount matches the wrong figure
        posting = None
        for p in postings:
            if p.amount == OLD_TOTAL:
                posting = p
                break
        if posting is None:
            raise CommandError(
                f'No LoanRepaymentPosting with amount={OLD_TOTAL} found for this loan.'
            )

        self.stdout.write('\nLOAN REPAYMENT POSTING')
        self.stdout.write(f'  id              : {posting.id}')
        self.stdout.write(f'  posting_ref     : {posting.posting_ref}')
        self.stdout.write(f'  amount          : {posting.amount}  ->  {NEW_TOTAL}')
        self.stdout.write(f'  principal_amount: {posting.principal_amount}  ->  {NEW_PRINCIPAL}')
        self.stdout.write(f'  interest_amount : {posting.interest_amount}  ->  {NEW_INTEREST}')

        # ── 3. Fetch Loan ─────────────────────────────────────────────────────
        loan = txn.loan
        if loan is None:
            raise CommandError('Transaction is not linked to a loan.')

        new_amount_paid       = loan.amount_paid + DIFF
        new_outstanding_bal   = loan.outstanding_balance - DIFF

        self.stdout.write('\nLOAN')
        self.stdout.write(f'  id                 : {loan.id}')
        self.stdout.write(f'  loan_number        : {loan.loan_number}')
        self.stdout.write(f'  client             : {loan.client}')
        self.stdout.write(f'  amount_paid        : {loan.amount_paid}  ->  {new_amount_paid}')
        self.stdout.write(f'  outstanding_balance: {loan.outstanding_balance}  ->  {new_outstanding_bal}')

        if new_outstanding_bal < Decimal('0.00'):
            raise CommandError(
                f'Correction would make outstanding_balance negative ({new_outstanding_bal}). Aborting.'
            )

        # ── 4. Fetch JournalEntry ─────────────────────────────────────────────
        try:
            je = JournalEntry.objects.get(id=JOURNAL_ENTRY_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JOURNAL_ENTRY_ID} not found.')

        self.stdout.write('\nJOURNAL ENTRY')
        self.stdout.write(f'  id            : {je.id}')
        self.stdout.write(f'  journal_number: {je.journal_number}')
        self.stdout.write(f'  status        : {je.status}')

        # ── 5. Fetch JournalEntryLines ─────────────────────────────────────────
        lines = {line.account.gl_code: line for line in je.lines.select_related('account')}

        for code, expected_old, expected_new, side in [
            (GL_CASH,     OLD_TOTAL,     NEW_TOTAL,     'debit'),
            (GL_PRINCIPAL, OLD_PRINCIPAL, NEW_PRINCIPAL, 'credit'),
            (GL_INTEREST,  OLD_INTEREST,  OLD_INTEREST,  'credit'),
        ]:
            if code not in lines:
                raise CommandError(f'JournalEntryLine for GL {code} not found.')
            line = lines[code]
            amount_field = f'{side}_amount'
            current_val  = getattr(line, amount_field)
            self.stdout.write(
                f'\nJOURNAL LINE  GL {code} ({line.account.account_name})'
            )
            self.stdout.write(f'  {amount_field}: {current_val}  ->  {expected_new}')
            self._assert(current_val, expected_old, f'GL {code} {amount_field}')

        # ── 6. Verify double-entry balance after correction ───────────────────
        total_debit_after  = NEW_TOTAL
        total_credit_after = NEW_PRINCIPAL + NEW_INTEREST
        if total_debit_after != total_credit_after:
            raise CommandError(
                f'Double-entry imbalance after correction: '
                f'debit={total_debit_after} credit={total_credit_after}'
            )
        self.stdout.write(
            f'\nDouble-entry check: debit {total_debit_after} == credit {total_credit_after}  OK'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # ── 7. Apply all changes atomically ───────────────────────────────────
        with db_transaction.atomic():
            # Transaction
            txn.amount           = NEW_TOTAL
            txn.principal_amount = NEW_PRINCIPAL
            txn.interest_amount  = NEW_INTEREST
            txn.save(update_fields=['amount', 'principal_amount', 'interest_amount'])

            # LoanRepaymentPosting
            posting.amount           = NEW_TOTAL
            posting.principal_amount = NEW_PRINCIPAL
            posting.interest_amount  = NEW_INTEREST
            posting.save(update_fields=['amount', 'principal_amount', 'interest_amount'])

            # Loan
            loan.amount_paid       = new_amount_paid
            loan.outstanding_balance = new_outstanding_bal
            loan.save(update_fields=['amount_paid', 'outstanding_balance'])

            # JournalEntryLines
            cash_line = lines[GL_CASH]
            cash_line.debit_amount = NEW_TOTAL
            cash_line.save(update_fields=['debit_amount'])

            principal_line = lines[GL_PRINCIPAL]
            principal_line.credit_amount = NEW_PRINCIPAL
            principal_line.save(update_fields=['credit_amount'])
            # Interest line is unchanged — no save needed

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write('Summary of changes written:')
        self.stdout.write(f'  Transaction.amount           : {OLD_TOTAL} -> {NEW_TOTAL}')
        self.stdout.write(f'  Transaction.principal_amount : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  LoanRepaymentPosting.amount  : {OLD_TOTAL} -> {NEW_TOTAL}')
        self.stdout.write(f'  LoanRepaymentPosting.principal: {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  Loan.amount_paid             : +{DIFF}')
        self.stdout.write(f'  Loan.outstanding_balance     : -{DIFF}')
        self.stdout.write(f'  JE line 1010 debit_amount    : {OLD_TOTAL} -> {NEW_TOTAL}')
        self.stdout.write(f'  JE line 1810 credit_amount   : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  JE line 4010 credit_amount   : {OLD_INTEREST} (unchanged)')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. '
                f'Aborting — do NOT use --commit until this is resolved.'
            )
