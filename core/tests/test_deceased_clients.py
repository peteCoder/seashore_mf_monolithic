"""
Tests for Deceased-client handling:
  - Client.is_deceased/deceased_date/marked_deceased_by/marked_deceased_at
  - core/views/client_views.client_mark_deceased / client_unmark_deceased
  - The unresolved-loans / accounts-needing-resolution banner on client_detail
  - Savings deposit freeze in core/views/savings_views.py (the actual gap
    this feature closes — deposit/withdrawal posting had NO status check
    at all before this)

Design decisions under test (confirmed with the user, don't relitigate):
  - Marking deceased is NOT blocked by active loans — client_deactivate's
    "active loans" block is untouched and separate.
  - Savings: deposits frozen, withdrawals still allowed once deceased.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Client, ClientGroup, Loan, SavingsAccount, SavingsDepositPosting,
    GroupSavingsCollectionSession, GroupSavingsCollectionItem,
)
from core.tests.factories import (
    make_branch, make_user, make_client, make_loan_product, make_savings_product,
)


class MarkDeceasedPermissionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='DC001')
        cls.director = make_user(cls.branch, role='director', email='dc1_dir@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='dc1_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='dc1_client@test.com')

    def _url(self):
        return reverse('core:client_mark_deceased', args=[self.client_obj.id])

    def test_director_can_mark_deceased(self):
        self.client.force_login(self.director)
        response = self.client.post(self._url(), {'reason': 'Confirmed by family'}, follow=True)
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_deceased)
        self.assertEqual(self.client_obj.marked_deceased_by, self.director)
        self.assertIn('Confirmed by family', self.client_obj.notes)

    def test_staff_cannot_mark_deceased(self):
        self.client.force_login(self.staff)
        response = self.client.post(self._url(), {'reason': 'x'})
        self.assertEqual(response.status_code, 403)
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_deceased)

    def test_marking_deceased_stores_optional_date(self):
        self.client.force_login(self.director)
        self.client.post(self._url(), {'reason': 'x', 'deceased_date': '2026-08-15'})
        self.client_obj.refresh_from_db()
        self.assertEqual(str(self.client_obj.deceased_date), '2026-08-15')

    def test_marking_deceased_works_with_no_date_given(self):
        self.client.force_login(self.director)
        self.client.post(self._url(), {'reason': 'x'})
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_deceased)
        self.assertIsNone(self.client_obj.deceased_date)


class MarkDeceasedNotBlockedByActiveLoansTests(TestCase):
    """The core original ask: marking deceased must NOT require loans to be
    resolved first — that's a deliberate difference from client_deactivate,
    which still blocks on active loans (untouched, tested separately)."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='DC002')
        cls.director = make_user(cls.branch, role='director', email='dc2_dir@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='dc2_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='dc2_client@test.com')
        cls.product = make_loan_product(code='DC002P')
        cls.loan = Loan.objects.create(
            client=cls.client_obj, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('50000.00'), duration_months=3,
            disbursement_method='cash', created_by=cls.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('40000.00'),
        )

    def test_mark_deceased_succeeds_with_active_loan(self):
        self.client.force_login(self.director)
        response = self.client.post(
            reverse('core:client_mark_deceased', args=[self.client_obj.id]),
            {'reason': 'Confirmed'}, follow=True,
        )
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_deceased)

    def test_deactivate_still_blocked_by_active_loan_afterward(self):
        """Deceased is orthogonal — deactivation's existing loan block is untouched."""
        self.client.force_login(self.director)
        self.client.post(reverse('core:client_mark_deceased', args=[self.client_obj.id]), {'reason': 'x'})
        response = self.client.post(
            reverse('core:client_deactivate', args=[self.client_obj.id]), {'reason': 'x'}, follow=True,
        )
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_active)  # still active — deactivation was blocked

    def test_unresolved_loans_shown_on_detail_page(self):
        self.client.force_login(self.director)
        self.client.post(reverse('core:client_mark_deceased', args=[self.client_obj.id]), {'reason': 'x'})
        response = self.client.get(reverse('core:client_detail', args=[self.client_obj.id]))
        self.assertIn(self.loan, list(response.context['unresolved_loans']))
        self.assertContains(response, self.loan.loan_number)
        self.assertContains(response, 'still need')


class UnmarkDeceasedTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='DC003')
        cls.director = make_user(cls.branch, role='director', email='dc3_dir@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='dc3_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='dc3_client@test.com')

    def test_unmark_clears_deceased_flag(self):
        self.client.force_login(self.director)
        self.client.post(reverse('core:client_mark_deceased', args=[self.client_obj.id]), {'reason': 'x'})
        self.client_obj.refresh_from_db()
        self.assertTrue(self.client_obj.is_deceased)

        self.client.post(reverse('core:client_unmark_deceased', args=[self.client_obj.id]))
        self.client_obj.refresh_from_db()
        self.assertFalse(self.client_obj.is_deceased)
        self.assertIsNone(self.client_obj.deceased_date)
        self.assertIsNone(self.client_obj.marked_deceased_by)


