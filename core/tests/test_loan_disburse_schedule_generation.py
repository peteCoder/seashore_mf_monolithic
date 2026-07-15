"""
Tests for Loan.disburse() repayment-schedule generation.

Regression coverage for a bug where loans could go 'active' with zero
LoanRepaymentSchedule rows — either because number_of_installments was
never calculated (legacy default 0, e.g. loans created via bulk_create()
which bypasses save()/calculate_loan_details()) or because schedule
generation raised an exception — and disbursement still silently
"succeeded". Since the repayment tracker (/loans/repayment-tracker/) is
built entirely from LoanRepaymentSchedule rows, such loans were
structurally invisible to it even though they still owed money — this is
the reported "only shows new clients" symptom.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import Loan, LoanRepaymentSchedule, Transaction
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestLoanDisburseScheduleGeneration(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='LDS001')
        cls.manager = make_user(cls.branch, role='manager', email='lds_mgr@test.com')
        cls.client_obj = make_client(cls.branch, cls.manager, email='lds_client@test.com')
        cls.product = make_loan_product(code='LDSP001')

    def _make_approved_loan(self, **kwargs):
        defaults = dict(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.manager,
            purpose='Business', status='approved',
        )
        defaults.update(kwargs)
        # Loan.save() calls calculate_loan_details() on creation, which
        # correctly computes number_of_installments/total_repayment for any
        # positive duration_months — this is the normal creation path.
        return Loan.objects.create(**defaults)

    def test_normal_loan_still_generates_schedule(self):
        """Sanity check: a loan created via the normal path (installment
        count correctly calculated at creation) still disburses and
        generates its schedule exactly as before."""
        loan = self._make_approved_loan()
        self.assertEqual(loan.number_of_installments, 6)  # monthly, 6 months
        success, message = loan.disburse(disbursed_by=self.manager)
        self.assertTrue(success, message)
        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan).count(), 6)

    def test_zero_installments_self_heals_and_generates_schedule(self):
        """Regression test: a loan with the legacy number_of_installments=0
        bug (e.g. imported via bulk_create(), which bypasses save() and
        never runs calculate_loan_details()) must now self-heal at
        disbursement time and still get a full schedule persisted, instead
        of silently disbursing with none."""
        loan = self._make_approved_loan()
        # Simulate the legacy corruption: force it back to 0 in the DB,
        # bypassing save() so calculate_loan_details() does NOT re-run.
        Loan.objects.filter(id=loan.id).update(number_of_installments=0)
        loan.refresh_from_db()
        self.assertEqual(loan.number_of_installments, 0)

        success, message = loan.disburse(disbursed_by=self.manager)
        self.assertTrue(success, message)

        loan.refresh_from_db()
        self.assertEqual(loan.number_of_installments, 6)
        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan).count(), 6)

    def test_unrecoverable_failure_rolls_back_entire_disbursement(self):
        """When schedule generation fails even after the self-heal attempt
        (e.g. an unexpected internal error), the whole disbursement — status
        change, Transaction — must roll back, not just skip the schedule
        step and silently report success."""
        loan = self._make_approved_loan()

        with patch(
            'core.models.all_models.generate_repayment_schedule',
            side_effect=RuntimeError('boom'),
        ):
            with self.assertRaises(ValueError):
                loan.disburse(disbursed_by=self.manager)

        loan.refresh_from_db()
        self.assertEqual(loan.status, 'approved')
        self.assertEqual(LoanRepaymentSchedule.objects.filter(loan=loan).count(), 0)
        self.assertEqual(Transaction.objects.filter(loan=loan).count(), 0)

    def test_disburse_view_shows_error_instead_of_500(self):
        """The view must catch the new ValueError and surface it as a normal
        form error (messages.error + redirect back to the disburse form),
        not a 500."""
        loan = self._make_approved_loan()
        self.client.force_login(self.manager)

        with patch(
            'core.models.all_models.generate_repayment_schedule',
            side_effect=RuntimeError('boom'),
        ):
            response = self.client.post(
                reverse('core:loan_disburse', args=[loan.id]),
                {
                    'disbursement_method': 'cash',
                    'disbursement_date': '2026-01-01',
                },
            )
        self.assertEqual(response.status_code, 200)
        loan.refresh_from_db()
        self.assertEqual(loan.status, 'approved')
