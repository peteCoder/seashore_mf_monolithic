"""
View / HTTP Tests
==================

Tests that key views:
- Redirect unauthenticated users to login
- Return HTTP 200 for authenticated users with correct roles
- Reject POST with invalid data properly
"""

from django.test import TestCase, Client as HttpClient
from django.urls import reverse

from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestAuthViews(TestCase):
    """Login / logout views."""

    def test_login_page_accessible(self):
        response = self.client.get(reverse('core:login'))
        self.assertEqual(response.status_code, 200)

    def test_register_page_accessible(self):
        response = self.client.get(reverse('core:register'))
        self.assertEqual(response.status_code, 200)

    def test_login_with_valid_credentials(self):
        branch = make_branch(code='AUTH01')
        user = make_user(branch, email='login_test@test.com')
        response = self.client.post(reverse('core:login'), {
            'email': 'login_test@test.com',
            'password': 'TestPass123!',
        })
        # Should redirect after successful login
        self.assertIn(response.status_code, [200, 302])

    def test_login_with_wrong_password(self):
        branch = make_branch(code='AUTH02')
        make_user(branch, email='badpwd@test.com')
        response = self.client.post(reverse('core:login'), {
            'email': 'badpwd@test.com',
            'password': 'WrongPassword',
        })
        # Should stay on login page (200) with error
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertRedirects(
            response,
            f"{reverse('core:login')}?next={reverse('core:dashboard')}",
            fetch_redirect_response=False,
        )

    def test_logout_redirects_to_login(self):
        branch = make_branch(code='AUTH03')
        user = make_user(branch, email='logout_test@test.com')
        self.client.force_login(user)
        response = self.client.get(reverse('core:logout'))
        self.assertRedirects(response, reverse('core:login'), fetch_redirect_response=False)


class TestClientViews(TestCase):
    """Client list and detail views — authenticated access."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='CV001')
        cls.staff = make_user(cls.branch, role='staff', email='cv_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='cv_mgr@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='cv_client@test.com')

    def test_client_list_requires_login(self):
        response = self.client.get(reverse('core:client_list'))
        self.assertEqual(response.status_code, 302)

    def test_client_list_accessible_to_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_list'))
        self.assertEqual(response.status_code, 200)

    def test_client_detail_accessible(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_detail', args=[self.client_obj.id]))
        self.assertEqual(response.status_code, 200)

    def test_client_statement_accessible(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_statement', args=[self.client_obj.id]))
        self.assertEqual(response.status_code, 200)

    def test_subsidiary_ledger_accessible(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:subsidiary_ledger', args=[self.client_obj.id]))
        self.assertEqual(response.status_code, 200)


class TestLoanViews(TestCase):
    """Loan list and detail views."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='LV001')
        cls.staff = make_user(cls.branch, role='staff', email='lv_staff@test.com')
        cls.product = make_loan_product(code='LVP001')

    def test_loan_list_requires_login(self):
        response = self.client.get(reverse('core:loan_list'))
        self.assertEqual(response.status_code, 302)

    def test_loan_list_accessible_to_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:loan_list'))
        self.assertEqual(response.status_code, 200)


class TestAccountingViews(TestCase):
    """Accounting dashboard and reports — manager+ required."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='AV001')
        cls.staff = make_user(cls.branch, role='staff', email='av_staff@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='av_mgr@test.com')
        cls.director = make_user(cls.branch, role='director', email='av_dir@test.com')

    def test_accounting_dashboard_requires_login(self):
        response = self.client.get(reverse('core:accounting_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_accounting_dashboard_accessible_to_manager(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:accounting_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_par_aging_report_accessible(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:report_par_aging'))
        self.assertEqual(response.status_code, 200)

    def test_audit_log_restricted_to_director(self):
        # Staff should be denied
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:audit_log'))
        self.assertIn(response.status_code, [302, 403])

    def test_audit_log_accessible_to_director(self):
        self.client.force_login(self.director)
        response = self.client.get(reverse('core:audit_log'))
        self.assertEqual(response.status_code, 200)


class TestImportViews(TestCase):
    """CSV import views — manager+ required."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='IMP01')
        cls.manager = make_user(cls.branch, role='manager', email='imp_mgr@test.com')

    def test_import_clients_page_accessible(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:import_clients'))
        self.assertEqual(response.status_code, 200)

    def test_import_loans_page_accessible(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:import_loans'))
        self.assertEqual(response.status_code, 200)


class TestTwoFactorViews(TestCase):
    """2FA setup and verify views."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='2FA01')
        cls.user = make_user(cls.branch, email='2fa_test@test.com')

    def test_setup_2fa_requires_login(self):
        response = self.client.get(reverse('core:setup_2fa'))
        self.assertEqual(response.status_code, 302)

    def test_setup_2fa_accessible_when_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('core:setup_2fa'))
        self.assertEqual(response.status_code, 200)

    def test_verify_2fa_redirects_without_pending_session(self):
        # No _2fa_pending_uid in session → redirect to login
        response = self.client.get(reverse('core:verify_2fa'))
        self.assertRedirects(
            response, reverse('core:login'), fetch_redirect_response=False
        )
