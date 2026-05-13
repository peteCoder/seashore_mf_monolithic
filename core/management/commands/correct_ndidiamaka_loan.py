"""
Management command: correct_ndidiamaka_loan
============================================

Corrects a wrongly entered loan principal for Ndidiamaka Uchechukwu.

Wrong principal : N250,000.00
Correct principal: N500,000.00

What changes
------------
  Loan               : f0eb9dc0-1a8e-4d85-84ac-31c04ad48709
    principal_amount       250,000  ->  500,000
    total_interest          45,000  ->   90,000
    total_repayment        295,000  ->  590,000
    outstanding_balance    295,000  ->  590,000
    amount_disbursed       250,000  ->  500,000
    installment_amount   12,291.67  ->  24,583.33

  Transaction (disbursement) : 7b01bda9-46d6-4bf1-8b46-17713b1d838b
    amount                 250,000  ->  500,000

  JournalEntry (disbursement): 1fc8cab4-8610-4e8f-a1e8-93cdaf48640b  (JE-20260415-366492)
    GL 1810 debit_amount   250,000  ->  500,000
    GL 1010 credit_amount  250,000  ->  500,000

  LoanRepaymentSchedule (24 rows) - dates UNCHANGED, amounts recalculated:
    Rows 1-23: principal=20,833.33  interest=3,750.00  total=24,583.33
    Row   24 : principal=20,833.41  interest=3,750.00  total=24,583.41  (rounding absorber)

What does NOT change
---------------------
  Fees journal JE-20260415-870323 and all fee fields on the loan are untouched.

Usage
-----
  # Preview - no DB writes:
  python manage.py correct_ndidiamaka_loan --dry-run

  # Apply the correction:
  python manage.py correct_ndidiamaka_loan --commit
"""

from decimal import Decimal, ROUND_HALF_UP
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID        = 'f0eb9dc0-1a8e-4d85-84ac-31c04ad48709'
TXN_ID         = '7b01bda9-46d6-4bf1-8b46-17713b1d838b'
JE_ID          = '1fc8cab4-8610-4e8f-a1e8-93cdaf48640b'

OLD_PRINCIPAL  = Decimal('250000.00')
NEW_PRINCIPAL  = Decimal('500000.00')
RATE           = Decimal('0.03')        # 3% per month
MONTHS         = 6
N              = 24                     # installments (unchanged)

OLD_INTEREST   = Decimal('45000.00')
NEW_INTEREST   = NEW_PRINCIPAL * RATE * MONTHS   # 90,000.00

OLD_REPAYMENT  = Decimal('295000.00')
NEW_REPAYMENT  = NEW_PRINCIPAL + NEW_INTEREST    # 590,000.00

OLD_INSTALLMENT = Decimal('12291.67')
NEW_INSTALLMENT = (NEW_REPAYMENT / N).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)  # 24,583.33

# Per-installment split for rows 1-23
NEW_INTEREST_PER = (NEW_INTEREST / N).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)   # 3,750.00
NEW_PRINCIPAL_PER = (NEW_PRINCIPAL / N).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) # 20,833.33
NEW_TOTAL_PER   = NEW_INSTALLMENT  # 24,583.33

# Row 24 absorbs rounding to ensure totals sum perfectly
NEW_TOTAL_LAST     = NEW_REPAYMENT - (NEW_INSTALLMENT * (N - 1))
NEW_PRINCIPAL_LAST = NEW_PRINCIPAL - (NEW_PRINCIPAL_PER * (N - 1))
NEW_INTEREST_LAST  = NEW_INTEREST_PER  # interest stays same

GL_PRINCIPAL = '1810'
GL_CASH      = '1010'


