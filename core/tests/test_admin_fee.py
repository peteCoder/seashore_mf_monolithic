"""
Tests for the Admin Fee as an editable percentage of the loan principal
(default 2.7%), and the retirement of the Loan Form Fee / Loan Maintenance Fee.

The admin fee replaced an earlier flat amount and a short-lived tiered
schedule. It is now `admin_fee_rate` on the loan product, editable by admin
exactly like the risk premium / tech fee rates.

Loan Form Fee and Loan Maintenance Fee always compute to zero now,
regardless of the (retired, historical-only) *_enabled/*_amount fields
still present on LoanProduct.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.forms.product_forms import LoanProductForm
from core.models import Loan
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestAdminFeeCalculation(TestCase):

    def test_disabled_by_default(self):
        product = make_loan_product(code='AFP001')
        self.assertFalse(product.admin_fee_enabled)
        self.assertEqual(product.admin_fee_rate, Decimal('0.0270'))

        fees = product.calculate_fees(Decimal('100000.00'))
        self.assertEqual(fees['admin_fee'], Decimal('0.00'))

    def test_default_rate_is_2_point_7_percent_of_principal(self):
        product = make_loan_product(code='AFP002', admin_fee_enabled=True)
        self.assertEqual(product.calculate_fees(Decimal('100000.00'))['admin_fee'], Decimal('2700.00'))
        self.assertEqual(product.calculate_fees(Decimal('150000.00'))['admin_fee'], Decimal('4050.00'))
        self.assertEqual(product.calculate_fees(Decimal('2500000.00'))['admin_fee'], Decimal('67500.00'))

    def test_rate_is_editable_per_product(self):
        product = make_loan_product(
            code='AFP004', admin_fee_enabled=True, admin_fee_rate=Decimal('0.0300'),
        )
        self.assertEqual(product.calculate_fees(Decimal('100000.00'))['admin_fee'], Decimal('3000.00'))

    def test_old_flat_admin_fee_amount_field_is_ignored(self):
        product = make_loan_product(
            code='AFP009', admin_fee_enabled=True, admin_fee_amount=Decimal('999999.00'),
        )
        self.assertEqual(product.calculate_fees(Decimal('100000.00'))['admin_fee'], Decimal('2700.00'))

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
        self.assertEqual(fees['total_upfront_fees'], Decimal('2700.00'))

    def test_fee_summary_text_shows_admin_fee_rate_when_enabled(self):
        product = make_loan_product(code='AFP006', admin_fee_enabled=True)
        self.assertIn('Admin Fee: 2.70%', product.get_fee_summary_text())

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


class TestAdminFeeRateForm(TestCase):
    """Admin edits the rate as a plain percentage (2.7), stored as a fraction."""

    def test_form_field_present_and_retired_fields_absent(self):
        form = LoanProductForm()
        self.assertIn('admin_fee_rate', form.fields)
        self.assertIn('admin_fee_enabled', form.fields)
        for retired in ('admin_fee_amount', 'loan_form_fee_amount', 'loan_maintenance_fee_amount'):
            self.assertNotIn(retired, form.fields)

    def test_form_shows_rate_as_percentage_and_saves_as_fraction(self):
        product = make_loan_product(code='AFP010', admin_fee_enabled=True)
        form = LoanProductForm(instance=product)
        self.assertEqual(Decimal(str(form.initial['admin_fee_rate'])), Decimal('2.7'))

        form = LoanProductForm(data={}, instance=product)
        form.cleaned_data = {'admin_fee_rate': Decimal('3.5')}
        self.assertEqual(form.clean_admin_fee_rate(), Decimal('0.0350'))


class TestAdminFeeOnLoan(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='AFL001')
        cls.staff = make_user(cls.branch, role='staff', email='afl_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='afl_client@test.com')

    def _loan(self, product, principal):
        return Loan.objects.create(
            client=self.client_obj, loan_product=product, branch=self.branch,
            principal_amount=Decimal(principal), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='pending_fees',
        )

    def test_loan_copies_zero_admin_fee_when_product_disabled(self):
        loan = self._loan(make_loan_product(code='AFLP001', admin_fee_enabled=False), '100000.00')
        self.assertEqual(loan.admin_fee, Decimal('0.00'))

    def test_loan_gets_percentage_admin_fee_when_product_enabled(self):
        loan = self._loan(make_loan_product(code='AFLP002', admin_fee_enabled=True), '800000.00')
        self.assertEqual(loan.admin_fee, Decimal('21600.00'))  # 2.7% of 800,000
        self.assertGreaterEqual(loan.total_upfront_fees, Decimal('21600.00'))

    def test_loan_never_gets_form_or_maintenance_fee(self):
        product = make_loan_product(
            code='AFLP003',
            loan_form_fee_enabled=True, loan_form_fee_amount=Decimal('200.00'),
            loan_maintenance_fee_enabled=True, loan_maintenance_fee_amount=Decimal('200.00'),
        )
        loan = self._loan(product, '100000.00')
        self.assertEqual(loan.loan_form_fee, Decimal('0.00'))
        self.assertEqual(loan.loan_maintenance_fee, Decimal('0.00'))


class TestAdminFeePages(TestCase):
    """The pages an admin/staff actually use: product form, detail, API, loan form."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='AFPG01')
        cls.admin = make_user(cls.branch, role='admin', email='afpg_admin@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='afpg_staff@test.com')
        cls.product = make_loan_product(code='AFPG-P', admin_fee_enabled=True, loan_type='regular')

    def test_product_edit_page_shows_rate_field_and_no_retired_fields(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_product_update', args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('Admin Fee Rate (%)', html)
        self.assertIn('name="admin_fee_rate"', html)
        self.assertIn('value="2.7"', html)
        for gone in ('Loan Form Fee', 'Loan Maintenance Fee', 'name="admin_fee_amount"',
                     'name="loan_form_fee_amount"', 'name="loan_maintenance_fee_amount"'):
            self.assertNotIn(gone, html)

    def test_product_create_page_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_product_create'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="admin_fee_rate"', response.content.decode())

    def test_admin_can_edit_rate_through_the_form_and_new_rate_applies(self):
        self.client.force_login(self.admin)
        url = reverse('core:loan_product_update', args=[self.product.id])
        data = {}
        form = LoanProductForm(instance=self.product)
        for name, field in form.fields.items():
            value = form.initial.get(name, field.initial)
            if value is None:
                continue
            if isinstance(value, bool):
                if value:
                    data[name] = 'on'
            else:
                data[name] = str(value)
        data['admin_fee_rate'] = '3.5'
        response = self.client.post(url, data)
        ctx_form = response.context and response.context.get('form')
        self.assertEqual(response.status_code, 302, ctx_form.errors.as_json() if ctx_form else response.content[:500])
        self.product.refresh_from_db()
        self.assertEqual(self.product.admin_fee_rate, Decimal('0.0350'))
        self.assertEqual(self.product.calculate_fees(Decimal('100000'))['admin_fee'], Decimal('3500.00'))

    def test_product_detail_page_shows_rate(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_product_detail', args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('2.70% of loan amount', html)
        self.assertNotIn('Loan Form Fee', html)

    def test_product_api_returns_rate_not_brackets(self):
        self.client.force_login(self.staff)
        data = self.client.get(reverse('core:loan_product_api', args=[self.product.id])).json()
        admin_fee = data['fees']['admin_fee']
        self.assertTrue(admin_fee['enabled'])
        self.assertAlmostEqual(admin_fee['rate'], 0.027)
        self.assertAlmostEqual(admin_fee['rate_percent'], 2.7)
        self.assertNotIn('brackets', admin_fee)
        self.assertNotIn('loan_form_fee', data['fees'])
        self.assertNotIn('loan_maintenance_fee', data['fees'])

    def test_loan_application_page_renders(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_create'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('fees.admin_fee.rate_percent', html)
        self.assertNotIn('brackets', html)
        self.assertNotIn('fees.loan_form_fee', html)
