"""
Tests for the client-list date filter, filtered-count display, and
querystring-preserving pagination.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.tests.factories import make_branch, make_user, make_client


class TestClientListDateFilterAndPagination(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='James Watt', code='JW001')
        cls.other_branch = make_branch(name='Other Branch', code='OB001')
        cls.staff = make_user(cls.branch, role='admin', email='jw_admin@test.com')

        # 5 clients registered inside Jan 2026 window, active+approved
        for i in range(5):
            make_client(
                cls.branch, cls.staff,
                email=f'in_range_{i}@test.com',
                registration_date=date(2026, 1, 10),
            )
        # 3 clients registered outside window
        for i in range(3):
            make_client(
                cls.branch, cls.staff,
                email=f'out_range_{i}@test.com',
                registration_date=date(2026, 3, 1),
            )
        # 2 clients in range but different branch (should be excluded by branch filter)
        for i in range(2):
            make_client(
                cls.other_branch, cls.staff,
                email=f'other_branch_{i}@test.com',
                registration_date=date(2026, 1, 15),
            )

    def test_date_filter_narrows_results(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_list'), {
            'date_from': '2026-01-01',
            'date_to': '2026-01-30',
            'branch': self.branch.id,
            'status': 'active',
            'approval_status': 'approved',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 5)

    def test_total_count_reflects_full_filtered_set_on_page_2(self):
        # Create enough extra in-range clients to force a second page (25/page)
        for i in range(25):
            make_client(
                self.branch, self.staff,
                email=f'bulk_{i}@test.com',
                registration_date=date(2026, 1, 20),
            )
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_list'), {
            'date_from': '2026-01-01',
            'date_to': '2026-01-30',
            'branch': self.branch.id,
            'status': 'active',
            'approval_status': 'approved',
            'page': '2',
        })
        self.assertEqual(response.status_code, 200)
        # 5 original in-range + 25 bulk = 30 total matching filters
        self.assertEqual(response.context['total_count'], 30)
        self.assertEqual(response.context['clients'].number, 2)

        content = response.content.decode()
        # Pagination links must retain every active filter, not just `page`
        self.assertIn('date_from=2026-01-01', content)
        self.assertIn('date_to=2026-01-30', content)
        self.assertIn(f'branch={self.branch.id}', content)
        self.assertIn('status=active', content)
        self.assertIn('approval_status=approved', content)
        # And the filtered count line should render 30
        self.assertIn('30', content)

    def test_clear_filters_link_still_shows_all(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 10)
