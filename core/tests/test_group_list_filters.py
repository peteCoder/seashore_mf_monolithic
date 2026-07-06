"""
Tests for the /groups/ date filter, filtered-count display, and
querystring-preserving pagination.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.models import ClientGroup
from core.tests.factories import make_branch, make_user


class TestGroupListDateFilterAndPagination(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='Group Branch', code='GB001')
        cls.admin = make_user(cls.branch, role='admin', email='gl_admin@test.com')

        for i in range(3):
            ClientGroup.objects.create(
                name=f'In Range Group {i}', branch=cls.branch,
                registration_date=date(2026, 1, 10),
            )
        for i in range(2):
            ClientGroup.objects.create(
                name=f'Out Range Group {i}', branch=cls.branch,
                registration_date=date(2026, 3, 1),
            )
        ClientGroup.objects.create(
            name='Monday Group', branch=cls.branch, meeting_day='monday',
        )
        ClientGroup.objects.create(
            name='Friday Group', branch=cls.branch, meeting_day='friday',
        )

    def test_date_filter_narrows_results(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_list'), {
            'date_from': '2026-01-01',
            'date_to': '2026-01-30',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 3)

    def test_meeting_day_filter_narrows_results(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_list'), {'meeting_day': 'monday'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)
        names = {g.name for g in response.context['groups']}
        self.assertEqual(names, {'Monday Group'})

    def test_pagination_preserves_filters(self):
        for i in range(25):
            ClientGroup.objects.create(
                name=f'Bulk Group {i}', branch=self.branch, registration_date=date(2026, 1, 15),
            )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_list'), {
            'date_from': '2026-01-01',
            'date_to': '2026-01-30',
            'branch': self.branch.id,
            'page': '2',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 28)
        content = response.content.decode()
        self.assertIn('date_from=2026-01-01', content)
        self.assertIn('date_to=2026-01-30', content)
        self.assertIn(f'branch={self.branch.id}', content)
