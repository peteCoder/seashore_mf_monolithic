"""
Model Validation Tests
=======================

Tests for model clean() methods, field constraints, and business rules
on Loan, SavingsAccount, Client, and Branch models.
"""

from decimal import Decimal
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.tests.factories import make_branch, make_user, make_client, make_loan_product, make_savings_product


# =============================================================================
# Branch Model
# =============================================================================

class TestBranchModel(TestCase):

    def test_create_branch(self):
        branch = make_branch(name='Lekki Branch', code='LKI001')
        self.assertEqual(str(branch.name), 'Lekki Branch')
        self.assertTrue(branch.is_active)

    def test_branch_code_unique(self):
        from django.db import IntegrityError
        make_branch(code='UNIQ001')
        with self.assertRaises(Exception):
            make_branch(code='UNIQ001')


# =============================================================================
# User Model
# =============================================================================

class TestUserModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()

    def test_create_staff_user(self):
        user = make_user(self.branch, role='staff', email='staff@test.com')
        self.assertEqual(user.user_role, 'staff')
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_approved)

    def test_user_email_is_unique(self):
        make_user(self.branch, email='unique@test.com')
        with self.assertRaises(Exception):
            make_user(self.branch, email='unique@test.com')

    def test_user_full_name(self):
        user = make_user(self.branch, role='manager', email='mgr@test.com')
        self.assertIn('Manager', user.get_full_name())

    def test_check_password(self):
        user = make_user(self.branch, email='pwd@test.com')
        self.assertTrue(user.check_password('TestPass123!'))
        self.assertFalse(user.check_password('WrongPass'))

    def test_2fa_fields_default(self):
        user = make_user(self.branch, email='2fa@test.com')
        self.assertFalse(user.is_2fa_enabled)
        self.assertIsNone(user.totp_secret)


# =============================================================================
# Client Model
# =============================================================================

class TestClientModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.staff = make_user(cls.branch, role='staff', email='cl_staff@test.com')

    def test_create_client(self):
        client = make_client(self.branch, self.staff, email='client1@test.com')
        self.assertEqual(client.first_name, 'Test')
        self.assertEqual(client.approval_status, 'approved')

    def test_client_id_auto_generated(self):
        client = make_client(self.branch, self.staff, email='client2@test.com')
        self.assertIsNotNone(client.client_id)
        self.assertTrue(len(client.client_id) > 0)

    def test_client_get_full_name(self):
        client = make_client(self.branch, self.staff, email='client3@test.com')
        full_name = client.get_full_name()
        self.assertIn('Test', full_name)
        self.assertIn('Client', full_name)


# =============================================================================
# LoanProduct Model
# =============================================================================

class TestLoanProductModel(TestCase):

    def test_create_loan_product(self):
        product = make_loan_product()
        self.assertEqual(product.monthly_interest_rate, Decimal('0.03'))
        self.assertEqual(product.interest_calculation_method, 'flat')
        self.assertTrue(product.is_active)

    def test_min_max_amount_logic(self):
        product = make_loan_product(
            code='LNP002',
            min_principal_amount=Decimal('50000.00'),
            max_principal_amount=Decimal('500000.00'),
        )
        self.assertLess(product.min_principal_amount, product.max_principal_amount)


# =============================================================================
# SavingsProduct Model
# =============================================================================

class TestSavingsProductModel(TestCase):

    def test_create_savings_product(self):
        product = make_savings_product()
        self.assertEqual(product.product_type, 'regular')
        self.assertEqual(product.interest_rate_annual, Decimal('4.00'))

    def test_fixed_deposit_product(self):
        fd = make_savings_product(
            name='Fixed Deposit 6M',
            code='FD006',
            product_type='fixed',
            interest_rate_annual=Decimal('8.00'),
        )
        self.assertEqual(fd.product_type, 'fixed')


# =============================================================================
# Loan Model
# =============================================================================

class TestLoanModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='LN001')
        cls.staff = make_user(cls.branch, role='staff', email='ln_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='ln_mgr@test.com')
        cls.loan_client = make_client(cls.branch, cls.staff, email='lnclient@test.com')
        cls.product = make_loan_product(code='LNP001')

    def _make_loan(self, **kwargs):
        from core.models import Loan
        defaults = dict(
            client=self.__class__.loan_client,
            loan_product=self.product,
            branch=self.branch,
            principal_amount=Decimal('100000.00'),
            duration_months=6,
            disbursement_method='cash',
            created_by=self.__class__.staff,
            purpose='Business expansion',
            status='pending_fees',
        )
        defaults.update(kwargs)
        return Loan.objects.create(**defaults)

    def test_loan_number_auto_generated(self):
        loan = self._make_loan()
        self.assertIsNotNone(loan.loan_number)
        self.assertTrue(loan.loan_number.startswith('LN'))

    def test_loan_default_status(self):
        loan = self._make_loan()
        self.assertEqual(loan.status, 'pending_fees')

    def test_loan_principal_amount(self):
        loan = self._make_loan(principal_amount=Decimal('250000.00'))
        self.assertEqual(loan.principal_amount, Decimal('250000.00'))

    def test_multiple_loans_unique_numbers(self):
        loan1 = self._make_loan()
        loan2 = self._make_loan()
        self.assertNotEqual(loan1.loan_number, loan2.loan_number)


# =============================================================================
# SavingsAccount Model
# =============================================================================

class TestSavingsAccountModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SV001')
        cls.staff = make_user(cls.branch, role='staff', email='sv_staff@test.com')
        cls.sa_client = make_client(cls.branch, cls.staff, email='svclient@test.com')
        cls.product = make_savings_product(code='SVP001')

    def _make_savings(self, **kwargs):
        from core.models import SavingsAccount
        defaults = dict(
            client=self.__class__.sa_client,
            savings_product=self.product,
            branch=self.branch,
            status='active',
            balance=Decimal('0.00'),
            approval_status='approved',
        )
        defaults.update(kwargs)
        return SavingsAccount.objects.create(**defaults)

    def test_account_number_auto_generated(self):
        account = self._make_savings()
        self.assertIsNotNone(account.account_number)

    def test_initial_balance_zero(self):
        account = self._make_savings(balance=Decimal('0.00'))
        self.assertEqual(account.balance, Decimal('0.00'))

    def test_savings_account_linked_to_client(self):
        account = self._make_savings()
        self.assertEqual(account.client, self.__class__.sa_client)
