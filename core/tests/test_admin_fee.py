"""
Tests for the tiered Admin Fee (management decision, 2026-09) and the
retirement of the Loan Form Fee / Loan Maintenance Fee.

Admin fee is no longer a fixed amount configured per loan product — it is
looked up from ADMIN_FEE_BRACKETS based on the loan principal, with the
upper bound of each bracket inclusive:
  0 - 300,000        -> 2,500
  300,000 - 700,000  -> 5,000
  700,000 - 1,000,000 -> 7,500
  1,000,000 - 1,500,000 -> 10,000
  1,500,000 - 2,000,000 -> 15,000
  above 2,000,000    -> 20,000

Loan Form Fee and Loan Maintenance Fee always compute to zero now,
regardless of the (retired, historical-only) *_enabled/*_amount fields
still present on LoanProduct.
"""
from decimal import Decimal

from django.test import TestCase

from core.models import Loan, get_tiered_admin_fee
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestTieredAdminFeeLookup(TestCase):

    def test_bracket_boundaries_are_upper_bound_inclusive(self):
        cases = [
            (Decimal('1.00'),         Decimal('2500.00')),
            (Decimal('300000.00'),    Decimal('2500.00')),   # exact boundary -> lower tier
            (Decimal('300000.01'),    Decimal('5000.00')),
            (Decimal('700000.00'),    Decimal('5000.00')),
            (Decimal('700000.01'),    Decimal('7500.00')),
            (Decimal('1000000.00'),   Decimal('7500.00')),
            (Decimal('1000000.01'),   Decimal('10000.00')),
            (Decimal('1500000.00'),   Decimal('10000.00')),
            (Decimal('1500000.01'),   Decimal('15000.00')),
            (Decimal('2000000.00'),   Decimal('15000.00')),
            (Decimal('2000000.01'),   Decimal('20000.00')),
            (Decimal('10000000.00'),  Decimal('20000.00')),
        ]
        for principal, expected_fee in cases:
            with self.subTest(principal=principal):
                self.assertEqual(get_tiered_admin_fee(principal), expected_fee)


class TestAdminFeeCalculation(TestCase):

    def test_disabled_by_default(self):
        product = make_loan_product(code='AFP001')
        self.assertFalse(product.admin_fee_enabled)

        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['admin_fee'], Decimal('0.00'))

    def test_included_when_enabled_uses_bracket_for_principal(self):
        product = make_loan_product(code='AFP002', admin_fee_enabled=True)
        self.assertEqual(product.calculate_fees(Decimal('100000.00'))['admin_fee'], Decimal('2500.00'))
        self.assertEqual(product.calculate_fees(Decimal('500000.00'))['admin_fee'], Decimal('5000.00'))
        self.assertEqual(product.calculate_fees(Decimal('2500000.00'))['admin_fee'], Decimal('20000.00'))

    def test_old_fixed_admin_fee_amount_field_is_ignored(self):
        """Setting the retired admin_fee_amount field must not affect the tiered lookup."""
        product = make_loan_product(
            code='AFP004', admin_fee_enabled=True, admin_fee_amount=Decimal('999999.00'),
        )
        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['admin_fee'], Decimal('2500.00'))

    def test_loan_form_fee_and_maintenance_fee_always_zero(self):
        """Even if the retired enabled flags are left on, these fees never apply."""
        product = make_loan_product(
            code='AFP005',
            loan_form_fee_enabled=True, loan_form_fee_amount=Decimal('200.00'),
            loan_maintenance_fee_enabled=True, loan_maintenance_fee_amount=Decimal('200.00'),
        )
        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['loan_form_fee'], Decimal('0.00'))
        self.assertEqual(fees['loan_maintenance_fee'], Decimal('0.00'))

    def test_total_upfront_fees_includes_only_admin_fee(self):
        product = make_loan_product(
            code='AFP003',
            admin_fee_enabled=True,
            loan_form_fee_enabled=True, loan_form_fee_amount=Decimal('200.00'),
            risk_premium_enabled=False, rp_income_enabled=False, tech_fee_enabled=False,
        )
        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['total_upfront_fees'], Decimal('2500.00'))

    def test_fee_summary_text_includes_admin_fee_when_enabled(self):
        product = make_loan_product(code='AFP006', admin_fee_enabled=True)
        self.assertIn('Admin Fee', product.get_fee_summary_text())

    def test_fee_summary_text_omits_admin_fee_when_disabled(self):
        product = make_loan_product(code='AFP007', admin_fee_enabled=False)
        self.assertNotIn('Admin Fee', product.get_fee_summary_text())

    def test_fee_summary_text_omits_retired_form_and_maintenance_fees(self):
        product = make_loan_product(
            code='AFP008',
            loan_form_fee_enabled=True, loan_maintenance_fee_enabled=True,
        )
        text = product.get_fee_summary_text()
        self.assertNotIn('Form Fee', text)
        self.assertNotIn('Maintenance Fee', text)


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

    def test_loan_copies_tiered_admin_fee_when_product_enabled(self):
        product = make_loan_product(code='AFLP002', admin_fee_enabled=True)
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=product, branch=self.branch,
            principal_amount=Decimal('800000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='pending_fees',
        )
        self.assertEqual(loan.admin_fee, Decimal('7500.00'))
        self.assertGreaterEqual(loan.total_upfront_fees, Decimal('7500.00'))

    def test_loan_never_gets_form_or_maintenance_fee(self):
        product = make_loan_product(
            code='AFLP003',
            loan_form_fee_enabled=True, loan_form_fee_amount=Decimal('200.00'),
            loan_maintenance_fee_enabled=True, loan_maintenance_fee_amount=Decimal('200.00'),
        )
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='pending_fees',
        )
        self.assertEqual(loan.loan_form_fee, Decimal('0.00'))
        self.assertEqual(loan.loan_maintenance_fee, Decimal('0.00'))
