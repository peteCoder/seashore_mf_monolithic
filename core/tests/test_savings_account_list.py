"""
Tests for /savings/: the filter form actually rendering (regression for a
context-key bug where the view passed `form` but the template read
`search_form`, silently hiding every filter widget), the renamed columns,
the per-row Post/Withdraw actions, the filtered-count line, and
querystring-preserving pagination.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.models import SavingsAccount
from core.tests.factories import make_branch, make_user, make_client, make_savings_product


class TestSavingsAccountListFilters(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='SAL Branch A', code='SALA001')
        cls.branch_b = make_branch(name='SAL Branch B', code='SALB001')
        cls.admin = make_user(cls.branch_a, role='admin', email='sal_admin@test.com')
        staff_a = make_user(cls.branch_a, role='staff', email='sal_staff_a@test.com')
        cls.client_a = make_client(cls.branch_a, staff_a, email='sal_client_a@test.com')
        client_b = make_client(cls.branch_b, staff_a, email='sal_client_b@test.com')
        cls.product = make_savings_product(code='SALP001')

        cls.account_active = SavingsAccount.objects.create(
            client=cls.client_a, branch=cls.branch_a, savings_product=cls.product,
            status='active', date_opened=date(2026, 1, 10),
        )
        cls.account_pending = SavingsAccount.objects.create(
            client=client_b, branch=cls.branch_b, savings_product=cls.product,
            status='pending', date_opened=date(2026, 3, 1),
        )

    def test_filter_form_renders(self):
        """
        Regression test: the view previously put the form in context as
        `form`, but the template read `search_form` — so the widgets never
        rendered. Confirm the actual <select>/<input> filter controls appear.
        """
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_account_list'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="search"', content)
        self.assertIn('name="status"', content)
        self.assertIn('name="branch"', content)
        self.assertIn('name="savings_product"', content)
        self.assertIn('name="date_from"', content)
        self.assertIn('name="date_to"', content)

    def test_branch_and_status_filter_narrow_results(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_account_list'), {
            'branch': self.branch_a.id, 'status': 'active',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total_accounts'], 1)

    def test_date_filter_narrows_results(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_account_list'), {
            'date_from': '2026-01-01', 'date_to': '2026-01-31',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total_accounts'], 1)

    def test_columns_and_actions_rendered(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_account_list'))
        content = response.content.decode()
        self.assertIn('Savings Details', content)
        self.assertIn('Amount in Account', content)
        self.assertNotIn('Interest Earned', content)

        self.assertIn(reverse('core:savings_account_detail', args=[self.account_active.id]), content)
        self.assertIn(reverse('core:savings_deposit_post_for_account', args=[self.account_active.id]), content)
        self.assertIn(reverse('core:savings_withdrawal_post_for_account', args=[self.account_active.id]), content)

    def test_post_withdraw_actions_hidden_for_non_active_account(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_account_list'))
        content = response.content.decode()
        self.assertNotIn(reverse('core:savings_deposit_post_for_account', args=[self.account_pending.id]), content)
        self.assertNotIn(reverse('core:savings_withdrawal_post_for_account', args=[self.account_pending.id]), content)

    def test_pagination_preserves_filters(self):
        for i in range(25):
            SavingsAccount.objects.create(
                client=self.client_a, branch=self.branch_a, savings_product=self.product,
                status='active', date_opened=date(2026, 1, 15),
            )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:savings_account_list'), {
            'branch': self.branch_a.id, 'status': 'active', 'page': '2',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total_accounts'], 26)
        content = response.content.decode()
        self.assertIn(f'branch={self.branch_a.id}', content)
        self.assertIn('status=active', content)