class SavingsFreezeTests(TestCase):
    """
    The actual gap this feature closes: deposit/withdrawal posting had NO
    status check at all before this. Deposits get blocked once the client
    is deceased; withdrawals stay allowed (per the user's explicit choice —
    otherwise the balance could never be paid out and the account closed).
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='DC004')
        cls.director = make_user(cls.branch, role='director', email='dc4_dir@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='dc4_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='dc4_client@test.com')
        cls.product = make_savings_product(code='DC004P')
        cls.account = SavingsAccount.objects.create(
            client=cls.client_obj, savings_product=cls.product, branch=cls.branch,
            status='active', balance=Decimal('5000.00'), approval_status='approved',
        )

    def _mark_deceased(self):
        self.client.force_login(self.director)
        self.client.post(reverse('core:client_mark_deceased', args=[self.client_obj.id]), {'reason': 'x'})
        self.client.force_login(self.staff)

    def test_deposit_blocked_once_deceased(self):
        self._mark_deceased()
        response = self.client.post(
            reverse('core:savings_deposit_post_for_account', args=[self.account.id]),
            {
                'savings_account': self.account.id, 'amount': '1000.00',
                'payment_method': 'cash', 'payment_date': timezone.now().date().isoformat(),
            },
            follow=True,
        )
        self.assertFalse(SavingsDepositPosting.objects.filter(savings_account=self.account).exists())
        self.assertContains(response, 'deceased')

    def test_deposit_allowed_before_deceased(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('core:savings_deposit_post_for_account', args=[self.account.id]),
            {
                'savings_account': self.account.id, 'amount': '1000.00',
                'payment_method': 'cash', 'payment_date': timezone.now().date().isoformat(),
            },
            follow=True,
        )
        self.assertTrue(SavingsDepositPosting.objects.filter(savings_account=self.account).exists())

    def test_deceased_client_account_excluded_from_bulk_deposit_picker(self):
        self._mark_deceased()
        response = self.client.get(reverse('core:savings_deposit_post_bulk'))
        accounts = list(response.context['accounts'])
        self.assertNotIn(self.account, accounts)

    def test_withdrawal_still_allowed_once_deceased(self):
        self._mark_deceased()
        from core.models import SavingsWithdrawalPosting
        response = self.client.post(
            reverse('core:savings_withdrawal_post_for_account', args=[self.account.id]),
            {
                'savings_account': self.account.id, 'amount': '1000.00',
                'payment_method': 'cash', 'withdrawal_date': timezone.now().date().isoformat(),
            },
            follow=True,
        )
        self.assertTrue(SavingsWithdrawalPosting.objects.filter(savings_account=self.account).exists())


class GroupCollectionFreezeTests(TestCase):
    """
    Real gap found (and fixed) after the standalone freeze shipped: group
    collection screens (/collect-savings/, /collect-all/) filtered purely on
    savings_accounts__status='active' with no deceased check at all — a
    deceased client's account kept showing up there as collectible even
    though the standalone deposit pages were frozen. Confirmed against a
    real group before fixing.
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='DC005')
        cls.director = make_user(cls.branch, role='director', email='dc5_dir@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='dc5_staff@test.com')
        cls.group = ClientGroup.objects.create(
            name='Test Union', branch=cls.branch, loan_officer=cls.staff,
            status='active', registration_date=timezone.now().date(),
        )
        cls.client_obj = make_client(cls.branch, cls.staff, email='dc5_client@test.com', group=cls.group)
        cls.product = make_savings_product(code='DC005P')
        cls.account = SavingsAccount.objects.create(
            client=cls.client_obj, savings_product=cls.product, branch=cls.branch,
            status='active', balance=Decimal('5000.00'), approval_status='approved',
        )

    def _mark_deceased(self):
        self.client.force_login(self.director)
        self.client.post(reverse('core:client_mark_deceased', args=[self.client_obj.id]), {'reason': 'x'})

    def test_deceased_client_excluded_from_savings_collection_listing(self):
        self._mark_deceased()
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:group_savings_collection', args=[self.group.id]))
        clients_listed = {d['client'] for d in response.context['member_savings_data']}
        self.assertNotIn(self.client_obj, clients_listed)

    def test_deceased_client_excluded_from_combined_collection_listing(self):
        self._mark_deceased()
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:group_combined_collection', args=[self.group.id]))
        clients_listed = {d['client'] for d in response.context['member_savings_data']}
        self.assertNotIn(self.client_obj, clients_listed)

    def test_tampered_submission_for_deceased_client_silently_skipped(self):
        """Safety net: even if the form is tampered with to include a
        deceased client's account_id, the posting view must not accept it."""
        self._mark_deceased()
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('core:group_savings_collection_post', args=[self.group.id]),
            {
                'total_amount': '1000.00',
                'payment_date': timezone.now().date().isoformat(),
                f'amount_{self.account.id}': '1000.00',
            },
            follow=True,
        )
        self.assertContains(response, 'No valid amounts')
        self.assertFalse(GroupSavingsCollectionItem.objects.filter(savings_account=self.account).exists())

    def test_approval_time_race_condition_skips_deposit(self):
        """A session submitted while the client was alive, then approved
        after they're marked deceased — the deposit must be skipped, not
        silently processed just because it already passed submission-time
        checks."""
        session = GroupSavingsCollectionSession.objects.create(
            group=self.group, collected_by=self.staff,
            collection_date=timezone.now().date(), total_amount=Decimal('1000.00'),
            status='pending',
        )
        GroupSavingsCollectionItem.objects.create(
            session=session, client=self.client_obj, savings_account=self.account,
            amount=Decimal('1000.00'),
        )
        self._mark_deceased()

        self.client.force_login(self.director)
        response = self.client.post(
            reverse('core:group_savings_collection_approve', args=[session.id]),
            {'decision': 'approve', 'transaction_date': timezone.now().date().isoformat()},
            follow=True,
        )
        self.assertContains(response, 'deceased')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('5000.00'))  # unchanged — deposit skipped
