"""
Tests for the Officer Snapshot report — one at-a-glance row per loan officer
with loan portfolio, savers, clients, loans, overdue and savings portfolio.

Focus: the six figures are computed correctly, staff only ever see their own
row, and managers/HR who have clients assigned directly to them show up too.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule, SavingsAccount
from core.tests.factories import (
    make_branch, make_user, make_client, make_loan_product, make_savings_product,
)

URL = 'core:report_officer_snapshot'


def _loan(client_obj, product, branch, officer, outstanding, status='active'):
    return Loan.objects.create(
        client=client_obj, loan_product=product, branch=branch,
        principal_amount=Decimal('100000.00'), duration_months=3,
        disbursement_method='cash', created_by=officer,
        purpose='Business', status=status,
        outstanding_balance=Decimal(outstanding),
        disbursement_date=timezone.now(),
    )


def _row_for(response, officer):
    return next(r for r in response.context['rows'] if r['officer'] == officer)


class OfficerSnapshotFigureTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='OS001')
        cls.staff = make_user(cls.branch, role='staff', email='os_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='os_mgr@test.com')
        cls.product = make_loan_product(code='OSP001')
        cls.sav_product = make_savings_product(code='OSS001')

        cls.c1 = make_client(cls.branch, cls.staff, email='os_c1@test.com')
        cls.c2 = make_client(cls.branch, cls.staff, email='os_c2@test.com')
        cls.c_inactive = make_client(cls.branch, cls.staff, email='os_c3@test.com')
        cls.c_inactive.is_active = False
        cls.c_inactive.save(update_fields=['is_active'])

        cls.loan1 = _loan(cls.c1, cls.product, cls.branch, cls.staff, '40000.00')
        cls.loan2 = _loan(cls.c2, cls.product, cls.branch, cls.staff, '60000.00')
        _loan(cls.c1, cls.product, cls.branch, cls.staff, '999.00', status='completed')

        # loan1 has one overdue and one future installment; loan2 is up to date
        today = timezone.now().date()
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan1, installment_number=1, due_date=today - timedelta(days=10),
            principal_amount=Decimal('8000.00'), interest_amount=Decimal('2000.00'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan1, installment_number=2, due_date=today + timedelta(days=20),
            principal_amount=Decimal('8000.00'), interest_amount=Decimal('2000.00'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
        )

        # c1 has two savings accounts (still ONE saver), c2 has none
        SavingsAccount.objects.create(
            client=cls.c1, savings_product=cls.sav_product, branch=cls.branch,
            status='active', balance=Decimal('5000.00'), approval_status='approved',
        )
        SavingsAccount.objects.create(
            client=cls.c1, savings_product=cls.sav_product, branch=cls.branch,
            status='active', balance=Decimal('2500.00'), approval_status='approved',
        )

    def setUp(self):
        self.client.force_login(self.manager)

    def test_all_six_figures(self):
        response = self.client.get(reverse(URL))
        self.assertEqual(response.status_code, 200)
        row = _row_for(response, self.staff)
        self.assertEqual(row['loan_portfolio'], Decimal('100000.00'))   # 40k + 60k, completed excluded
        self.assertEqual(row['loans'], 2)
        self.assertEqual(row['clients'], 2)                              # inactive client excluded
        self.assertEqual(row['savers'], 1)                               # distinct clients, not accounts
        self.assertEqual(row['savings_portfolio'], Decimal('7500.00'))
        self.assertEqual(row['overdue_loans'], 1)
        self.assertEqual(row['overdue_amount'], Decimal('10000.00'))     # future installment excluded

    def test_totals_sum_the_rows(self):
        response = self.client.get(reverse(URL))
        totals = response.context['totals']
        rows = response.context['rows']
        self.assertEqual(totals['loans'], sum(r['loans'] for r in rows))
        self.assertEqual(totals['loan_portfolio'], sum(r['loan_portfolio'] for r in rows))
        self.assertEqual(totals['savings_portfolio'], Decimal('7500.00'))

    def test_excel_export(self):
        response = self.client.get(reverse(URL) + '?export=excel')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])


class OfficerSnapshotScopingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='OS002')
        cls.other_branch = make_branch(name='OS002 Other', code='OS002B')
        cls.staff_a = make_user(cls.branch, role='staff', email='osa_staff@test.com')
        cls.staff_b = make_user(cls.branch, role='staff', email='osb_staff@test.com')
        cls.staff_other = make_user(cls.other_branch, role='staff', email='oso_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='osa_mgr@test.com')
        cls.hr = make_user(cls.branch, role='hr', email='osa_hr@test.com')
        cls.director = make_user(cls.branch, role='director', email='osa_dir@test.com')
        # Clients assigned straight to the manager and to HR, not to any staff
        cls.mgr_client = make_client(cls.branch, cls.manager, email='osa_mc@test.com')
        cls.hr_client = make_client(cls.branch, cls.hr, email='osa_hc@test.com')

    def test_staff_sees_only_own_row_even_with_param_tampering(self):
        self.client.force_login(self.staff_a)
        response = self.client.get(reverse(URL) + f'?staff={self.staff_b.id}')
        self.assertEqual([r['officer'] for r in response.context['rows']], [self.staff_a])
        self.assertIsNone(response.context['staff_options'])

    def test_manager_sees_own_branch_staff_but_not_other_branch(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse(URL))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.staff_a, officers)
        self.assertIn(self.staff_b, officers)
        self.assertNotIn(self.staff_other, officers)

    def test_manager_and_hr_with_direct_clients_appear(self):
        self.client.force_login(self.director)
        response = self.client.get(reverse(URL))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.manager, officers)
        self.assertIn(self.hr, officers)
        self.assertEqual(_row_for(response, self.manager)['clients'], 1)
        self.assertEqual(_row_for(response, self.hr)['clients'], 1)

    def test_director_can_filter_by_branch(self):
        self.client.force_login(self.director)
        response = self.client.get(reverse(URL) + f'?branch={self.other_branch.id}')
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.staff_other, officers)
        self.assertNotIn(self.staff_a, officers)

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(reverse(URL)).status_code, 302)
