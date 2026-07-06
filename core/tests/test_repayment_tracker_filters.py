"""
Tests for the /loans/repayment-tracker/ branch filter and filtered result count.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestRepaymentTrackerBranchFilter(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='Branch A', code='RTA001')
        cls.branch_b = make_branch(name='Branch B', code='RTB001')
        cls.admin = make_user(cls.branch_a, role='admin', email='rt_admin@test.com')
        cls.manager_a = make_user(cls.branch_a, role='manager', email='rt_mgr_a@test.com')

        staff_a = make_user(cls.branch_a, role='staff', email='rt_staff_a@test.com')
        staff_b = make_user(cls.branch_b, role='staff', email='rt_staff_b@test.com')
        client_a = make_client(cls.branch_a, staff_a, email='rt_client_a@test.com')
        client_b = make_client(cls.branch_b, staff_b, email='rt_client_b@test.com')
        product = make_loan_product(code='RTP001')

        today = timezone.localdate()

        cls.loan_a = Loan.objects.create(
            client=client_a, loan_product=product, branch=cls.branch_a,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=staff_a,
            purpose='Business', status='active',
            outstanding_balance=Decimal('50000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan_a, installment_number=1,
            due_date=today - timedelta(days=5),
            principal_amount=Decimal('8000.00'), interest_amount=Decimal('2000.00'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
            status='overdue',
        )

        cls.loan_b = Loan.objects.create(
            client=client_b, loan_product=product, branch=cls.branch_b,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=staff_b,
            purpose='Business', status='active',
            outstanding_balance=Decimal('50000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan_b, installment_number=1,
            due_date=today - timedelta(days=3),
            principal_amount=Decimal('8000.00'), interest_amount=Decimal('2000.00'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
            status='overdue',
        )

    def test_admin_sees_both_branches_unfiltered(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['overdue_summary']['count'], 2)
        self.assertEqual(response.context['active_tab_count'], 2)
        self.assertIsNone(response.context['selected_branch'])

    def test_branch_filter_box_renders_for_admin(self):
        """
        Regression test: the filter box is gated by `{% if checker.can_view_all_branches %}`
        in the template, so `checker` must actually be in the view's context —
        it was silently missing before, which hid the filter for every role.
        """
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        content = response.content.decode()
        self.assertIn('name="branch"', content)
        self.assertIn(self.branch_a.name, content)
        self.assertIn(self.branch_b.name, content)

    def test_branch_filter_box_hidden_for_manager(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        content = response.content.decode()
        self.assertNotIn('name="branch"', content)

    def test_admin_branch_filter_narrows_to_one_branch(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'), {
            'branch': self.branch_a.id,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['overdue_summary']['count'], 1)
        self.assertEqual(response.context['active_tab_count'], 1)
        self.assertEqual(response.context['selected_branch'], self.branch_a)

        content = response.content.decode()
        # Tab links must retain the branch selection, not just switch tabs
        self.assertIn(f'branch={self.branch_a.id}', content)

    def test_manager_cannot_pick_branch_stays_scoped_to_own(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:loan_repayment_tracker'), {
            'branch': self.branch_b.id,
        })
        self.assertEqual(response.status_code, 200)
        # Manager is locked to their own branch regardless of the branch param
        self.assertEqual(response.context['overdue_summary']['count'], 1)
        self.assertIsNone(response.context['selected_branch'])
