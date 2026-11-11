"""
Tests for the direct Bulk Assignment page (core:bulk_assign).

Covers:
- Staff/loan-officer role can never reach the view (403).
- Manager can bulk-assign clients -> staff, but only within their own branch,
  even if ids from another branch are posted.
- Manager cannot perform branch-level moves (clients -> branch, staff ->
  branch) — those are HR and above only.
- HR can perform all three actions, across any branch.
- Every execution creates an auto-approved AssignmentRequest record (no
  pending step) with the correct assignment_data, for audit history.
"""
from django.test import TestCase
from django.urls import reverse

from core.models import AssignmentRequest, Client, User
from core.tests.factories import make_branch, make_user, make_client


class BulkAssignmentTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch_a = make_branch(name='Branch A', code='BULKA')
        cls.branch_b = make_branch(name='Branch B', code='BULKB')

        cls.manager_a = make_user(cls.branch_a, role='manager', email='mgr_a@test.com')
        cls.hr = make_user(cls.branch_a, role='hr', email='hr@test.com')
        cls.staff_a1 = make_user(cls.branch_a, role='staff', email='staff_a1@test.com')
        cls.staff_a2 = make_user(cls.branch_a, role='staff', email='staff_a2@test.com')
        cls.staff_b1 = make_user(cls.branch_b, role='staff', email='staff_b1@test.com')

        cls.client_a1 = make_client(cls.branch_a, cls.staff_a1, email='client_a1@test.com')
        cls.client_a2 = make_client(cls.branch_a, cls.staff_a1, email='client_a2@test.com')
        cls.client_b1 = make_client(cls.branch_b, cls.staff_b1, email='client_b1@test.com')

    # ── Access control ───────────────────────────────────────────────────

    def test_staff_cannot_access(self):
        self.client.force_login(self.staff_a1)
        response = self.client.get(reverse('core:bulk_assign'))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_view(self):
        self.client.force_login(self.manager_a)
        response = self.client.get(reverse('core:bulk_assign'))
        self.assertEqual(response.status_code, 200)

    def test_hr_can_view(self):
        self.client.force_login(self.hr)
        response = self.client.get(reverse('core:bulk_assign'))
        self.assertEqual(response.status_code, 200)

    # ── Manager: clients -> staff, own branch only ──────────────────────

    def test_manager_can_assign_clients_to_staff_in_own_branch(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_staff',
            'clients': [str(self.client_a1.id), str(self.client_a2.id)],
            'target_staff': str(self.staff_a2.id),
            'reason': 'Rebalancing portfolios',
        })
        self.assertEqual(response.status_code, 302)

        self.client_a1.refresh_from_db()
        self.client_a2.refresh_from_db()
        self.assertEqual(self.client_a1.assigned_staff_id, self.staff_a2.id)
        self.assertEqual(self.client_a2.assigned_staff_id, self.staff_a2.id)

        req = AssignmentRequest.objects.latest('created_at')
        self.assertEqual(req.assignment_type, 'bulk_clients_to_staff')
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.requested_by, self.manager_a)
        self.assertEqual(req.reviewed_by, self.manager_a)
        self.assertEqual(req.affected_count, 2)
        self.assertIsNotNone(req.executed_at)

    def test_manager_cannot_move_a_client_from_another_branch(self):
        """Even if a manager somehow posts a client id from another branch,
        the view must silently exclude it rather than act on it."""
        self.client.force_login(self.manager_a)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_staff',
            'clients': [str(self.client_b1.id)],
            'target_staff': str(self.staff_a2.id),
            'reason': 'Attempted cross-branch move',
        })
        self.assertEqual(response.status_code, 200)  # re-rendered with error
        self.client_b1.refresh_from_db()
        self.assertEqual(self.client_b1.assigned_staff_id, self.staff_b1.id)  # unchanged

    def test_manager_cannot_use_a_target_staff_from_another_branch(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_staff',
            'clients': [str(self.client_a1.id)],
            'target_staff': str(self.staff_b1.id),
            'reason': 'Attempted cross-branch target',
        })
        self.assertEqual(response.status_code, 200)
        self.client_a1.refresh_from_db()
        self.assertEqual(self.client_a1.assigned_staff_id, self.staff_a1.id)  # unchanged

    # ── Manager: branch-level moves forbidden ───────────────────────────

    def test_manager_cannot_move_clients_to_branch(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_branch',
            'clients': [str(self.client_a1.id)],
            'target_branch': str(self.branch_b.id),
            'reason': 'Should be forbidden',
        })
        self.assertEqual(response.status_code, 403)
        self.client_a1.refresh_from_db()
        self.assertEqual(self.client_a1.branch_id, self.branch_a.id)

    def test_manager_cannot_move_staff_to_branch(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'staff_to_branch',
            'staff': [str(self.staff_a1.id)],
            'target_branch': str(self.branch_b.id),
            'reason': 'Should be forbidden',
        })
        self.assertEqual(response.status_code, 403)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_a.id)

    # ── HR: all three actions, any branch ───────────────────────────────

    def test_hr_can_move_clients_to_branch(self):
        self.client.force_login(self.hr)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_branch',
            'clients': [str(self.client_a1.id)],
            'target_branch': str(self.branch_b.id),
            'reason': 'Client relocated',
        })
        self.assertEqual(response.status_code, 302)
        self.client_a1.refresh_from_db()
        self.assertEqual(self.client_a1.branch_id, self.branch_b.id)

        req = AssignmentRequest.objects.latest('created_at')
        self.assertEqual(req.assignment_type, 'bulk_clients_to_branch')
        self.assertEqual(req.status, 'approved')

    def test_hr_can_move_staff_to_branch(self):
        self.client.force_login(self.hr)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'staff_to_branch',
            'staff': [str(self.staff_a1.id)],
            'target_branch': str(self.branch_b.id),
            'reason': 'Staff transfer',
        })
        self.assertEqual(response.status_code, 302)
        self.staff_a1.refresh_from_db()
        self.assertEqual(self.staff_a1.branch_id, self.branch_b.id)

        req = AssignmentRequest.objects.latest('created_at')
        self.assertEqual(req.assignment_type, 'bulk_staff_to_branch')
        self.assertEqual(req.status, 'approved')
        self.assertEqual(list(req.get_affected_staff()), [self.staff_a1])

    def test_hr_can_assign_clients_to_staff_across_branches(self):
        self.client.force_login(self.hr)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_staff',
            'clients': [str(self.client_b1.id)],
            'target_staff': str(self.staff_b1.id),
            'reason': 'HR rebalancing',
        })
        self.assertEqual(response.status_code, 302)

    # ── Validation ───────────────────────────────────────────────────────

    def test_reason_is_required(self):
        self.client.force_login(self.manager_a)
        response = self.client.post(reverse('core:bulk_assign'), {
            'tab': 'clients_to_staff',
            'clients': [str(self.client_a1.id)],
            'target_staff': str(self.staff_a2.id),
            'reason': '',
        })
        self.assertEqual(response.status_code, 200)
        self.client_a1.refresh_from_db()
        self.assertEqual(self.client_a1.assigned_staff_id, self.staff_a1.id)  # unchanged
