"""
Tests for the new Admin Fee (₦2,500 flat, matching the Loan Form Fee /
Loan Maintenance Fee pattern). Built disabled by default — activation is a
separate, deliberate step (see core/management/commands, or the Loan
Product edit page: admin_fee_enabled).
"""
from decimal import Decimal

from django.test import TestCase

from core.models import Loan
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestAdminFeeCalculation(TestCase):

    def test_disabled_by_default(self):
        product = make_loan_product(code='AFP001')
        self.assertFalse(product.admin_fee_enabled)
        self.assertEqual(product.admin_fee_amount, Decimal('2500.00'))

        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['admin_fee'], Decimal('0.00'))

    def test_included_when_enabled(self):
        product = make_loan_product(code='AFP002', admin_fee_enabled=True)
        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['admin_fee'], Decimal('2500.00'))

    def test_total_upfront_fees_includes_admin_fee(self):
        product = make_loan_product(
            code='AFP003',
            admin_fee_enabled=True,
            loan_form_fee_enabled=True, loan_form_fee_amount=Decimal('200.00'),
            risk_premium_enabled=False, rp_income_enabled=False, tech_fee_enabled=False,
        )
        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['total_upfront_fees'], Decimal('2700.00'))  # 2500 + 200

    def test_custom_admin_fee_amount(self):
        product = make_loan_product(
            code='AFP004', admin_fee_enabled=True, admin_fee_amount=Decimal('3000.00'),
        )
        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['admin_fee'], Decimal('3000.00'))

    def test_fee_summary_text_includes_admin_fee_when_enabled(self):
        product = make_loan_product(code='AFP005', admin_fee_enabled=True)
        self.assertIn('Admin Fee: ₦2,500.00', product.get_fee_summary_text())

    def test_fee_summary_text_omits_admin_fee_when_disabled(self):
        product = make_loan_product(code='AFP006', admin_fee_enabled=False)
        self.assertNotIn('Admin Fee', product.get_fee_summary_text())


class TestAdminFeeOnLoan(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='AFL001')
        cls.staff = make_user(cls.branch, role='staff', email='afl_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='afl_client@test.com')

    def test_loan_copies_zero_admin_fee_when_product_disabled(self):
        product = make_loan_product(code='AFLP001', admin_fee_enabled=False)
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='pending_fees',
        )
        self.assertEqual(loan.admin_fee, Decimal('0.00'))

    def test_loan_copies_admin_fee_when_product_enabled(self):
        product = make_loan_product(code='AFLP002', admin_fee_enabled=True)
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='pending_fees',
        )
        self.assertEqual(loan.admin_fee, Decimal('2500.00'))
        self.assertGreaterEqual(loan.total_upfront_fees, Decimal('2500.00'))
