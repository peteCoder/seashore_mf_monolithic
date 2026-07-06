"""
Tests for /savings/transactions/: the branch/date/search filters, the
exposed `type` filter, the accurate filtered-count, and querystring-preserving
pagination (regression coverage for the bug where paging dropped `type`).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import SavingsAccount, SavingsDepositPosting, SavingsWithdrawalPosting
from core.tests.factories import make_branch, make_user, make_client, make_savings_product


class TestSavingsTransactionListFilters(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='STX Branch A', code='STXA001')
        cls.branch_b = make_branch(name='STX Branch B', code='STXB001')
        cls.admin = make_user(cls.branch_a, role='admin', email='stx_admin@test.com')
        staff_a = make_user(cls.branch_a, role='staff', email='stx_staff_a@test.com')
        client_a = make_client(cls.branch_a, staff_a, email='stx_client_a@test.com')
        product = make_savings_product(code='STXP001')

        account_a = SavingsAccount.objects.create(
            client=client_a, branch=cls.branch_a, savings_product=product, status='active',
        )

        # 2 deposits, 1 withdrawal, all in branch A
        for i in range(2):
            SavingsDepositPosting.objects.create(
                savings_account=account_a, amount=Decimal('1000.00'),
                payment_date=date(2026, 1, 10), submitted_by=staff_a,
            )
        SavingsWithdrawalPosting.objects.create(
            savings_account=account_a, amount=Decimal('500.00'),
            withdrawal_date=date(2026, 1, 12), submitted_by=staff_a,
        )

    def test_type_filter_shows_only_deposits(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_transaction_list'), {'type': 'deposit'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 2)

    def test_type_filter_shows_only_withdrawals(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_transaction_list'), {'type': 'withdrawal'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)

    def test_branch_filter_excludes_other_branch(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_transaction_list'), {'branch': self.branch_b.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 0)

    def test_pagination_preserves_type_filter(self):
        """
        Regression test: pagination links previously dropped `type`, so paging
        while `type=deposit` was active would silently fall back to the
        combined (all) list. The `{% querystring %}` fix must keep `type` in
        every pagination href.
        """
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_transaction_list'), {'type': 'deposit'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('type=deposit', content)
