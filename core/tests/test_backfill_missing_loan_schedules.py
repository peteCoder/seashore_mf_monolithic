"""
Tests for the backfill_missing_loan_schedules management command — the
remediation for loans already affected by the "repayment tracker only
shows newly disbursed loans" bug (active loans with outstanding balances
but zero LoanRepaymentSchedule rows).
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule, LoanRepaymentPosting
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestBackfillMissingLoanSchedules(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='BMS001')
        cls.manager = make_user(cls.branch, role='manager', email='bms_mgr@test.com')
        cls.client_obj = make_client(cls.branch, cls.manager, email='bms_client@test.com')
        cls.product = make_loan_product(code='BMSP001')

    def _make_broken_old_loan(self):
        """Simulate a loan that was disbursed long ago but ended up with
        zero schedule rows and number_of_installments=0 — the exact bug
        this command repairs. Uses .update() (not .save()) to bypass
        calculate_loan_details(), matching how the real corruption looks."""
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.manager,
            purpose='Business', status='approved',
        )
        Loan.objects.filter(id=loan.id).update(
            status='active',
            disbursement_date=timezone.now() - timedelta(days=200),
            outstanding_balance=loan.total_repayment,
            number_of_installments=0,
        )
        loan.refresh_from_db()
        return loan

    def test_dry_run_does_not_modify_anything(self):
        loan = self._make_broken_old_loan()
        out = StringIO()
        call_command('backfill_missing_loan_schedules', '--dry-run', stdout=out)

        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan).count(), 0)
        loan.refresh_from_db()
        self.assertEqual(loan.number_of_installments, 0)

    def test_commit_creates_schedule_and_fixes_installment_count(self):
        loan = self._make_broken_old_loan()
        out = StringIO()
        call_command('backfill_missing_loan_schedules', '--commit', stdout=out)

        loan.refresh_from_db()
        self.assertEqual(loan.number_of_installments, 6)
        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan).count(), 6)

    def test_commit_allocates_existing_approved_postings(self):
        """A client who has genuinely been paying must not appear to have
        paid nothing just because their schedule rows didn't exist yet."""
        loan = self._make_broken_old_loan()
        installment_amount = loan.total_repayment / 6

        LoanRepaymentPosting.objects.create(
            loan=loan, amount=installment_amount,
            payment_date=timezone.now().date() - timedelta(days=100),
            status='approved', submitted_by=self.manager,
        )

        call_command('backfill_missing_loan_schedules', '--commit', stdout=StringIO())

        rows = list(
            LoanRepaymentSchedule.objects.filter(loan=loan).order_by('installment_number')
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0].amount_paid, installment_amount.quantize(Decimal('0.01')))
        self.assertEqual(rows[0].status, 'paid')
        self.assertEqual(rows[1].amount_paid, Decimal('0.00'))

    def test_loans_with_existing_schedule_are_untouched(self):
        loan = self._make_broken_old_loan()
        LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=1, due_date=timezone.now().date(),
            principal_amount=Decimal('16000.00'), interest_amount=Decimal('4000.00'),
            total_amount=Decimal('20000.00'), outstanding_amount=Decimal('20000.00'),
        )
        call_command('backfill_missing_loan_schedules', '--commit', stdout=StringIO())

        # Still only the 1 pre-existing row — command must not touch loans
        # that already have schedule rows.
        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan).count(), 1)

    def test_loan_id_filter_scopes_to_a_single_loan(self):
        loan1 = self._make_broken_old_loan()
        loan2 = self._make_broken_old_loan()

        call_command(
            'backfill_missing_loan_schedules', '--commit',
            f'--loan-id={loan1.id}', stdout=StringIO(),
        )

        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan1).count(), 6)
        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan2).count(), 0)
