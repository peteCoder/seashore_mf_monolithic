"""
Tests for pagination on the savings account detail page — the same
truncation bug fixed on the client/loan detail pages (core/tests/
test_detail_page_pagination.py), applied here too, since a savings
account's transaction history is just as important as a loan's.

Also covers a separate, more serious bug found while fixing this: the
"Pending Postings" tab's template loop (`{% for posting in pending_postings %}`)
never actually received a `pending_postings` variable from the view — the
view built `deposit_postings`/`withdrawal_postings` but never combined or
passed them — so that tab silently showed nothing at all, regardless of how
many deposits/withdrawals were actually awaiting approval.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import SavingsAccount, SavingsDepositPosting, SavingsWithdrawalPosting, Transaction
from core.tests.factories import make_branch, make_user, make_client, make_savings_product


class SavingsAccountDetailTransactionPaginationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SPAG001')
        cls.staff = make_user(cls.branch, role='staff', email='spag_staff@test.com')
        cls.director = make_user(cls.branch, role='director', email='spag_dir@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='spag_client@test.com')
        cls.product = make_savings_product(code='SPAG001P')
        cls.account = SavingsAccount.objects.create(
            client=cls.client_obj, savings_product=cls.product, branch=cls.branch,
            status='active', balance=Decimal('50000.00'), approval_status='approved',
        )

        for i in range(25):
            Transaction.objects.create(
                transaction_type='deposit', amount=Decimal('1000.00'),
                client=cls.client_obj, savings_account=cls.account, branch=cls.branch,
                balance_before=Decimal('0.00'), balance_after=Decimal('1000.00'),
                processed_by=cls.staff, description=f'dep {i}',
                status='completed', transaction_date=timezone.now(),
            )

    def setUp(self):
        self.client.force_login(self.director)

    def test_page_one_shows_20_and_reports_full_count(self):
        response = self.client.get(reverse('core:savings_account_detail', args=[self.account.id]))
        page = response.context['transactions']
        self.assertEqual(len(page.object_list), 20)
        self.assertEqual(page.paginator.count, 25)

    def test_every_transaction_reachable_across_pages(self):
        seen = set()
        for page_num in (1, 2):
            response = self.client.get(
                reverse('core:savings_account_detail', args=[self.account.id]),
                {'transactions_page': page_num},
            )
            seen.update(t.id for t in response.context['transactions'].object_list)
        all_ids = set(Transaction.objects.filter(savings_account=self.account).values_list('id', flat=True))
        self.assertEqual(seen, all_ids)

    def test_tab_label_shows_full_count(self):
        response = self.client.get(reverse('core:savings_account_detail', args=[self.account.id]))
        self.assertContains(response, 'Transaction History (25)')


class SavingsAccountPendingPostingsTests(TestCase):
    """The bug: this tab previously always rendered as empty, regardless of
    real pending postings. Now it must show them, combined, and paginated."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='SPAG002')
        cls.staff = make_user(cls.branch, role='staff', email='spag2_staff@test.com')
        cls.director = make_user(cls.branch, role='director', email='spag2_dir@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='spag2_client@test.com')
        cls.product = make_savings_product(code='SPAG002P')
        cls.account = SavingsAccount.objects.create(
            client=cls.client_obj, savings_product=cls.product, branch=cls.branch,
            status='active', balance=Decimal('20000.00'), approval_status='approved',
        )

        for i in range(3):
            SavingsDepositPosting.objects.create(
                posting_ref=f'SDPTEST{i:03d}', savings_account=cls.account,
                client=cls.client_obj, branch=cls.branch, amount=Decimal('500.00'),
                payment_date=timezone.now().date(), submitted_by=cls.staff, status='pending',
            )
        for i in range(3):
            SavingsWithdrawalPosting.objects.create(
                posting_ref=f'SWPTEST{i:03d}', savings_account=cls.account,
                client=cls.client_obj, branch=cls.branch, amount=Decimal('300.00'),
                withdrawal_date=timezone.now().date(), submitted_by=cls.staff, status='pending',
            )
        # An approved (non-pending) posting must NOT show up in the tab.
        SavingsDepositPosting.objects.create(
            posting_ref='SDPTESTAPPROVED', savings_account=cls.account,
            client=cls.client_obj, branch=cls.branch, amount=Decimal('999.00'),
            payment_date=timezone.now().date(), submitted_by=cls.staff, status='approved',
        )

    def setUp(self):
        self.client.force_login(self.director)

    def test_pending_postings_variable_is_actually_populated(self):
        response = self.client.get(reverse('core:savings_account_detail', args=[self.account.id]))
        page = response.context['pending_postings']
        self.assertEqual(page.paginator.count, 6)  # 3 deposits + 3 withdrawals, approved one excluded

    def test_both_deposit_and_withdrawal_postings_appear_in_the_page(self):
        response = self.client.get(reverse('core:savings_account_detail', args=[self.account.id]))
        refs = {p.posting_ref for p in response.context['pending_postings'].object_list}
        self.assertTrue(any(r.startswith('SDPTEST') and 'APPROVED' not in r for r in refs))
        self.assertTrue(any(r.startswith('SWPTEST') for r in refs))
        self.assertNotIn('SDPTESTAPPROVED', refs)

    def test_tab_shows_correct_combined_count_not_zero(self):
        response = self.client.get(reverse('core:savings_account_detail', args=[self.account.id]))
        self.assertContains(response, 'Pending Postings (6)')
        self.assertNotContains(response, 'Pending Postings (0)')

    def test_date_field_normalized_so_template_can_render_it(self):
        """Deposit uses payment_date, withdrawal uses withdrawal_date — the
        view must normalize both to .transaction_date for the shared template
        loop, or the date column renders blank."""
        response = self.client.get(reverse('core:savings_account_detail', args=[self.account.id]))
        for p in response.context['pending_postings'].object_list:
            self.assertTrue(hasattr(p, 'transaction_date') and p.transaction_date is not None)
