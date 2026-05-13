"""
Management command: correct_osaro_loan
======================================

Corrects Osaro Lilian's loan principal from N200,000 to N250,000.
The loan is still Pending Approval (no disbursement, no schedule rows).
Only the fees transaction and its journal have been posted.

Loan : 048a7a98-6345-4ba2-a2f1-265ef7823661  (LN20260422152704345228)

LOAN FIELDS
                      OLD (200k)     NEW (250k)
  principal_amount :   200,000    ->   250,000
  total_interest   :    36,000    ->    45,000   (250k x 3% x 6 months)
  total_repayment  :   236,000    ->   295,000
  installment_amt  :  9,833.33   ->  12,291.67  (295k / 24)
  risk_premium_fee :     3,000   ->     3,750   (250k x 1.5%)
  rp_income_fee    :     3,000   ->     3,750   (250k x 1.5%)
  tech_fee         :     1,000   ->     1,250   (250k x 0.5%)
  loan_form_fee    :       200   ->       200   (fixed, unchanged)
  loan_maint_fee   :       200   ->       200   (fixed, unchanged)
  total_upfront    :     7,400   ->     9,150

FEES TRANSACTION : 6e51ddd5-a8ae-41ed-88e8-01285a573daf  (TXN20260422153225681312)
  amount        : 7,400 -> 9,150
  balance_after : 7,400 -> 9,150

FEES JE : 5a7b16b3-af14-469c-8994-dfa6a7bf3ab9  (JE-20260422-615483)
  GL 1010 (Cash)         debit  : 7,400 -> 9,150
  GL 4150 (risk premium) credit : 3,000 -> 3,750   [line ad4a429e]
  GL 4150 (rp income)    credit : 3,000 -> 3,750   [line 7dcfddbb]
  GL 4160 (tech fee)     credit : 1,000 -> 1,250   [line 4093b3d5]
  GL 4120 (app fee)      credit :   200 ->   200   (unchanged)
  GL 4165 (maint fee)    credit :   200 ->   200   (unchanged)

Usage
-----
  python manage.py correct_osaro_loan --dry-run
  python manage.py correct_osaro_loan --commit
"""

from decimal import Decimal, ROUND_HALF_UP
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID  = '048a7a98-6345-4ba2-a2f1-265ef7823661'
TXN_ID   = '6e51ddd5-a8ae-41ed-88e8-01285a573daf'
JE_ID    = '5a7b16b3-af14-469c-8994-dfa6a7bf3ab9'

# JE line IDs
LINE_1010_ID  = 'c70eb5cd-3880-486a-9f46-49ed35a8cda5'   # cash debit
LINE_4150A_ID = 'ad4a429e-ee46-408f-8045-3f1fee6be99f'   # risk premium credit
LINE_4150B_ID = '7dcfddbb-a47d-4af6-a4e5-f8ac4b26b32a'   # rp income credit
LINE_4160_ID  = '4093b3d5-b79d-4ead-978f-e9b785d183f9'   # tech fee credit
LINE_4120_ID  = 'ddcbd404-36b5-4a44-96da-c034f5fa0f0c'   # app fee (unchanged)
LINE_4165_ID  = 'bff926ee-73fe-490b-95a0-bb602e9a1400'   # maint fee (unchanged)

# Old values (200k basis)
OLD_PRINCIPAL     = Decimal('200000.00')
OLD_INTEREST      = Decimal('36000.00')
OLD_REPAYMENT     = Decimal('236000.00')
OLD_INSTALLMENT   = Decimal('9833.33')
OLD_RISK_PREMIUM  = Decimal('3000.00')
OLD_RP_INCOME     = Decimal('3000.00')
OLD_TECH_FEE      = Decimal('1000.00')
FIXED_FEE         = Decimal('200.00')
OLD_TOTAL_FEES    = Decimal('7400.00')

