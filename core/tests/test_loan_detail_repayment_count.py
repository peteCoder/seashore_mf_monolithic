"""
Tests for the "Successful Repayments" count shown on /loans/<id>/, derived
from LoanRepaymentSchedule.computed_status rather than the stale stored
`status` field.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestLoanDetailRepaymentCount(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='LDC001')
        cls.staff = make_user(cls.branch, role='staff', email='ldc_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='ldc_client@test.com')
        cls.product = make_loan_product(code='LDCP001')

        cls.loan = Loan.objects.create(
            client=cls.client_obj, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('100000.00'), duration_months=4,
            disbursement_method='cash', created_by=cls.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('30000.00'),
        )

        today = timezone.localdate()

        # Installment 1: fully paid
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=1, due_date=today - timedelta(days=60),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'), amount_paid=Decimal('25000.00'),
        )
        # Installment 2: fully paid
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=2, due_date=today - timedelta(days=30),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'), amount_paid=Decimal('25000.00'),
        )
        # Installment 3: partially paid — NOT successful
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=3, due_date=today - timedelta(days=5),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'), amount_paid=Decimal('10000.00'),
        )
        # Installment 4: untouched, upcoming — NOT successful
        LoanRepaymentSchedule.objects.create(
            loan=cls.loan, installment_number=4, due_date=today + timedelta(days=25),
            principal_amount=Decimal('20000.00'), interest_amount=Decimal('5000.00'),
            total_amount=Decimal('25000.00'),
        )

    def test_paid_installments_count_context(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['paid_installments_count'], 2)
        self.assertEqual(response.context['summary']['total_installments'], 4)

    def test_paid_installments_count_rendered(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        content = response.content.decode()
        self.assertIn('2/4 paid', content)
        self.assertIn('Arms Paid', content)
