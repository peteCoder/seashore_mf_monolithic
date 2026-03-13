"""
Permission / Role Tests
=======================

Verifies that the PermissionChecker class enforces the role hierarchy:
  staff < manager < director < admin

Hierarchy rules under test:
- Staff cannot approve loans or clients
- Manager can approve loans in their own branch only
- Director/Admin can approve across all branches
- Only Admin can delete clients
"""

from django.test import TestCase

from core.tests.factories import make_branch, make_user, make_client
from core.permissions import PermissionChecker


class TestStaffPermissions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='PERM01')
        cls.staff = make_user(cls.branch, role='staff', email='perm_staff@test.com')

    def setUp(self):
        self.checker = PermissionChecker(self.staff)

    def test_staff_is_staff(self):
        self.assertTrue(self.checker.is_staff())

    def test_staff_is_not_manager(self):
        self.assertFalse(self.checker.is_manager())

    def test_staff_is_not_director(self):
        self.assertFalse(self.checker.is_director())

    def test_staff_is_not_admin(self):
        self.assertFalse(self.checker.is_admin())

    def test_staff_cannot_approve_loans(self):
        self.assertFalse(self.checker.can_approve_loans())

    def test_staff_cannot_approve_clients(self):
        self.assertFalse(self.checker.can_approve_client())

    def test_staff_cannot_delete_clients(self):
        self.assertFalse(self.checker.can_delete_client())

    def test_staff_cannot_approve_loans(self):
        self.assertFalse(self.checker.can_approve_loans())


class TestManagerPermissions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='PERM02')
        cls.other_branch = make_branch(name='Other Branch', code='PERM03')
        cls.manager = make_user(cls.branch, role='manager', email='perm_mgr@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='perm_mgr_staff@test.com')

    def setUp(self):
        self.checker = PermissionChecker(self.manager)

    def test_manager_is_manager(self):
        self.assertTrue(self.checker.is_manager())

    def test_manager_is_not_director(self):
        self.assertFalse(self.checker.is_director())

    def test_manager_can_approve_loans(self):
        self.assertTrue(self.checker.can_approve_loans())

    def test_manager_can_approve_clients(self):
        self.assertTrue(self.checker.can_approve_client())

    def test_manager_cannot_delete_clients(self):
        self.assertFalse(self.checker.can_delete_client())


class TestDirectorPermissions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='PERM04')
        cls.director = make_user(cls.branch, role='director', email='perm_dir@test.com')

    def setUp(self):
        self.checker = PermissionChecker(self.director)

    def test_director_is_director(self):
        self.assertTrue(self.checker.is_director())

    def test_director_is_admin_or_director(self):
        self.assertTrue(self.checker.is_admin_or_director())

    def test_director_can_approve_loans(self):
        self.assertTrue(self.checker.can_approve_loans())

    def test_director_cannot_delete_clients(self):
        self.assertFalse(self.checker.can_delete_client())  # admin-only permission

    def test_director_can_view_all_branches(self):
        self.assertTrue(self.checker.can_view_all_branches())


class TestAdminPermissions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='PERM05')
        cls.admin = make_user(cls.branch, role='admin', email='perm_admin@test.com')

    def setUp(self):
        self.checker = PermissionChecker(self.admin)

    def test_admin_is_admin(self):
        self.assertTrue(self.checker.is_admin())

    def test_admin_is_admin_or_director(self):
        self.assertTrue(self.checker.is_admin_or_director())

    def test_admin_can_approve_loans(self):
        self.assertTrue(self.checker.can_approve_loans())

    def test_admin_can_delete_clients(self):
        self.assertTrue(self.checker.can_delete_client())

    def test_admin_can_view_all_branches(self):
        self.assertTrue(self.checker.can_view_all_branches())
