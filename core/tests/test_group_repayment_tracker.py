"""
Tests for /groups/repayment-tracker/ — groups meeting today, scoped by role.

Scoping is deliberately custom (not checker.can_view_all_branches()):
  - admin / director: all branches
  - hr / manager:      own branch only
  - staff:             own branch AND must be the group's loan_officer
"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ClientGroup
from core.tests.factories import make_branch, make_user


def _today_name():
    return timezone.localdate().strftime('%A').lower()


def _other_day():
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    today = _today_name()
    return next(d for d in days if d != today)


class TestGroupRepaymentTracker(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='GRT Branch A', code='GRTA001')
        cls.branch_b = make_branch(name='GRT Branch B', code='GRTB001')

        cls.admin = make_user(cls.branch_a, role='admin', email='grt_admin@test.com')
        cls.director = make_user(cls.branch_a, role='director', email='grt_dir@test.com')
        cls.hr = make_user(cls.branch_a, role='hr', email='grt_hr@test.com')
        cls.manager_a = make_user(cls.branch_a, role='manager', email='grt_mgr_a@test.com')
        cls.staff_a1 = make_user(cls.branch_a, role='staff', email='grt_staff_a1@test.com')
        cls.staff_a2 = make_user(cls.branch_a, role='staff', email='grt_staff_a2@test.com')

        today_name = _today_name()
        other_day = _other_day()

        # Branch A, meets today, staff_a1 in charge
        cls.group_a1 = ClientGroup.objects.create(
            name='Group A1', branch=cls.branch_a, loan_officer=cls.staff_a1,
            meeting_day=today_name, status='active',
        )
        # Branch A, meets today, staff_a2 in charge
        cls.group_a2 = ClientGroup.objects.create(
            name='Group A2', branch=cls.branch_a, loan_officer=cls.staff_a2,
            meeting_day=today_name, status='active',
        )
        # Branch A, does NOT meet today
        ClientGroup.objects.create(
            name='Group A3 Other Day', branch=cls.branch_a, loan_officer=cls.staff_a1,
            meeting_day=other_day, status='active',
        )
        # Branch A, meets today but inactive
        ClientGroup.objects.create(
            name='Group A4 Inactive', branch=cls.branch_a, loan_officer=cls.staff_a1,
            meeting_day=today_name, status='inactive',
        )
        # Branch B, meets today
        cls.group_b1 = ClientGroup.objects.create(
            name='Group B1', branch=cls.branch_b, meeting_day=today_name, status='active',
        )

    def test_admin_sees_all_branches(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 3)
        names = {g.name for g in response.context['groups']}
        self.assertEqual(names, {'Group A1', 'Group A2', 'Group B1'})

    def test_director_sees_all_branches(self):
        self.client.force_login(self.director)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 3)

    def test_hr_scoped_to_own_branch_only(self):
        self.client.force_login(self.hr)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 2)
        names = {g.name for g in response.context['groups']}
        self.assertEqual(names, {'Group A1', 'Group A2'})

    def test_manager_scoped_to_own_branch_only(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 2)

    def test_staff_sees_only_own_groups(self):
        self.client.force_login(self.staff_a1)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 1)
        names = {g.name for g in response.context['groups']}
        self.assertEqual(names, {'Group A1'})

    def test_inactive_and_wrong_day_groups_excluded(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        names = {g.name for g in response.context['groups']}
        self.assertNotIn('Group A3 Other Day', names)
        self.assertNotIn('Group A4 Inactive', names)

    def test_collect_payment_link_points_to_combined_collection(self):
        """
        The tracker's "Collect Payment" button must lead to the combined
        loan-repayment + savings collection flow, not the loans-only one.
        """
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:group_repayment_tracker'))
        content = response.content.decode()
        self.assertIn(reverse('core:group_combined_collection', args=[self.group_a1.id]), content)
        self.assertNotIn(reverse('core:group_collection_detail', args=[self.group_a1.id]), content)


class TestGroupRepaymentTrackerDashboardAlert(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='GRTD Branch A', code='GRTDA001')
        cls.branch_b = make_branch(name='GRTD Branch B', code='GRTDB001')
        cls.manager_a = make_user(cls.branch_a, role='manager', email='grtd_mgr_a@test.com')

        today_name = _today_name()
        ClientGroup.objects.create(
            name='GRTD Group A', branch=cls.branch_a, meeting_day=today_name, status='active',
        )
        ClientGroup.objects.create(
            name='GRTD Group B', branch=cls.branch_b, meeting_day=today_name, status='active',
        )

    def test_dashboard_alert_scoped_to_manager_branch(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['groups_meeting_today_count'], 1)
        action_urls = [a['action_url'] for a in response.context['alerts']]
        self.assertIn(reverse('core:group_repayment_tracker'), action_urls)
