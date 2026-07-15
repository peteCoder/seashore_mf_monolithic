"""
End-to-end regression test for the reported bug: "Repayment tracker only
showing the newly disbursed client only excluding the old clients".

Confirms the full chain: a loan with no LoanRepaymentSchedule rows is
invisible on /loans/repayment-tracker/ even though it's overdue and owes
money, and running `backfill_missing_loan_schedules` makes it appear.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan
from core.tests.factories import make_branch, make_user, make_client, make_loan_product
from io import StringIO


class TestRepaymentTrackerOldClientsBug(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='RTOC001')
        cls.admin = make_user(cls.branch, role='admin', email='rtoc_admin@test.com')
        client_obj = make_client(cls.branch, cls.admin, email='rtoc_client@test.com')
        product = make_loan_product(code='RTOCP001')

        cls.old_loan = Loan.objects.create(
            client=client_obj, loan_product=product, branch=cls.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=cls.admin,
            purpose='Business', status='approved',
        )
        # Mirrors what Loan.disburse() sets on the loan itself (dates,
        # status, balances) — it's specifically the LoanRepaymentSchedule
        # rows that are missing, which is the exact shape of the real bug.
        first_repayment = (timezone.now() - timedelta(days=200)).date()
        Loan.objects.filter(id=cls.old_loan.id).update(
            status='overdue',
            disbursement_date=timezone.now() - timedelta(days=200),
            first_repayment_date=first_repayment,
            outstanding_balance=cls.old_loan.total_repayment,
            number_of_installments=0,
        )

    def test_old_loan_with_no_schedule_is_invisible_to_tracker(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['overdue_summary']['count'], 0)
        # It should show up in the "no schedule" warning list instead
        no_schedule_ids = [l.id for l in response.context['loans_no_schedule']]
        self.assertIn(self.old_loan.id, no_schedule_ids)

    def test_backfill_makes_old_loan_visible_in_tracker(self):
        call_command('backfill_missing_loan_schedules', '--commit', stdout=StringIO())

        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:loan_repayment_tracker'))
        self.assertEqual(response.status_code, 200)

        overdue_loan_ids = {row.loan_id for row in response.context['overdue_rows']}
        self.assertIn(self.old_loan.id, overdue_loan_ids)
        no_schedule_ids = [l.id for l in response.context['loans_no_schedule']]
        self.assertNotIn(self.old_loan.id, no_schedule_ids)
