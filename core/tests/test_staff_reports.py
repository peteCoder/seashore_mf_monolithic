"""
Tests for the six Staff Reports (Loan, Staff Savings Portfolio,
Disbursement, Registration, Unions, Overdue) and the dashboard's Client
Overview chart.

Unlike the Financial Reports (report_trial_balance etc., Manager+ only),
these are staff-accessible — but staff must only ever see their OWN data,
never a picker. That scoping is the highest-risk part of this feature, so
it's what most of these tests focus on.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Client, ClientGroup, Loan, SavingsAccount
from core.tests.factories import (
    make_branch, make_user, make_client, make_loan_product, make_savings_product,
)

REPORT_URLS = [
    'core:report_loans',
    'core:report_staff_savings_portfolio',
    'core:report_disbursement',
    'core:report_registration',
    'core:report_unions',
    'core:report_overdue_by_staff',
]


class StaffReportsAccessTests(TestCase):
    """Every role in CAN_VIEW_STAFF_REPORTS can load every report page."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR001')
        cls.staff = make_user(cls.branch, role='staff', email='sr_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='sr_mgr@test.com')
        cls.director = make_user(cls.branch, role='director', email='sr_dir@test.com')

    def test_staff_can_access_all_six_reports(self):
        self.client.force_login(self.staff)
        for name in REPORT_URLS:
            with self.subTest(report=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_manager_can_access_all_six_reports(self):
        self.client.force_login(self.manager)
        for name in REPORT_URLS:
            with self.subTest(report=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_director_can_access_all_six_reports(self):
        self.client.force_login(self.director)
        for name in REPORT_URLS:
            with self.subTest(report=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_anonymous_is_redirected_to_login(self):
        for name in REPORT_URLS:
            with self.subTest(report=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)


class StaffReportScopingTests(TestCase):
    """
    Staff must never see another staff member's data — no picker, and any
    ?staff=<other id> in the querystring is ignored, not honoured.
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR002')
        cls.branch_b = make_branch(name='SR002 Branch B', code='SR002B')
        cls.staff_a = make_user(cls.branch, role='staff', email='sra_staff@test.com')
        cls.staff_b = make_user(cls.branch, role='staff', email='srb_staff@test.com')
        cls.manager_a = make_user(cls.branch, role='manager', email='sra_mgr@test.com')
        cls.client_a = make_client(cls.branch, cls.staff_a, email='sra_client@test.com')
        cls.client_b = make_client(cls.branch, cls.staff_b, email='srb_client@test.com')
        cls.product = make_loan_product(code='SR002P')

        today = timezone.now()
        cls.loan_a = Loan.objects.create(
            client=cls.client_a, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('50000.00'), duration_months=3,
            disbursement_method='cash', created_by=cls.staff_a,
            purpose='Business', status='active',
            outstanding_balance=Decimal('40000.00'),
            disbursement_date=today,
        )
        cls.loan_b = Loan.objects.create(
            client=cls.client_b, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('75000.00'), duration_months=3,
            disbursement_method='cash', created_by=cls.staff_b,
            purpose='Business', status='active',
            outstanding_balance=Decimal('60000.00'),
            disbursement_date=today,
        )

    def test_staff_sees_only_own_loans_even_with_staff_param_tampering(self):
        self.client.force_login(self.staff_a)
        url = reverse('core:report_loans') + f'?staff={self.staff_b.id}'
        response = self.client.get(url)
        rows = response.context['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['officer'], self.staff_a)
        self.assertEqual(rows[0]['nol'], 1)
        self.assertEqual(rows[0]['principal'], Decimal('50000.00'))

    def test_staff_has_no_staff_picker(self):
        self.client.force_login(self.staff_a)
        response = self.client.get(reverse('core:report_loans'))
        self.assertIsNone(response.context['staff_options'])
        self.assertEqual(response.context['selected_staff'], self.staff_a)

    def test_manager_sees_both_staff_in_branch_by_default(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:report_loans'))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertEqual(officers, {self.staff_a, self.staff_b})

    def test_manager_can_filter_to_one_staff(self):
        self.client.force_login(self.manager_a)
        url = reverse('core:report_loans') + f'?staff={self.staff_b.id}'
        response = self.client.get(url)
        rows = response.context['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['officer'], self.staff_b)
        self.assertEqual(rows[0]['principal'], Decimal('75000.00'))


class ManagerWithDirectClientsTests(TestCase):
    """
    Some managers have clients assigned straight to them, not just via
    their staff (confirmed in production: 3 managers, 309 clients between
    them). Those portfolios must not vanish from these reports just because
    the manager isn't role='staff'.
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR007')
        cls.manager = make_user(cls.branch, role='manager', email='sr7_mgr@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='sr7_staff@test.com')
        # Client assigned directly to the MANAGER, not to any staff.
        cls.direct_client = make_client(cls.branch, cls.manager, email='sr7_direct@test.com')
        cls.product = make_loan_product(code='SR007P')
        cls.loan = Loan.objects.create(
            client=cls.direct_client, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('45000.00'), duration_months=3,
            disbursement_method='cash', created_by=cls.manager,
            purpose='Business', status='active',
            outstanding_balance=Decimal('35000.00'),
            disbursement_date=timezone.now(),
        )

    def test_manager_appears_in_own_branch_loan_report(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:report_loans'))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.manager, officers)
        self.assertIn(self.staff, officers)
        manager_row = next(r for r in response.context['rows'] if r['officer'] == self.manager)
        self.assertEqual(manager_row['nol'], 1)
        self.assertEqual(manager_row['principal'], Decimal('45000.00'))

    def test_manager_appears_in_staff_picker_dropdown(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:report_loans'))
        picker_ids = {u.id for u in response.context['staff_options']}
        self.assertIn(self.manager.id, picker_ids)

    def test_manager_with_direct_clients_appears_in_registration_report(self):
        self.direct_client.registration_date = timezone.now().date()
        self.direct_client.save(update_fields=['registration_date'])
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:report_registration'))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.manager, officers)


class HrWithDirectClientsTests(TestCase):
    """
    Not just managers — HR can have directly-assigned clients too (confirmed
    in production: one HR user, 2 clients). The fix is role-agnostic (any
    non-staff role with real attributed data gets included), so this should
    already pass with no further code changes — this test locks it in.
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR008')
        cls.hr = make_user(cls.branch, role='hr', email='sr8_hr@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='sr8_mgr@test.com')
        cls.direct_client = make_client(cls.branch, cls.hr, email='sr8_direct@test.com')
        cls.product = make_loan_product(code='SR008P')
        Loan.objects.create(
            client=cls.direct_client, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('20000.00'), duration_months=3,
            disbursement_method='cash', created_by=cls.hr,
            purpose='Business', status='active',
            outstanding_balance=Decimal('15000.00'),
            disbursement_date=timezone.now(),
        )

    def test_hr_appears_in_own_loan_report(self):
        self.client.force_login(self.hr)
        response = self.client.get(reverse('core:report_loans'))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.hr, officers)

    def test_hr_appears_when_manager_in_same_branch_views_report(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:report_loans'))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertIn(self.hr, officers)

    def test_admin_and_director_never_appear_without_assigned_data(self):
        """Admins (and directors) never have clients assigned to them in
        production — confirm they simply don't show up, since nothing
        singles them out; they're just staff role's complement that
        happens to have no attributed data."""
        director = make_user(self.branch, role='director', email='sr8_dir@test.com')
        self.client.force_login(director)
        response = self.client.get(reverse('core:report_loans'))
        officers = {r['officer'] for r in response.context['rows']}
        self.assertNotIn(director, officers)


class DisbursementReportTests(TestCase):
    """C (loan volume) + E (distinct client reach) combined on one report."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR003')
        cls.staff = make_user(cls.branch, role='staff', email='sr3_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='sr3_client@test.com')
        cls.product = make_loan_product(code='SR003P')

        today = timezone.now()
        # Same client, two loans disbursed in period -> 2 loans, 1 distinct client
        for i in range(2):
            Loan.objects.create(
                client=cls.client_obj, loan_product=cls.product, branch=cls.branch,
                principal_amount=Decimal('30000.00'), duration_months=3,
                disbursement_method='cash', created_by=cls.staff,
                purpose='Business', status='active',
                outstanding_balance=Decimal('20000.00'),
                disbursement_date=today,
            )

    def test_loan_count_vs_distinct_client_count(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:report_disbursement'))
        row = response.context['rows'][0]
        self.assertEqual(row['loans_disbursed'], 2)
        self.assertEqual(row['clients_disbursed'], 1)
        self.assertEqual(row['principal_disbursed'], Decimal('60000.00'))


class RegistrationReportTests(TestCase):
    """Attributed to Client.original_officer, not assigned_staff."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR004')
        cls.staff = make_user(cls.branch, role='staff', email='sr4_staff@test.com')
        cls.other_staff = make_user(cls.branch, role='staff', email='sr4_other@test.com')

    def test_registration_follows_original_officer_not_current_assignment(self):
        # registration_date has no model default (null=True, blank=True) — the
        # factory doesn't set it, so it must be passed explicitly here.
        client_obj = make_client(
            self.branch, self.staff, email='sr4_client@test.com',
            registration_date=timezone.now().date(),
        )
        # original_officer is set automatically to assigned_staff on first
        # save when blank (see Client.save()) — reassign afterwards so
        # assigned_staff != original_officer, and confirm the report follows
        # original_officer.
        client_obj.assigned_staff = self.other_staff
        client_obj.save(update_fields=['assigned_staff'])
        self.assertEqual(client_obj.original_officer, self.staff)

        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:report_registration'))
        row = response.context['rows'][0]
        self.assertEqual(row['officer'], self.staff)
        self.assertEqual(row['total'], 1)


class UnionsReportTests(TestCase):
    """ClientGroup rows, filtered by loan_officer + registration_date + branch."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR005')
        cls.staff = make_user(cls.branch, role='staff', email='sr5_staff@test.com')
        cls.other_staff = make_user(cls.branch, role='staff', email='sr5_other@test.com')
        today = timezone.now().date()
        cls.group = ClientGroup.objects.create(
            name='Test Union', branch=cls.branch, loan_officer=cls.staff,
            status='active', registration_date=today,
            total_members=10, active_members=8,
            total_savings=Decimal('100000.00'), total_loans_outstanding=Decimal('50000.00'),
        )
        ClientGroup.objects.create(
            name='Other Union', branch=cls.branch, loan_officer=cls.other_staff,
            status='active', registration_date=today,
        )

    def test_staff_sees_only_their_own_union(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:report_unions'))
        groups = list(response.context['groups'])
        self.assertEqual(groups, [self.group])


class DashboardClientOverviewTests(TestCase):
    """The Client Overview chart is Manager+ only, not shown to staff."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SR006')
        cls.staff = make_user(cls.branch, role='staff', email='sr6_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='sr6_mgr@test.com')
        # is_active/approval_status are hardcoded kwargs inside make_client()
        # itself (approval_status='approved', is_active=True), so they can't
        # be overridden via **kwargs — mutate after creation instead.
        make_client(cls.branch, cls.staff, email='sr6_active@test.com')

        pending = make_client(cls.branch, cls.staff, email='sr6_pending@test.com')
        pending.is_active = False
        pending.approval_status = 'pending'
        pending.save()

        closed = make_client(cls.branch, cls.staff, email='sr6_closed@test.com')
        closed.is_active = False
        closed.save()

    def test_manager_sees_client_overview(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:dashboard'))
        overview = response.context['client_overview']
        self.assertIsNotNone(overview)
        self.assertEqual(overview['registered'], 3)
        self.assertEqual(overview['pending_approval'], 1)

    def test_staff_does_not_see_client_overview(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:dashboard'))
        self.assertIsNone(response.context['client_overview'])
