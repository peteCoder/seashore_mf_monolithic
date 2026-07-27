"""
Tests for /clients/<id>/statement/: a reversed transaction (e.g. a
duplicate loan disbursement corrected after the fact) must stay visible
in the statement for the audit trail, but must not count toward
total_in/total_out/net_position.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Transaction
from core.tests.factories import make_branch, make_user, make_client


class TestClientStatementReversedTransactions(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='CSR001')
        cls.staff = make_user(cls.branch, role='staff', email='csr_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='csr_client@test.com')

        cls.real_disbursement = Transaction.objects.create(
            transaction_type='loan_disbursement', amount=Decimal('200000.00'),
            client=cls.client_obj, branch=cls.branch, processed_by=cls.staff,
            status='completed', transaction_date=timezone.now(),
        )
        cls.duplicate_disbursement = Transaction.objects.create(
            transaction_type='loan_disbursement', amount=Decimal('200000.00'),
            client=cls.client_obj, branch=cls.branch, processed_by=cls.staff,
            status='reversed', transaction_date=timezone.now(),
        )
        cls.deposit = Transaction.objects.create(
            transaction_type='deposit', amount=Decimal('20000.00'),
            client=cls.client_obj, branch=cls.branch, processed_by=cls.staff,
            status='completed', transaction_date=timezone.now(),
        )

    def test_reversed_transaction_excluded_from_totals(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_statement', args=[self.client_obj.id]))
        self.assertEqual(response.status_code, 200)
        # Only the real (non-reversed) disbursement should count
        self.assertEqual(response.context['total_out'], Decimal('200000.00'))
        self.assertEqual(response.context['total_in'], Decimal('20000.00'))
        self.assertEqual(
            response.context['net_position'], Decimal('20000.00') - Decimal('200000.00')
        )

    def test_reversed_transaction_still_listed(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_statement', args=[self.client_obj.id]))
        txn_ids = {t.id for t in response.context['transactions']}
        self.assertIn(self.real_disbursement.id, txn_ids)
        self.assertIn(self.duplicate_disbursement.id, txn_ids)

    def test_reversed_badge_rendered(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_statement', args=[self.client_obj.id]))
        content = response.content.decode()
        self.assertIn('Reversed', content)
        self.assertIn('line-through', content)


class TestClientDetailReversedTransactionIndicator(TestCase):
    """
    /clients/<id>/ Transactions tab must visually flag a reversed
    transaction (transparent red row + "Reversed" badge), not just the
    dedicated statement page.
    """

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='CDR001')
        cls.staff = make_user(cls.branch, role='staff', email='cdr_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='cdr_client@test.com')

        cls.duplicate_disbursement = Transaction.objects.create(
            transaction_type='loan_disbursement', amount=Decimal('200000.00'),
            client=cls.client_obj, branch=cls.branch, processed_by=cls.staff,
            status='reversed', transaction_date=timezone.now(),
        )
        cls.real_disbursement = Transaction.objects.create(
            transaction_type='loan_disbursement', amount=Decimal('200000.00'),
            client=cls.client_obj, branch=cls.branch, processed_by=cls.staff,
            status='completed', transaction_date=timezone.now(),
        )

    def test_reversed_row_badge_and_highlight_rendered(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:client_detail', args=[self.client_obj.id]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Reversed', content)
        self.assertIn('bg-red-50/60', content)
        self.assertIn('line-through', content)
