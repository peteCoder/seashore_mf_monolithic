"""
Tests for the "All Active Loans" tab on /loans/repayment-tracker/.

This tab exists because loans that are current or ahead of schedule have
their next unpaid installment beyond the other tabs' 30-day lookahead —
so they never appear in Overdue/Today/Week/Month, even though they're
active and outstanding. See test_repayment_tracker_old_clients_bug.py for
the investigation that found this (it looked like a data bug at first;
it's actually the tracker's fixed-window design).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestAllActiveLoansTab(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='AAL Branch A', code='AALA001')
        cls.branch_b = make_branch(name='AAL Branch B', code='AALB001')
        cls.admin = make_user(cls.branch_a, role='admin', email='aal_admin@test.com')
        cls.manager_a = make_user(cls.branch_a, role='manager', email='aal_mgr_a@test.com')
        client_a = make_client(cls.branch_a, cls.admin, email='aal_client_a@test.com')
        client_b = make_client(cls.branch_b, cls.admin, email='aal_client_b@test.com')
        product = make_loan_product(code='AALP001')

        today = timezone.localdate()

        # Ahead-of-schedule loan in branch A: next due date is 45 days out,
        # invisible to the other 4 tabs, but must appear in "All Active Loans".
        cls.current_loan = Loan.objects.create(
            client=client_a, loan_product=product, branch=cls.branch_a,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=cls.admin,
            purpose='Business', status='active',
            outstanding_balance=Decimal('50000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.current_loan, installment_number=1, due_date=today + timedelta(days=45),
            principal_amount=Decimal('8000.00'), interest_amount=Decimal('2000.00'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
        )

        # Loan in branch B, for branch-filter test
        cls.branch_b_loan = Loan.objects.create(
            client=client_b, loan_product=product, branch=cls.branch_b,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=cls.admin,
            purpose='Business', status='active',
            outstanding_balance=Decimal('50000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.branch_b_loan, installment_number=1, due_date=today + timedelta(days=45),
            principal_amount=Decimal('8000.00'), interest_amount=Decimal('2000.00'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
        )

    def test_ahead_of_schedule_loan_missing_from_other_tabs(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        overdue_ids = {r.loan_id for r in response.context['overdue_rows']}
        today_ids = {r.loan_id for r in response.context['due_today_rows']}
        week_ids = {r.loan_id for r in response.context['due_week_rows']}
        month_ids = {r.loan_id for r in response.context['due_month_rows']}
        all_four = overdue_ids | today_ids | week_ids | month_ids
        self.assertNotIn(self.current_loan.id, all_four)

    def test_ahead_of_schedule_loan_appears_in_all_active_loans_tab(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'), {'tab': 'all'})
        self.assertEqual(response.status_code, 200)
        loan_ids = {l.id for l in response.context['all_active_loans']}
        self.assertIn(self.current_loan.id, loan_ids)
        self.assertIn(self.branch_b_loan.id, loan_ids)

    def test_branch_filter_narrows_all_active_loans_tab(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('core:loan_repayment_tracker'),
            {'tab': 'all', 'branch': self.branch_a.id},
        )
        loan_ids = {l.id for l in response.context['all_active_loans']}
        self.assertIn(self.current_loan.id, loan_ids)
        self.assertNotIn(self.branch_b_loan.id, loan_ids)
        self.assertEqual(response.context['all_active_loans_count'], 1)

    def test_manager_only_sees_own_branch_in_all_active_loans_tab(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:loan_repayment_tracker'), {'tab': 'all'})
        loan_ids = {l.id for l in response.context['all_active_loans']}
        self.assertIn(self.current_loan.id, loan_ids)
        self.assertNotIn(self.branch_b_loan.id, loan_ids)

    def test_all_tab_renders_arms_paid_and_repay_link(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'), {'tab': 'all'})
        content = response.content.decode()
        self.assertIn('0/1', content)  # paid_installments/total_installments
        self.assertIn(reverse('core:loan_repayment_post_for_loan', args=[self.current_loan.id]), content)

    def test_all_tab_pagination_preserves_branch_and_tab(self):
        for i in range(25):
            loan = Loan.objects.create(
                client=self.current_loan.client, loan_product=self.current_loan.loan_product,
                branch=self.branch_a, principal_amount=Decimal('50000.00'), duration_months=3,
                disbursement_method='cash', created_by=self.admin,
                purpose='Business', status='active', outstanding_balance=Decimal('20000.00'),
            )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('core:loan_repayment_tracker'),
            {'tab': 'all', 'branch': self.branch_a.id, 'all_page': '2'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['all_active_loans'].number, 2)
        content = response.content.decode()
        self.assertIn(f'branch={self.branch_a.id}', content)
        self.assertIn('tab=all', content)
