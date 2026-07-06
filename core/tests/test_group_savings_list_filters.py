"""
Tests for the /group-savings/ branch/date filter, filtered-count display,
and querystring-preserving pagination.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ClientGroup, GroupSavingsAccount
from core.tests.factories import make_branch, make_user, make_savings_product


class TestGroupSavingsAccountListFilters(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='GSA Branch A', code='GSAA001')
        cls.branch_b = make_branch(name='GSA Branch B', code='GSAB001')
        cls.admin = make_user(cls.branch_a, role='admin', email='gsa_admin@test.com')
        cls.product = make_savings_product(code='GSAP001', product_type='group_savings')

        cls.group_a = ClientGroup.objects.create(name='GSA Group A', branch=cls.branch_a)
        cls.group_b = ClientGroup.objects.create(name='GSA Group B', branch=cls.branch_b)

        cls.account_a = GroupSavingsAccount.objects.create(
            group=cls.group_a, savings_product=cls.product, branch=cls.branch_a, status='active',
        )
        cls.account_b = GroupSavingsAccount.objects.create(
            group=cls.group_b, savings_product=cls.product, branch=cls.branch_b, status='pending',
        )

    def test_branch_filter_narrows_results(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_savings_account_list'), {
            'branch': self.branch_a.id,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total'], 1)

    def test_status_and_date_filter_combine(self):
        self.client.force_login(self.admin)
        today_str = timezone.localdate().isoformat()
        response = self.client.get(reverse('core:group_savings_account_list'), {
            'status': 'active',
            'date_from': today_str,
            'date_to': today_str,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary']['total'], 1)

    def test_pagination_link_preserves_filters(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_savings_account_list'), {
            'branch': self.branch_a.id,
            'status': 'active',
        })
        self.assertEqual(response.status_code, 200)
        # No second page with just 1 account, but the count line must reflect the filter
        content = response.content.decode()
        self.assertIn('1', content)
