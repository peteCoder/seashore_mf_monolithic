"""
Tests for the read-only 'auditor' role.

Two independent guarantees are tested:
1. An auditor can VIEW everything a director/admin/hr can (dashboard, client
   list, loan list, reports, financial statements).
2. An auditor can NEVER mutate anything — this is enforced by
   ReadOnlyAuditorMiddleware at the HTTP-method level, not by permission-list
   membership, so it is tested directly against real POST endpoints,
   including one (group collection approval) that would otherwise be
   incorrectly ALLOWED by PermissionChecker.can_approve_collections()
   because it reuses can_view_all_branches().
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Client, Loan
from core.permissions import PermissionChecker
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class AuditorCanViewEverythingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='AUD001')
        cls.other_branch = make_branch(name='AUD001 Other', code='AUD001B')
        cls.auditor = make_user(cls.branch, role='auditor', email='auditor1@test.com')
        cls.staff = make_user(cls.other_branch, role='staff', email='aud_staff@test.com')
        cls.client_obj = make_client(cls.other_branch, cls.staff, email='aud_client@test.com')
        cls.product = make_loan_product(code='AUD001P', loan_type='regular')
        cls.loan = Loan.objects.create(
            client=cls.client_obj, loan_product=cls.product, branch=cls.other_branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=cls.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('80000.00'),
            disbursement_date=timezone.now(),
        )

    def setUp(self):
        self.client.force_login(self.auditor)

    def test_checker_grants_full_view_access(self):
        checker = PermissionChecker(self.auditor)
        self.assertTrue(checker.can_view_all_branches())
        self.assertTrue(checker.can_view_reports())
        self.assertTrue(checker.can_view_staff_reports())
        self.assertTrue(checker.can_view_financials())
        self.assertTrue(checker.can_view_profit_loss())

    def test_auditor_sees_clients_and_loans_from_every_branch(self):
        checker = PermissionChecker(self.auditor)
        self.assertIn(self.client_obj, checker.filter_clients(Client.objects.all()))
        self.assertIn(self.loan, checker.filter_loans(Loan.objects.all()))

    def test_dashboard_loads(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_can_view_client_from_other_branch(self):
        response = self.client.get(reverse('core:client_detail', args=[self.client_obj.id]))
        self.assertEqual(response.status_code, 200)

    def test_can_view_loan_from_other_branch(self):
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        self.assertEqual(response.status_code, 200)

    def test_can_view_client_list(self):
        response = self.client.get(reverse('core:client_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.client_obj, response.context['clients'].object_list
                       if hasattr(response.context['clients'], 'object_list') else response.context['clients'])

    def test_can_view_officer_snapshot_all_officers(self):
        response = self.client.get(reverse('core:report_officer_snapshot'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['staff_options'])  # not locked to self like staff role

    def test_can_view_trial_balance(self):
        response = self.client.get(reverse('core:report_trial_balance'), {'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        self.assertEqual(response.status_code, 200)

    def test_can_view_profit_loss_page(self):
        response = self.client.get(reverse('core:report_profit_loss'), {'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        self.assertEqual(response.status_code, 200)

    def test_can_view_balance_sheet_page(self):
        response = self.client.get(reverse('core:report_balance_sheet'), {'as_of_date': '2026-12-31'})
        self.assertEqual(response.status_code, 200)

    def test_can_view_par_aging(self):
        response = self.client.get(reverse('core:report_par_aging'))
        self.assertEqual(response.status_code, 200)

    def test_can_view_audit_log(self):
        response = self.client.get(reverse('core:audit_log'))
        self.assertEqual(response.status_code, 200)

    def test_can_view_loan_products(self):
        response = self.client.get(reverse('core:loan_product_list'))
        self.assertEqual(response.status_code, 200)


class AuditorCannotMutateAnythingTests(TestCase):
    """The hard guarantee: every unsafe HTTP verb is blocked, regardless of
    what any individual view's own permission check says."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='AUD002')
        cls.auditor = make_user(cls.branch, role='auditor', email='auditor2@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='aud2_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='aud2_client@test.com')
        cls.product = make_loan_product(code='AUD002P', loan_type='regular')

    def setUp(self):
        self.client.force_login(self.auditor)

    def _assert_blocked(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'read-only auditor', response.content)

    def test_cannot_create_client(self):
        response = self.client.post(reverse('core:client_create'), {'first_name': 'X'})
        self._assert_blocked(response)

    def test_cannot_edit_client(self):
        response = self.client.post(
            reverse('core:client_update', args=[self.client_obj.id]), {'first_name': 'Hacked'}
        )
        self._assert_blocked(response)
        self.client_obj.refresh_from_db()
        self.assertNotEqual(self.client_obj.first_name, 'Hacked')

    def test_cannot_delete_client(self):
        response = self.client.post(reverse('core:client_delete', args=[self.client_obj.id]))
        self._assert_blocked(response)
        self.assertTrue(Client.objects.filter(id=self.client_obj.id).exists())

    def test_cannot_create_loan(self):
        response = self.client.post(reverse('core:loan_create'), {
            'client': self.client_obj.id, 'loan_product': self.product.id,
            'principal_amount': '50000', 'duration_months': '6',
        })
        self._assert_blocked(response)
        self.assertEqual(Loan.objects.filter(client=self.client_obj).count(), 0)

    def test_cannot_create_loan_product(self):
        response = self.client.post(reverse('core:loan_product_create'), {'code': 'HACK'})
        self._assert_blocked(response)

    def test_cannot_approve_group_collection_despite_permission_checker_landmine(self):
        """
        PermissionChecker.can_approve_collections() returns True for anyone
        with can_view_all_branches() -- which the auditor deliberately has.
        This proves the middleware, not that method, is what actually blocks
        the write: even though the view-level check would wrongly say yes,
        the POST is still rejected before the view runs.
        """
        checker = PermissionChecker(self.auditor)
        self.assertTrue(checker.can_approve_collections(), (
            "This permission-list landmine is expected to still be True for "
            "auditor -- it's exactly why the middleware exists, not a bug to fix here."
        ))
        import uuid
        response = self.client.post(
            reverse('core:group_collection_approve', args=[uuid.uuid4()]), {}
        )
        self._assert_blocked(response)

    def test_get_requests_are_never_blocked(self):
        response = self.client.get(reverse('core:client_list'))
        self.assertEqual(response.status_code, 200)

    def test_non_auditor_roles_are_unaffected_by_middleware(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('core:client_create'), {})
        self.assertNotEqual(response.status_code, 403)

    def test_auditor_can_still_log_out(self):
        response = self.client.get(reverse('core:logout'))
        self.assertEqual(response.status_code, 302)
