"""
Management command: correct_odekhoa_loan
=========================================

Corrects Odekhoa Queen's loan principal from N10,500 to N150,000.
Loan is at pending_fees stage — no fees paid, no transactions, no schedule rows.

Loan : 8abf2198-4383-4c61-9aa6-b53bd79bd55a  (LN20260514151959740407)

                          OLD (10,500)    NEW (150,000)
  principal_amount     :      10,500  ->     150,000
  total_interest       :       1,890  ->      27,000   (150k x 3% x 6 months)
  total_repayment      :      12,390  ->     177,000
  installment_amount   :      516.25  ->       7,375   (177,000 / 24 = exact)
  risk_premium_fee     :      157.50  ->       2,250   (150k x 1.5%)
  rp_income_fee        :      157.50  ->       2,250   (150k x 1.5%)
  tech_fee             :       52.50  ->         750   (150k x 0.5%)
  loan_form_fee        :      200.00  ->      200.00   (fixed, unchanged)
  loan_maintenance_fee :      200.00  ->      200.00   (fixed, unchanged)
  total_upfront_fees   :      767.50  ->       5,650

Usage
-----
  python manage.py correct_odekhoa_loan --dry-run
  python manage.py correct_odekhoa_loan --commit
"""

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID = '8abf2198-4383-4c61-9aa6-b53bd79bd55a'

OLD_PRINCIPAL    = Decimal('10500.00')
OLD_INTEREST     = Decimal('1890.00')
OLD_REPAYMENT    = Decimal('12390.00')
OLD_INSTALLMENT  = Decimal('516.25')
OLD_RISK_PREMIUM = Decimal('157.50')
OLD_RP_INCOME    = Decimal('157.50')
OLD_TECH_FEE     = Decimal('52.50')
OLD_TOTAL_FEES   = Decimal('767.50')
FIXED_FEE        = Decimal('200.00')

NEW_PRINCIPAL    = Decimal('150000.00')
NEW_INTEREST     = Decimal('27000.00')    # 150k x 3% x 6
NEW_REPAYMENT    = Decimal('177000.00')   # 150k + 27k
NEW_INSTALLMENT  = Decimal('7375.00')     # 177k / 24 (exact)
NEW_RISK_PREMIUM = Decimal('2250.00')     # 150k x 1.5%
NEW_RP_INCOME    = Decimal('2250.00')     # 150k x 1.5%
NEW_TECH_FEE     = Decimal('750.00')      # 150k x 0.5%
NEW_TOTAL_FEES   = Decimal('5650.00')     # 2250+2250+750+200+200