# New values (250k basis)
NEW_PRINCIPAL     = Decimal('250000.00')
RATE              = Decimal('0.03')
MONTHS            = 6
NEW_INTEREST      = NEW_PRINCIPAL * RATE * MONTHS          # 45,000.00
NEW_REPAYMENT     = NEW_PRINCIPAL + NEW_INTEREST           # 295,000.00
N                 = 24
NEW_INSTALLMENT   = (NEW_REPAYMENT / N).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)  # 12,291.67
NEW_RISK_PREMIUM  = Decimal('3750.00')
NEW_RP_INCOME     = Decimal('3750.00')
NEW_TECH_FEE      = Decimal('1250.00')
NEW_TOTAL_FEES    = NEW_RISK_PREMIUM + NEW_RP_INCOME + NEW_TECH_FEE + FIXED_FEE + FIXED_FEE  # 9,150.00


class Command(BaseCommand):
    help = 'Correct Osaro Lilian loan principal from N200,000 to N250,000'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import Loan, Transaction, JournalEntry, JournalEntryLine

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== correct_osaro_loan [{mode}] ===\n'))

        # Pre-flight: verify computed values
        assert NEW_INTEREST   == Decimal('45000.00'),  f'Interest error: {NEW_INTEREST}'
        assert NEW_REPAYMENT  == Decimal('295000.00'), f'Repayment error: {NEW_REPAYMENT}'
        assert NEW_INSTALLMENT == Decimal('12291.67'), f'Installment error: {NEW_INSTALLMENT}'
        assert NEW_TOTAL_FEES == Decimal('9150.00'),   f'Total fees error: {NEW_TOTAL_FEES}'

        bal_check = NEW_RISK_PREMIUM + NEW_RP_INCOME + NEW_TECH_FEE + FIXED_FEE + FIXED_FEE
        if bal_check != NEW_TOTAL_FEES:
            raise CommandError(f'Fee balance error: {bal_check} != {NEW_TOTAL_FEES}')

        self.stdout.write('COMPUTED NEW VALUES (verified):')
        self.stdout.write(f'  new_interest   : {NEW_INTEREST}')
        self.stdout.write(f'  new_repayment  : {NEW_REPAYMENT}')
        self.stdout.write(f'  new_installment: {NEW_INSTALLMENT}')
        self.stdout.write(f'  new_total_fees : {NEW_TOTAL_FEES}  (balance check OK)')

        # 1. Loan
        try:
            loan = Loan.objects.get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        self.stdout.write('\nLOAN')
        self.stdout.write(f'  id               : {loan.id}')
        self.stdout.write(f'  loan_number      : {loan.loan_number}')
        self.stdout.write(f'  status           : {loan.status}  (must be pending_approval)')
        self.stdout.write(f'  principal_amount : {loan.principal_amount}  ->  {NEW_PRINCIPAL}')
        self.stdout.write(f'  total_interest   : {loan.total_interest}  ->  {NEW_INTEREST}')
        self.stdout.write(f'  total_repayment  : {loan.total_repayment}  ->  {NEW_REPAYMENT}')
        self.stdout.write(f'  installment_amt  : {loan.installment_amount}  ->  {NEW_INSTALLMENT}')
        self.stdout.write(f'  risk_premium_fee : {loan.risk_premium_fee}  ->  {NEW_RISK_PREMIUM}')
        self.stdout.write(f'  rp_income_fee    : {loan.rp_income_fee}  ->  {NEW_RP_INCOME}')
        self.stdout.write(f'  tech_fee         : {loan.tech_fee}  ->  {NEW_TECH_FEE}')
        self.stdout.write(f'  loan_form_fee    : {loan.loan_form_fee}  (unchanged)')
        self.stdout.write(f'  loan_maint_fee   : {loan.loan_maintenance_fee}  (unchanged)')
        self.stdout.write(f'  total_upfront    : {loan.total_upfront_fees}  ->  {NEW_TOTAL_FEES}')
        self.stdout.write(f'  amount_disbursed : {loan.amount_disbursed}  (must be 0)')
        self.stdout.write(f'  amount_paid      : {loan.amount_paid}  (must be 0)')

        if loan.status != 'pending_approval':
            raise CommandError(
                f'Loan status is {loan.status!r}, expected pending_approval. '
                f'Do NOT use --commit on a disbursed loan without further review.'
            )
        self._assert(loan.principal_amount,    OLD_PRINCIPAL,   'Loan.principal_amount')
        self._assert(loan.total_interest,      OLD_INTEREST,    'Loan.total_interest')
        self._assert(loan.total_repayment,     OLD_REPAYMENT,   'Loan.total_repayment')
        self._assert(loan.installment_amount,  OLD_INSTALLMENT, 'Loan.installment_amount')
        self._assert(loan.risk_premium_fee,    OLD_RISK_PREMIUM,'Loan.risk_premium_fee')
        self._assert(loan.rp_income_fee,       OLD_RP_INCOME,   'Loan.rp_income_fee')
        self._assert(loan.tech_fee,            OLD_TECH_FEE,    'Loan.tech_fee')
        self._assert(loan.total_upfront_fees,  OLD_TOTAL_FEES,  'Loan.total_upfront_fees')
        self._assert(loan.amount_disbursed,    Decimal('0.00'), 'Loan.amount_disbursed')
        self._assert(loan.amount_paid,         Decimal('0.00'), 'Loan.amount_paid')

        # 2. Fees Transaction
        try:
            txn = Transaction.objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write('\nFEES TRANSACTION')
        self.stdout.write(f'  ref           : {txn.transaction_ref}')
        self.stdout.write(f'  amount        : {txn.amount}  ->  {NEW_TOTAL_FEES}')
        self.stdout.write(f'  balance_before: {txn.balance_before}  (unchanged)')
        self.stdout.write(f'  balance_after : {txn.balance_after}  ->  {NEW_TOTAL_FEES}')
        self._assert(txn.amount,        OLD_TOTAL_FEES, 'Transaction.amount')
        self._assert(txn.balance_after, OLD_TOTAL_FEES, 'Transaction.balance_after')

        # 3. Fees Journal Entry
        try:
            je = JournalEntry.objects.get(id=JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JE_ID} not found.')

        self.stdout.write(f'\nFEES JOURNAL ENTRY: {je.journal_number} | status={je.status}')

        all_lines = {str(line.id): line for line in je.lines.select_related('account')}

        def get_line(lid, label):
            if lid not in all_lines:
                raise CommandError(f'JournalEntryLine {lid} ({label}) not found.')
            return all_lines[lid]

        line_1010  = get_line(LINE_1010_ID,  'GL 1010 cash')
        line_4150a = get_line(LINE_4150A_ID, 'GL 4150 risk premium')
        line_4150b = get_line(LINE_4150B_ID, 'GL 4150 rp income')
        line_4160  = get_line(LINE_4160_ID,  'GL 4160 tech fee')
        line_4120  = get_line(LINE_4120_ID,  'GL 4120 app fee')
        line_4165  = get_line(LINE_4165_ID,  'GL 4165 maint fee')

        self._assert(line_1010.debit_amount,   OLD_TOTAL_FEES,   'GL 1010 debit_amount')
        self._assert(line_4150a.credit_amount, OLD_RISK_PREMIUM, 'GL 4150a credit_amount')
        self._assert(line_4150b.credit_amount, OLD_RP_INCOME,    'GL 4150b credit_amount')
        self._assert(line_4160.credit_amount,  OLD_TECH_FEE,     'GL 4160 credit_amount')
        self._assert(line_4120.credit_amount,  FIXED_FEE,        'GL 4120 credit_amount')
        self._assert(line_4165.credit_amount,  FIXED_FEE,        'GL 4165 credit_amount')

        self.stdout.write(f'  GL 1010 ({line_1010.account.account_name}) debit  : {line_1010.debit_amount}  ->  {NEW_TOTAL_FEES}')
        self.stdout.write(f'  GL 4150 ({line_4150a.account.account_name}) credit : {line_4150a.credit_amount}  ->  {NEW_RISK_PREMIUM}  [risk premium]')
        self.stdout.write(f'  GL 4150 ({line_4150b.account.account_name}) credit : {line_4150b.credit_amount}  ->  {NEW_RP_INCOME}  [rp income]')
        self.stdout.write(f'  GL 4160 ({line_4160.account.account_name}) credit : {line_4160.credit_amount}  ->  {NEW_TECH_FEE}')
        self.stdout.write(f'  GL 4120 ({line_4120.account.account_name}) credit : {line_4120.credit_amount}  (unchanged)')
        self.stdout.write(f'  GL 4165 ({line_4165.account.account_name}) credit : {line_4165.credit_amount}  (unchanged)')

        new_credits = NEW_RISK_PREMIUM + NEW_RP_INCOME + NEW_TECH_FEE + line_4120.credit_amount + line_4165.credit_amount
        if new_credits != NEW_TOTAL_FEES:
            raise CommandError(f'Double-entry imbalance: debits={NEW_TOTAL_FEES}  credits={new_credits}')
        self.stdout.write(f'\n  Double-entry check: debits {NEW_TOTAL_FEES} == credits {new_credits}  OK')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # 4. Apply atomically
        with db_transaction.atomic():

            # Loan
            loan.principal_amount   = NEW_PRINCIPAL
            loan.total_interest     = NEW_INTEREST
            loan.total_repayment    = NEW_REPAYMENT
            loan.installment_amount = NEW_INSTALLMENT
            loan.risk_premium_fee   = NEW_RISK_PREMIUM
            loan.rp_income_fee      = NEW_RP_INCOME
            loan.tech_fee           = NEW_TECH_FEE
            loan.total_upfront_fees = NEW_TOTAL_FEES
            loan.save(update_fields=[
                'principal_amount', 'total_interest', 'total_repayment',
                'installment_amount', 'risk_premium_fee', 'rp_income_fee',
                'tech_fee', 'total_upfront_fees',
            ])

            # Transaction
            txn.amount        = NEW_TOTAL_FEES
            txn.balance_after = NEW_TOTAL_FEES
            txn.save(update_fields=['amount', 'balance_after'])

            # JE lines
            line_1010.debit_amount    = NEW_TOTAL_FEES
            line_1010.save(update_fields=['debit_amount'])
            line_4150a.credit_amount  = NEW_RISK_PREMIUM
            line_4150a.save(update_fields=['credit_amount'])
            line_4150b.credit_amount  = NEW_RP_INCOME
            line_4150b.save(update_fields=['credit_amount'])
            line_4160.credit_amount   = NEW_TECH_FEE
            line_4160.save(update_fields=['credit_amount'])
            # line_4120 and line_4165 unchanged

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write('Summary of changes written:')
        self.stdout.write(f'  Loan.principal_amount   : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  Loan.total_interest     : {OLD_INTEREST} -> {NEW_INTEREST}')
        self.stdout.write(f'  Loan.total_repayment    : {OLD_REPAYMENT} -> {NEW_REPAYMENT}')
        self.stdout.write(f'  Loan.installment_amount : {OLD_INSTALLMENT} -> {NEW_INSTALLMENT}')
        self.stdout.write(f'  Loan.risk_premium_fee   : {OLD_RISK_PREMIUM} -> {NEW_RISK_PREMIUM}')
        self.stdout.write(f'  Loan.rp_income_fee      : {OLD_RP_INCOME} -> {NEW_RP_INCOME}')
        self.stdout.write(f'  Loan.tech_fee           : {OLD_TECH_FEE} -> {NEW_TECH_FEE}')
        self.stdout.write(f'  Loan.total_upfront_fees : {OLD_TOTAL_FEES} -> {NEW_TOTAL_FEES}')
        self.stdout.write(f'  Transaction.amount      : {OLD_TOTAL_FEES} -> {NEW_TOTAL_FEES}')
        self.stdout.write(f'  Transaction.balance_after: {OLD_TOTAL_FEES} -> {NEW_TOTAL_FEES}')
        self.stdout.write(f'  JE GL 1010 debit        : {OLD_TOTAL_FEES} -> {NEW_TOTAL_FEES}')
        self.stdout.write(f'  JE GL 4150a credit      : {OLD_RISK_PREMIUM} -> {NEW_RISK_PREMIUM}')
        self.stdout.write(f'  JE GL 4150b credit      : {OLD_RP_INCOME} -> {NEW_RP_INCOME}')
        self.stdout.write(f'  JE GL 4160 credit       : {OLD_TECH_FEE} -> {NEW_TECH_FEE}')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. Aborting.'
            )
