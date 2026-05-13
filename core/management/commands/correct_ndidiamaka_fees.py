"""
Management command: correct_ndidiamaka_fees
============================================

Corrects the upfront loan fees for Ndidiamaka Uchechukwu whose fees were
calculated on the wrong principal (N250,000 instead of N500,000).

Fee rates (from Med Loan product):
  risk_premium_rate : 1.50%
  rp_income_rate    : 1.50%
  tech_fee_rate     : 0.50%
  loan_form_fee     : N200.00  (fixed)
  loan_maintenance  : N200.00  (fixed)

                    OLD (250k)   NEW (500k)
  risk_premium_fee :   3,750  ->   7,500
  rp_income_fee    :   3,750  ->   7,500
  tech_fee         :   1,250  ->   2,500
  loan_form_fee    :     200  ->     200  (unchanged)
  loan_maint_fee   :     200  ->     200  (unchanged)
  total_upfront    :   9,150  ->  17,900

Affected records
----------------
  Loan             : f0eb9dc0-1a8e-4d85-84ac-31c04ad48709
  Fees Transaction : 32ea6c33-e444-4924-a1df-a9e88c72ab67  (TXN20260417081643008087)
  Fees JE          : ccae3521-4e46-42d2-96db-91603293ffce  (JE-20260415-870323)
    Line 4160 (tech fee)         : credit 1,250 -> 2,500
    Line 4150 (risk premium)     : credit 3,750 -> 7,500
    Line 4150 (rp income)        : credit 3,750 -> 7,500
    Line 1010 (cash)             : debit  9,150 -> 17,900
    Line 4120 (app fee)          : 200   unchanged
    Line 4165 (maintenance fee)  : 200   unchanged

Usage
-----
  # Preview - no DB writes:
  python manage.py correct_ndidiamaka_fees --dry-run

  # Apply the correction:
  python manage.py correct_ndidiamaka_fees --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID     = 'f0eb9dc0-1a8e-4d85-84ac-31c04ad48709'
TXN_ID      = '32ea6c33-e444-4924-a1df-a9e88c72ab67'
JE_ID       = 'ccae3521-4e46-42d2-96db-91603293ffce'

# Journal line IDs (identified by dry-run inspection)
LINE_4160_ID = '0d3c3e7d-aafe-4cd9-864b-024da8fa60d4'  # tech fee credit
LINE_4150A_ID = 'c19c43e8-cbf3-4906-b24b-74ca4f857433'  # risk_premium credit
LINE_4150B_ID = 'c9064dd7-4ae4-4765-a924-d56ba4f1c3a0'  # rp_income credit
LINE_1010_ID  = 'de9b9ec2-9861-4cac-8e81-008586cb7731'  # cash debit
# These two are unchanged (200 each) - kept for balance verification
LINE_4120_ID  = 'b0b8f190-0fbb-42d3-ba6e-fba81b66b2fe'  # loan app fee credit
LINE_4165_ID  = '9f1102ad-f1b0-4f44-9412-3765db1977e1'  # maintenance fee credit

# Old values
OLD_RISK_PREMIUM  = Decimal('3750.00')
OLD_RP_INCOME     = Decimal('3750.00')
OLD_TECH_FEE      = Decimal('1250.00')
OLD_TOTAL         = Decimal('9150.00')
FIXED_FEE         = Decimal('200.00')   # form + maintenance (unchanged)

# New values
NEW_RISK_PREMIUM  = Decimal('7500.00')
NEW_RP_INCOME     = Decimal('7500.00')
NEW_TECH_FEE      = Decimal('2500.00')
NEW_TOTAL         = Decimal('17900.00')

DIFF = NEW_TOTAL - OLD_TOTAL   # 8,750.00


class Command(BaseCommand):
    help = 'Correct Ndidiamaka upfront fees from N9,150 to N17,900 (500k principal basis)'

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
        self.stdout.write(self.style.WARNING(f'\n=== correct_ndidiamaka_fees  [{mode}] ===\n'))

        # ── Pre-flight: verify new totals balance ──────────────────────────────
        credits_check = NEW_RISK_PREMIUM + NEW_RP_INCOME + NEW_TECH_FEE + FIXED_FEE + FIXED_FEE
        if credits_check != NEW_TOTAL:
            raise CommandError(
                f'Internal balance error: credits {credits_check} != {NEW_TOTAL}. Aborting.'
            )
        self.stdout.write(f'Balance check: {NEW_RISK_PREMIUM} + {NEW_RP_INCOME} + {NEW_TECH_FEE} '
                          f'+ {FIXED_FEE} + {FIXED_FEE} = {credits_check} == {NEW_TOTAL} OK')

        # ── 1. Loan fee fields ─────────────────────────────────────────────────
        try:
            loan = Loan.objects.get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        self.stdout.write('\nLOAN FEE FIELDS')
        self.stdout.write(f'  id                 : {loan.id}')
        self.stdout.write(f'  loan_number        : {loan.loan_number}')
        self.stdout.write(f'  risk_premium_fee   : {loan.risk_premium_fee}  ->  {NEW_RISK_PREMIUM}')
        self.stdout.write(f'  rp_income_fee      : {loan.rp_income_fee}  ->  {NEW_RP_INCOME}')
        self.stdout.write(f'  tech_fee           : {loan.tech_fee}  ->  {NEW_TECH_FEE}')
        self.stdout.write(f'  loan_form_fee      : {loan.loan_form_fee}  (unchanged)')
        self.stdout.write(f'  loan_maintenance_fee: {loan.loan_maintenance_fee}  (unchanged)')
        self.stdout.write(f'  total_upfront_fees : {loan.total_upfront_fees}  ->  {NEW_TOTAL}')

        self._assert(loan.risk_premium_fee,  OLD_RISK_PREMIUM, 'Loan.risk_premium_fee')
        self._assert(loan.rp_income_fee,     OLD_RP_INCOME,    'Loan.rp_income_fee')
        self._assert(loan.tech_fee,          OLD_TECH_FEE,     'Loan.tech_fee')
        self._assert(loan.total_upfront_fees, OLD_TOTAL,       'Loan.total_upfront_fees')
        self._assert(loan.loan_form_fee,     FIXED_FEE,        'Loan.loan_form_fee')
        self._assert(loan.loan_maintenance_fee, FIXED_FEE,     'Loan.loan_maintenance_fee')

        # ── 2. Fees Transaction ────────────────────────────────────────────────
        try:
            txn = Transaction.objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write('\nFEES TRANSACTION')
        self.stdout.write(f'  id     : {txn.id}')
        self.stdout.write(f'  ref    : {txn.transaction_ref}')
        self.stdout.write(f'  type   : {txn.transaction_type}')
        self.stdout.write(f'  amount : {txn.amount}  ->  {NEW_TOTAL}')
        self._assert(txn.amount, OLD_TOTAL, 'Transaction.amount')

        # ── 3. Fees Journal Entry ──────────────────────────────────────────────
        try:
            je = JournalEntry.objects.get(id=JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JE_ID} not found.')

        self.stdout.write('\nFEES JOURNAL ENTRY')
        self.stdout.write(f'  id            : {je.id}')
        self.stdout.write(f'  journal_number: {je.journal_number}')
        self.stdout.write(f'  status        : {je.status}')

        # Fetch all lines by ID for precision
        all_lines = {str(line.id): line for line in je.lines.select_related('account')}

        def get_line(line_id, label):
            if line_id not in all_lines:
                raise CommandError(f'JournalEntryLine {line_id} ({label}) not found.')
            return all_lines[line_id]

        line_4160 = get_line(LINE_4160_ID,  'GL 4160 tech fee')
        line_4150a = get_line(LINE_4150A_ID, 'GL 4150 risk premium')
        line_4150b = get_line(LINE_4150B_ID, 'GL 4150 rp income')
        line_1010  = get_line(LINE_1010_ID,  'GL 1010 cash')
        line_4120  = get_line(LINE_4120_ID,  'GL 4120 app fee')
        line_4165  = get_line(LINE_4165_ID,  'GL 4165 maintenance')

        # Verify current values
        self._assert(line_4160.credit_amount,  OLD_TECH_FEE,     'GL 4160 credit_amount')
        self._assert(line_4150a.credit_amount, OLD_RISK_PREMIUM,  'GL 4150a credit_amount')
        self._assert(line_4150b.credit_amount, OLD_RP_INCOME,     'GL 4150b credit_amount')
        self._assert(line_1010.debit_amount,   OLD_TOTAL,         'GL 1010 debit_amount')
        self._assert(line_4120.credit_amount,  FIXED_FEE,         'GL 4120 credit_amount')
        self._assert(line_4165.credit_amount,  FIXED_FEE,         'GL 4165 credit_amount')

        self.stdout.write(f'\n  GL 4160 ({line_4160.account.account_name}) credit: {line_4160.credit_amount}  ->  {NEW_TECH_FEE}')
        self.stdout.write(f'  GL 4150 ({line_4150a.account.account_name}) credit: {line_4150a.credit_amount}  ->  {NEW_RISK_PREMIUM}  [risk premium]')
        self.stdout.write(f'  GL 4150 ({line_4150b.account.account_name}) credit: {line_4150b.credit_amount}  ->  {NEW_RP_INCOME}  [rp income]')
        self.stdout.write(f'  GL 1010 ({line_1010.account.account_name}) debit : {line_1010.debit_amount}  ->  {NEW_TOTAL}')
        self.stdout.write(f'  GL 4120 ({line_4120.account.account_name}) credit: {line_4120.credit_amount}  (unchanged)')
        self.stdout.write(f'  GL 4165 ({line_4165.account.account_name}) credit: {line_4165.credit_amount}  (unchanged)')

        # Verify double-entry balance after correction
        new_total_credits = (NEW_TECH_FEE + NEW_RISK_PREMIUM + NEW_RP_INCOME
                             + line_4120.credit_amount + line_4165.credit_amount)
        new_total_debits  = NEW_TOTAL
        if new_total_credits != new_total_debits:
            raise CommandError(
                f'Double-entry imbalance: debits={new_total_debits}  credits={new_total_credits}'
            )
        self.stdout.write(f'\n  Double-entry check: debits {new_total_debits} == credits {new_total_credits}  OK')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # ── 4. Apply all changes atomically ───────────────────────────────────
        with db_transaction.atomic():

            # Loan fee fields
            loan.risk_premium_fee   = NEW_RISK_PREMIUM
            loan.rp_income_fee      = NEW_RP_INCOME
            loan.tech_fee           = NEW_TECH_FEE
            loan.total_upfront_fees = NEW_TOTAL
            loan.save(update_fields=[
                'risk_premium_fee', 'rp_income_fee', 'tech_fee', 'total_upfront_fees'
            ])

            # Fees transaction
            txn.amount = NEW_TOTAL
            txn.save(update_fields=['amount'])

            # Journal entry lines
            line_4160.credit_amount  = NEW_TECH_FEE
            line_4160.save(update_fields=['credit_amount'])

            line_4150a.credit_amount = NEW_RISK_PREMIUM
            line_4150a.save(update_fields=['credit_amount'])

            line_4150b.credit_amount = NEW_RP_INCOME
            line_4150b.save(update_fields=['credit_amount'])

            line_1010.debit_amount   = NEW_TOTAL
            line_1010.save(update_fields=['debit_amount'])

            # Lines 4120 and 4165 are unchanged — no save needed

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write('Summary of changes written:')
        self.stdout.write(f'  Loan.risk_premium_fee   : {OLD_RISK_PREMIUM} -> {NEW_RISK_PREMIUM}')
        self.stdout.write(f'  Loan.rp_income_fee      : {OLD_RP_INCOME} -> {NEW_RP_INCOME}')
        self.stdout.write(f'  Loan.tech_fee           : {OLD_TECH_FEE} -> {NEW_TECH_FEE}')
        self.stdout.write(f'  Loan.total_upfront_fees : {OLD_TOTAL} -> {NEW_TOTAL}')
        self.stdout.write(f'  Transaction.amount      : {OLD_TOTAL} -> {NEW_TOTAL}')
        self.stdout.write(f'  JE GL 4160 credit       : {OLD_TECH_FEE} -> {NEW_TECH_FEE}')
        self.stdout.write(f'  JE GL 4150a credit      : {OLD_RISK_PREMIUM} -> {NEW_RISK_PREMIUM}')
        self.stdout.write(f'  JE GL 4150b credit      : {OLD_RP_INCOME} -> {NEW_RP_INCOME}')
        self.stdout.write(f'  JE GL 1010 debit        : {OLD_TOTAL} -> {NEW_TOTAL}')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. '
                f'Aborting - do NOT use --commit until this is resolved.'
            )
