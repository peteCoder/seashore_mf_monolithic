"""
Tests for pagination on the client and loan detail pages.

Previously these pages silently truncated history to a fixed slice
(client transactions to 15, loan transactions/repayment postings to 10) with
no way to see anything past that limit. This replaces the truncation with
real Django pagination: every record is still reachable, just a page at a
time, and each list's tab keeps its own page number in the URL
(?transactions_page=, ?postings_page=) so paging through one list doesn't
reset another on the same page.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Loan, LoanRepaymentPosting, Transaction
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class ClientDetailTransactionPaginationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='PAG001')
        cls.staff = make_user(cls.branch, role='staff', email='pag_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='pag_client@test.com')
        cls.director = make_user(cls.branch, role='director', email='pag_dir@test.com')

        # 25 transactions -> more than one page at 20/page, so nothing that
        # used to be truncated at 15 should now be unreachable.
        for i in range(25):
            Transaction.objects.create(
                transaction_type='loan_repayment',
                amount=Decimal('1000.00'),
                client=cls.client_obj,
                branch=cls.branch,
                balance_before=Decimal('0.00'),
                balance_after=Decimal('1000.00'),
                processed_by=cls.staff,
                description=f'txn {i}',
                status='completed',
                transaction_date=timezone.now(),
            )

    def setUp(self):
        self.client.force_login(self.director)

    def test_page_one_shows_20_and_reports_full_count(self):
        response = self.client.get(reverse('core:client_detail', args=[self.client_obj.id]))
        page = response.context['recent_transactions']
        self.assertEqual(len(page.object_list), 20)
        self.assertEqual(page.paginator.count, 25)
        self.assertEqual(page.paginator.num_pages, 2)

    def test_page_two_reaches_the_remaining_transactions(self):
        response = self.client.get(
            reverse('core:client_detail', args=[self.client_obj.id]), {'transactions_page': 2}
        )
        page = response.context['recent_transactions']
        self.assertEqual(len(page.object_list), 5)

    def test_every_transaction_is_reachable_across_pages(self):
        seen_ids = set()
        for page_num in (1, 2):
            response = self.client.get(
                reverse('core:client_detail', args=[self.client_obj.id]), {'transactions_page': page_num}
            )
            seen_ids.update(t.id for t in response.context['recent_transactions'].object_list)
        all_ids = set(Transaction.objects.filter(client=self.client_obj).values_list('id', flat=True))
        self.assertEqual(seen_ids, all_ids)

    def test_pagination_controls_render_when_more_than_one_page(self):
        response = self.client.get(reverse('core:client_detail', args=[self.client_obj.id]))
        self.assertContains(response, 'transactions_page=2')

    def test_no_pagination_controls_when_everything_fits_on_one_page(self):
        other_client = make_client(self.branch, self.staff, email='pag_client_small@test.com')
        response = self.client.get(reverse('core:client_detail', args=[other_client.id]))
        self.assertNotContains(response, 'transactions_page=2')


class LoanDetailTransactionAndPostingPaginationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='PAG002')
        cls.staff = make_user(cls.branch, role='staff', email='pag2_staff@test.com')
        cls.director = make_user(cls.branch, role='director', email='pag2_dir@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='pag2_client@test.com')
        cls.product = make_loan_product(code='PAG002P', loan_type='regular')
        cls.loan = Loan.objects.create(
            client=cls.client_obj, loan_product=cls.product, branch=cls.branch,
            principal_amount=Decimal('500000.00'), duration_months=12,
            disbursement_method='cash', created_by=cls.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('400000.00'),
            disbursement_date=timezone.now(),
        )

        for i in range(15):
            Transaction.objects.create(
                transaction_type='loan_repayment',
                amount=Decimal('1000.00'),
                client=cls.client_obj,
                loan=cls.loan,
                branch=cls.branch,
                balance_before=Decimal('0.00'),
                balance_after=Decimal('1000.00'),
                processed_by=cls.staff,
                description=f'loan txn {i}',
                status='completed',
                transaction_date=timezone.now(),
            )
            LoanRepaymentPosting.objects.create(
                loan=cls.loan,
                amount=Decimal('1000.00'),
                payment_date=timezone.now().date(),
                submitted_by=cls.staff,
                status='approved',
                posting_ref=f'LRPTEST{i:03d}',
            )

    def setUp(self):
        self.client.force_login(self.director)

    def test_transactions_full_count_visible_across_pages(self):
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        page = response.context['transactions']
        self.assertEqual(page.paginator.count, 15)
        self.assertEqual(len(page.object_list), 15)  # 15 < 20/page, all on page 1

    def test_postings_full_count_visible(self):
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        page = response.context['repayment_postings']
        self.assertEqual(page.paginator.count, 15)

    def test_transactions_and_postings_paginate_independently(self):
        """Paging one list must not reset or affect the other's page."""
        response = self.client.get(
            reverse('core:loan_detail', args=[self.loan.id]),
            {'transactions_page': 1, 'postings_page': 1},
        )
        self.assertEqual(response.status_code, 200)
        # Both keys survive a request together without erroring or interfering.
        self.assertEqual(response.context['transactions'].number, 1)
        self.assertEqual(response.context['repayment_postings'].number, 1)

    def test_tab_label_shows_full_count_not_page_size(self):
        response = self.client.get(reverse('core:loan_detail', args=[self.loan.id]))
        self.assertContains(response, 'Transactions (15)')
        self.assertContains(response, 'Repayment Postings (15)')

    def test_more_than_20_transactions_are_all_reachable(self):
        for i in range(15, 30):
            Transaction.objects.create(
                transaction_type='loan_repayment', amount=Decimal('1000.00'),
                client=self.client_obj, loan=self.loan, branch=self.branch,
                balance_before=Decimal('0.00'), balance_after=Decimal('1000.00'),
                processed_by=self.staff, description=f'loan txn {i}',
                status='completed', transaction_date=timezone.now(),
            )
        seen = set()
        for page_num in (1, 2):
            response = self.client.get(
                reverse('core:loan_detail', args=[self.loan.id]), {'transactions_page': page_num}
            )
            seen.update(t.id for t in response.context['transactions'].object_list)
        self.assertEqual(len(seen), 30)