class Command(BaseCommand):
    help = 'Correct Ndidiamaka Uchechukwu loan principal from N250,000 to N500,000'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run',  action='store_true',
                           help='Show what WOULD be changed without writing to the database')
        group.add_argument('--commit',   action='store_true',
                           help='Apply the correction to the database')

    def handle(self, *args, **options):
        from core.models import Loan, Transaction, JournalEntry, LoanRepaymentSchedule

        dry_run = options['dry_run']
        mode = 'DRY RUN (no changes written)' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== correct_ndidiamaka_loan  [{mode}] ===\n'))

        # ── Pre-flight: verify computed values balance ─────────────────────────
        assert NEW_INTEREST   == Decimal('90000.00'), f"Interest calc error: {NEW_INTEREST}"
        assert NEW_REPAYMENT  == Decimal('590000.00'), f"Repayment calc error: {NEW_REPAYMENT}"
        assert NEW_INSTALLMENT == Decimal('24583.33'), f"Installment calc error: {NEW_INSTALLMENT}"
        assert NEW_INTEREST_PER == Decimal('3750.00'), f"Interest/inst error: {NEW_INTEREST_PER}"
        assert NEW_PRINCIPAL_PER == Decimal('20833.33'), f"Principal/inst error: {NEW_PRINCIPAL_PER}"
        # Verify totals reconcile exactly
        total_principal_check = NEW_PRINCIPAL_PER * (N - 1) + NEW_PRINCIPAL_LAST
        total_repayment_check = NEW_TOTAL_PER * (N - 1) + NEW_TOTAL_LAST
        if total_principal_check != NEW_PRINCIPAL:
            raise CommandError(f'Principal sum check failed: {total_principal_check} != {NEW_PRINCIPAL}')
        if total_repayment_check != NEW_REPAYMENT:
            raise CommandError(f'Repayment sum check failed: {total_repayment_check} != {NEW_REPAYMENT}')

        self.stdout.write('COMPUTED NEW VALUES (verified):')
        self.stdout.write(f'  new_interest     : {NEW_INTEREST}')
        self.stdout.write(f'  new_repayment    : {NEW_REPAYMENT}')
        self.stdout.write(f'  new_installment  : {NEW_INSTALLMENT}')
        self.stdout.write(f'  interest/inst    : {NEW_INTEREST_PER}')
        self.stdout.write(f'  principal/inst   : {NEW_PRINCIPAL_PER}')
        self.stdout.write(f'  total/inst       : {NEW_TOTAL_PER}')
        self.stdout.write(f'  last row total   : {NEW_TOTAL_LAST}')
        self.stdout.write(f'  last row principal: {NEW_PRINCIPAL_LAST}')
        self.stdout.write(f'  sum-principal check: {total_principal_check} == {NEW_PRINCIPAL} OK')
        self.stdout.write(f'  sum-repayment check: {total_repayment_check} == {NEW_REPAYMENT} OK')

        # ── 1. Loan ────────────────────────────────────────────────────────────
        try:
            loan = Loan.objects.get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        self.stdout.write('\nLOAN')
        self.stdout.write(f'  id               : {loan.id}')
        self.stdout.write(f'  loan_number      : {loan.loan_number}')
        self.stdout.write(f'  client           : {loan.client}')
        self.stdout.write(f'  principal_amount : {loan.principal_amount}  ->  {NEW_PRINCIPAL}')
        self.stdout.write(f'  total_interest   : {loan.total_interest}  ->  {NEW_INTEREST}')
        self.stdout.write(f'  total_repayment  : {loan.total_repayment}  ->  {NEW_REPAYMENT}')
        self.stdout.write(f'  outstanding_bal  : {loan.outstanding_balance}  ->  {NEW_REPAYMENT}')
        self.stdout.write(f'  amount_disbursed : {loan.amount_disbursed}  ->  {NEW_PRINCIPAL}')
        self.stdout.write(f'  installment_amt  : {loan.installment_amount}  ->  {NEW_INSTALLMENT}')
        self.stdout.write(f'  amount_paid      : {loan.amount_paid}  (must be 0)')

        self._assert(loan.principal_amount,    OLD_PRINCIPAL,  'Loan.principal_amount')
        self._assert(loan.total_interest,      OLD_INTEREST,   'Loan.total_interest')
        self._assert(loan.total_repayment,     OLD_REPAYMENT,  'Loan.total_repayment')
        self._assert(loan.outstanding_balance, OLD_REPAYMENT,  'Loan.outstanding_balance')
        self._assert(loan.amount_disbursed,    OLD_PRINCIPAL,  'Loan.amount_disbursed')
        self._assert(loan.amount_paid,         Decimal('0.00'),'Loan.amount_paid')

        # ── 2. Disbursement Transaction ────────────────────────────────────────
        try:
            txn = Transaction.objects.get(id=TXN_ID)
        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction {TXN_ID} not found.')

        self.stdout.write('\nDISBURSEMENT TRANSACTION')
        self.stdout.write(f'  id     : {txn.id}')
        self.stdout.write(f'  ref    : {txn.transaction_ref}')
        self.stdout.write(f'  amount : {txn.amount}  ->  {NEW_PRINCIPAL}')
        self._assert(txn.amount, OLD_PRINCIPAL, 'Transaction.amount')

        # ── 3. Disbursement Journal Entry ──────────────────────────────────────
        try:
            je = JournalEntry.objects.get(id=JE_ID)
        except JournalEntry.DoesNotExist:
            raise CommandError(f'JournalEntry {JE_ID} not found.')

        self.stdout.write('\nJOURNAL ENTRY (disbursement only)')
        self.stdout.write(f'  id            : {je.id}')
        self.stdout.write(f'  journal_number: {je.journal_number}')
        self.stdout.write(f'  status        : {je.status}')

        lines = {line.account.gl_code: line for line in je.lines.select_related('account')}

        for code, field, old_val in [
            (GL_PRINCIPAL, 'debit_amount',  OLD_PRINCIPAL),
            (GL_CASH,      'credit_amount', OLD_PRINCIPAL),
        ]:
            if code not in lines:
                raise CommandError(f'JournalEntryLine GL {code} not found in {je.journal_number}.')
            line = lines[code]
            current = getattr(line, field)
            self.stdout.write(
                f'  GL {code} ({line.account.account_name}) {field}: {current}  ->  {NEW_PRINCIPAL}'
            )
            self._assert(current, old_val, f'GL {code} {field}')

        # ── 4. LoanRepaymentSchedule rows ─────────────────────────────────────
        schedule_rows = list(
            LoanRepaymentSchedule.objects.filter(loan=loan).order_by('installment_number')
        )
        if len(schedule_rows) != N:
            raise CommandError(
                f'Expected {N} schedule rows, found {len(schedule_rows)}. Aborting.'
            )

        self.stdout.write(f'\nLOAN REPAYMENT SCHEDULE ({N} rows — dates unchanged)')
        self.stdout.write(f'  Rows 1-{N-1}:')
        self.stdout.write(f'    principal  : {schedule_rows[0].principal_amount}  ->  {NEW_PRINCIPAL_PER}')
        self.stdout.write(f'    interest   : {schedule_rows[0].interest_amount}  ->  {NEW_INTEREST_PER}')
        self.stdout.write(f'    total      : {schedule_rows[0].total_amount}  ->  {NEW_TOTAL_PER}')
        self.stdout.write(f'    outstanding: {schedule_rows[0].outstanding_amount}  ->  {NEW_TOTAL_PER}')
        last = schedule_rows[-1]
        self.stdout.write(f'  Row {N} (rounding absorber, due {last.due_date}):')
        self.stdout.write(f'    principal  : {last.principal_amount}  ->  {NEW_PRINCIPAL_LAST}')
        self.stdout.write(f'    interest   : {last.interest_amount}  ->  {NEW_INTEREST_LAST}')
        self.stdout.write(f'    total      : {last.total_amount}  ->  {NEW_TOTAL_LAST}')
        self.stdout.write(f'    outstanding: {last.outstanding_amount}  ->  {NEW_TOTAL_LAST}')

        # All rows must be pending with amount_paid = 0
        for row in schedule_rows:
            if row.amount_paid != Decimal('0.00'):
                raise CommandError(
                    f'Schedule row #{row.installment_number} has amount_paid={row.amount_paid}. '
                    f'Cannot correct a partially repaid loan. Aborting.'
                )
            if row.status != 'pending':
                raise CommandError(
                    f'Schedule row #{row.installment_number} has status={row.status} (expected pending). Aborting.'
                )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # ── 5. Apply all changes atomically ───────────────────────────────────
        with db_transaction.atomic():

            # Loan
            loan.principal_amount    = NEW_PRINCIPAL
            loan.total_interest      = NEW_INTEREST
            loan.total_repayment     = NEW_REPAYMENT
            loan.outstanding_balance = NEW_REPAYMENT
            loan.amount_disbursed    = NEW_PRINCIPAL
            loan.installment_amount  = NEW_INSTALLMENT
            loan.save(update_fields=[
                'principal_amount', 'total_interest', 'total_repayment',
                'outstanding_balance', 'amount_disbursed', 'installment_amount',
            ])

            # Transaction
            txn.amount = NEW_PRINCIPAL
            txn.save(update_fields=['amount'])

            # Journal entry lines
            je_lines = {line.account.gl_code: line for line in je.lines.select_related('account')}
            je_lines[GL_PRINCIPAL].debit_amount = NEW_PRINCIPAL
            je_lines[GL_PRINCIPAL].save(update_fields=['debit_amount'])
            je_lines[GL_CASH].credit_amount = NEW_PRINCIPAL
            je_lines[GL_CASH].save(update_fields=['credit_amount'])

            # LoanRepaymentSchedule rows
            for row in schedule_rows:
                is_last = (row.installment_number == N)
                row.principal_amount  = NEW_PRINCIPAL_LAST  if is_last else NEW_PRINCIPAL_PER
                row.interest_amount   = NEW_INTEREST_LAST   if is_last else NEW_INTEREST_PER
                row.total_amount      = NEW_TOTAL_LAST       if is_last else NEW_TOTAL_PER
                row.outstanding_amount = NEW_TOTAL_LAST      if is_last else NEW_TOTAL_PER
                row.save(update_fields=[
                    'principal_amount', 'interest_amount',
                    'total_amount', 'outstanding_amount',
                ])

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))
        self.stdout.write('Summary:')
        self.stdout.write(f'  Loan principal      : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  Loan total_interest : {OLD_INTEREST} -> {NEW_INTEREST}')
        self.stdout.write(f'  Loan total_repayment: {OLD_REPAYMENT} -> {NEW_REPAYMENT}')
        self.stdout.write(f'  Disbursement txn    : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  JE 1810 debit       : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  JE 1010 credit      : {OLD_PRINCIPAL} -> {NEW_PRINCIPAL}')
        self.stdout.write(f'  Schedule rows 1-{N-1}  : total {NEW_TOTAL_PER}/row')
        self.stdout.write(f'  Schedule row {N}       : total {NEW_TOTAL_LAST} (rounding row)')

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected value for {label}: '
                f'expected {expected}, got {actual}. '
                f'Aborting — do NOT use --commit until this is resolved.'
            )
