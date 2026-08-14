"""
Tests for the /loans/repayment-tracker/ due-date filter (date_from/date_to).

The filter narrows every tab's rows down to installments due within the
chosen range, and — since each tab's summary totals are computed directly
from those same (now-filtered) querysets — the displayed amounts follow
automatically without any separate calculation to keep in sync.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestRepaymentTrackerDateFilter(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='DateFilter Branch', code='RTD001')
        cls.admin = make_user(cls.branch, role='admin', email='rtd_admin@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='rtd_mgr@test.com')
        staff = make_user(cls.branch, role='staff', email='rtd_staff@test.com')
        client_obj = make_client(cls.branch, staff, email='rtd_client@test.com')
        product = make_loan_product(code='RTDP001')

        today = timezone.localdate()

        def _make_overdue_row(days_overdue, amount):
            loan = Loan.objects.create(
                client=client_obj, loan_product=product, branch=cls.branch,
                principal_amount=Decimal('100000.00'), duration_months=6,
                disbursement_method='cash', created_by=staff,
                purpose='Business', status='active',
                outstanding_balance=amount,
            )
            LoanRepaymentSchedule.objects.create(
                loan=loan, installment_number=1,
                due_date=today - timedelta(days=days_overdue),
                principal_amount=amount * Decimal('0.8'),
                interest_amount=amount * Decimal('0.2'),
                total_amount=amount, outstanding_amount=amount,
                status='overdue',
            )
            return loan

        # Two overdue rows, 20 days apart, distinct amounts so a date-range
        # filter that isolates one is easy to verify against the total.
        cls.old_loan   = _make_overdue_row(days_overdue=25, amount=Decimal('10000.00'))
        cls.recent_loan = _make_overdue_row(days_overdue=5,  amount=Decimal('7000.00'))

    def test_no_filter_shows_both_rows_and_combined_total(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        self.assertEqual(response.context['overdue_summary']['count'], 2)
        self.assertEqual(response.context['overdue_summary']['outstanding'], Decimal('17000.00'))

    def test_date_range_narrows_rows_and_the_total_amount_shown(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        response = self.client.get(reverse('core:loan_repayment_tracker'), {
            'date_from': (today - timedelta(days=10)).isoformat(),
            'date_to':   today.isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        # Only the 5-days-overdue row falls in this range.
        self.assertEqual(response.context['overdue_summary']['count'], 1)
        self.assertEqual(response.context['overdue_summary']['outstanding'], Decimal('7000.00'))
        self.assertEqual(list(response.context['overdue_rows']), [
            LoanRepaymentSchedule.objects.get(loan=self.recent_loan)
        ])

    def test_date_from_only_is_a_lower_bound(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        response = self.client.get(reverse('core:loan_repayment_tracker'), {
            'date_from': (today - timedelta(days=10)).isoformat(),
        })
        self.assertEqual(response.context['overdue_summary']['count'], 1)
        self.assertEqual(response.context['overdue_summary']['outstanding'], Decimal('7000.00'))

    def test_invalid_date_is_ignored_not_a_crash(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'), {
            'date_from': 'not-a-date',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['date_from'])
        # Falls back to unfiltered behaviour rather than erroring out.
        self.assertEqual(response.context['overdue_summary']['count'], 2)

    def test_date_inputs_render_for_a_branch_scoped_manager(self):
        """
        The date filter must be usable even for roles that can't see the
        branch dropdown (it's no longer nested inside the
        can_view_all_branches block).
        """
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        content = response.content.decode()
        self.assertNotIn('name="branch"', content)
        self.assertIn('name="date_from"', content)
        self.assertIn('name="date_to"', content)

    def test_date_filter_persists_across_tab_links(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        response = self.client.get(reverse('core:loan_repayment_tracker'), {
            'date_from': (today - timedelta(days=10)).isoformat(),
            'date_to':   today.isoformat(),
        })
        content = response.content.decode()
        self.assertIn(f"date_from={(today - timedelta(days=10)).isoformat()}", content)
        self.assertIn(f"date_to={today.isoformat()}", content)
