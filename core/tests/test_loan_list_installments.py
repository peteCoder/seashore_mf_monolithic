"""
Tests for the /loans/ list "Arms Paid" / "Amount Paid" columns and the
Repay row action, plus the matching "Arms Paid" / "Amount Paid" stat cards
on /loans/<id>/.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestLoanListInstallmentColumns(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='LLI001')
        cls.staff = make_user(cls.branch, role='staff', email='lli_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='lli_client@test.com')
        cls.product = make_loan_product(code='LLIP001')

        cls.loan = Loan.objects.create(
            client=cls.client_obj, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('100000.00'), duration_months=4,
            disbursement_method='cash', created_by=cls.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('30000.00'), amount_paid=Decimal('50000.00'),
        )

        today = timezone.localdate()
        # 2 paid, 1 partial, 1 untouched
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=1, due_date=today - timedelta(days=60),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'), amount_paid=Decimal('25000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=2, due_date=today - timedelta(days=30),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'), amount_paid=Decimal('25000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=3, due_date=today - timedelta(days=5),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'), amount_paid=Decimal('10000.00'),
        )
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=4, due_date=today + timedelta(days=25),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'),
        )

    def test_list_view_annotates_installment_counts(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_list'))
        self.assertEqual(response.status_code, 200)
        loan = response.context['loans'][0]
        self.assertEqual(loan.total_installments, 4)
        self.assertEqual(loan.paid_installments, 2)

    def test_list_view_renders_arms_paid_amount_paid_and_repay_link(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_list'))
        content = response.content.decode()
        self.assertIn('2/4', content)
        self.assertIn(reverse('core:loan_repayment_post_for_loan', args=[self.loan.id]), content)

    def test_detail_view_stat_cards_render(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Amount Paid', content)
        self.assertIn('Arms Paid', content)
        self.assertIn('2/4', content)