class Command(BaseCommand):
    help = 'Correct Odekhoa Queen loan principal from N10,500 to N150,000'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import Loan, LoanRepaymentSchedule, Transaction

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== correct_odekhoa_loan [{mode}] ===\n'))

        # Pre-flight arithmetic checks
        assert NEW_INTEREST  == NEW_PRINCIPAL * Decimal('0.03') * 6,  'Interest calc error'
        assert NEW_REPAYMENT == NEW_PRINCIPAL + NEW_INTEREST,         'Repayment calc error'
        assert NEW_INSTALLMENT * 24 == NEW_REPAYMENT,                 'Installment calc error (not exact)'
        fee_check = NEW_RISK_PREMIUM + NEW_RP_INCOME + NEW_TECH_FEE + FIXED_FEE + FIXED_FEE
        assert fee_check == NEW_TOTAL_FEES, f'Fee total error: {fee_check}'
        self.stdout.write('Arithmetic checks: OK')

        # Fetch loan
        try:
            loan = Loan.objects.get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        self.stdout.write(f'\nLOAN')
        self.stdout.write(f'  loan_number  : {loan.loan_number}')
        self.stdout.write(f'  client       : {loan.client}')
        self.stdout.write(f'  status       : {loan.status}  (must be pending_fees)')
        self.stdout.write(f'  amount_paid  : {loan.amount_paid}  (must be 0)')
        self.stdout.write(f'  amount_disbursed: {loan.amount_disbursed}  (must be 0)')

        if loan.status != 'pending_fees':
            raise CommandError(f'Status is {loan.status!r}, expected pending_fees. Aborting.')
        if loan.amount_paid != Decimal('0.00'):
            raise CommandError(f'amount_paid={loan.amount_paid} is not 0. Aborting.')
        if loan.amount_disbursed != Decimal('0.00'):
            raise CommandError(f'amount_disbursed={loan.amount_disbursed} is not 0. Aborting.')

        # Guard: no transactions, no schedule rows
        txn_count = Transaction.objects.filter(loan=loan).count()
        sched_count = LoanRepaymentSchedule.objects.filter(loan=loan).count()
        if txn_count != 0:
            raise CommandError(f'Found {txn_count} transaction(s) on this loan. Aborting.')
        if sched_count != 0:
            raise CommandError(f'Found {sched_count} schedule row(s) on this loan. Aborting.')

        # Assert current values
        self._assert(loan.principal_amount,    OLD_PRINCIPAL,    'principal_amount')
        self._assert(loan.total_interest,      OLD_INTEREST,     'total_interest')
        self._assert(loan.total_repayment,     OLD_REPAYMENT,    'total_repayment')
        self._assert(loan.installment_amount,  OLD_INSTALLMENT,  'installment_amount')
        self._assert(loan.risk_premium_fee,    OLD_RISK_PREMIUM, 'risk_premium_fee')
        self._assert(loan.rp_income_fee,       OLD_RP_INCOME,    'rp_income_fee')
        self._assert(loan.tech_fee,            OLD_TECH_FEE,     'tech_fee')
        self._assert(loan.total_upfront_fees,  OLD_TOTAL_FEES,   'total_upfront_fees')
        self._assert(loan.loan_form_fee,       FIXED_FEE,        'loan_form_fee')
        self._assert(loan.loan_maintenance_fee, FIXED_FEE,       'loan_maintenance_fee')

        self.stdout.write(f'\n  {"Field":<25} {"Old":>12}  ->  {"New":>12}')
        self.stdout.write(f'  {"-"*55}')
        self.stdout.write(f'  {"principal_amount":<25} {OLD_PRINCIPAL:>12}  ->  {NEW_PRINCIPAL:>12}')
        self.stdout.write(f'  {"total_interest":<25} {OLD_INTEREST:>12}  ->  {NEW_INTEREST:>12}')
        self.stdout.write(f'  {"total_repayment":<25} {OLD_REPAYMENT:>12}  ->  {NEW_REPAYMENT:>12}')
        self.stdout.write(f'  {"installment_amount":<25} {OLD_INSTALLMENT:>12}  ->  {NEW_INSTALLMENT:>12}')
        self.stdout.write(f'  {"risk_premium_fee":<25} {OLD_RISK_PREMIUM:>12}  ->  {NEW_RISK_PREMIUM:>12}')
        self.stdout.write(f'  {"rp_income_fee":<25} {OLD_RP_INCOME:>12}  ->  {NEW_RP_INCOME:>12}')
        self.stdout.write(f'  {"tech_fee":<25} {OLD_TECH_FEE:>12}  ->  {NEW_TECH_FEE:>12}')
        self.stdout.write(f'  {"loan_form_fee":<25} {FIXED_FEE:>12}       (unchanged)')
        self.stdout.write(f'  {"loan_maintenance_fee":<25} {FIXED_FEE:>12}       (unchanged)')
        self.stdout.write(f'  {"total_upfront_fees":<25} {OLD_TOTAL_FEES:>12}  ->  {NEW_TOTAL_FEES:>12}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        with db_transaction.atomic():
            loan.principal_amount    = NEW_PRINCIPAL
            loan.total_interest      = NEW_INTEREST
            loan.total_repayment     = NEW_REPAYMENT
            loan.installment_amount  = NEW_INSTALLMENT
            loan.risk_premium_fee    = NEW_RISK_PREMIUM
            loan.rp_income_fee       = NEW_RP_INCOME
            loan.tech_fee            = NEW_TECH_FEE
            loan.total_upfront_fees  = NEW_TOTAL_FEES
            loan.save(update_fields=[
                'principal_amount', 'total_interest', 'total_repayment',
                'installment_amount', 'risk_premium_fee', 'rp_income_fee',
                'tech_fee', 'total_upfront_fees',
            ])

        self.stdout.write(self.style.SUCCESS('\nCorrection applied successfully.\n'))

    def _assert(self, actual, expected, label):
        if actual != expected:
            raise CommandError(
                f'Unexpected {label}: expected {expected}, got {actual}. Aborting.'
            )
