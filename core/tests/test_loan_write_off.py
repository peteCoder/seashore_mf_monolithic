"""
Tests for core/views/loan_views.loan_write_off — the Bad Debt Write-Off flow.

Regression coverage for a real production bug: the journal entry it posts
was hardcoded to debit GL account '5050', which doesn't exist anywhere in
this app's actual Chart of Accounts (the real account for this purpose is
'5910 Provision for Bad Debts', under the "59 - Loan Loss Provisions"
category). Every write-off attempt failed with "Account 5050 not found or
inactive" — caught when a Director tried to write off a real deceased
client's loan. Zero loans had ever been successfully written off before
this fix (verified against production: Loan.objects.filter(status=
'written_off').count() == 0).
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import AccountType, Loan
from core.tests.factories import make_branch, make_user, make_client, make_loan_product, make_gl_account


class LoanWriteOffTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='WO001')
        cls.director = make_user(cls.branch, role='director', email='wo1_dir@test.com')
        cls.manager = make_user(cls.branch, role='manager', email='wo1_mgr@test.com')
        cls.staff = make_user(cls.branch, role='staff', email='wo1_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='wo1_client@test.com')
        cls.product = make_loan_product(code='WO001P')

        expense_type, _ = AccountType.objects.get_or_create(name='expense')
        asset_type, _ = AccountType.objects.get_or_create(name='asset')
        # The three GL accounts the write-off journal entry actually needs —
        # matches the real Chart of Accounts codes, not the old broken '5050'.
        make_gl_account(gl_code='5910', name='Provision for Bad Debts', account_type=expense_type)
        make_gl_account(gl_code='1810', name='Loan Receivable - Principal', account_type=asset_type)
        make_gl_account(gl_code='1820', name='Interest Receivable - Loans', account_type=asset_type)

    def _make_loan(self, **kwargs):
        defaults = dict(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=4,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('95600.00'),
            accrued_interest_balance=Decimal('0.00'),
        )
        defaults.update(kwargs)
        return Loan.objects.create(**defaults)

    def test_write_off_succeeds_and_posts_journal_entry(self):
        loan = self._make_loan()
        self.client.force_login(self.director)
        response = self.client.post(
            reverse('core:loan_write_off', args=[loan.id]),
            {'reason': 'Client deceased'},
            follow=True,
        )
        self.assertContains(response, 'written off')

        loan.refresh_from_db()
        self.assertEqual(loan.status, 'written_off')
        self.assertEqual(loan.outstanding_balance, Decimal('0.00'))

        from core.models import JournalEntry
        entry = JournalEntry.objects.filter(reference_number=f'WRITE-OFF-{loan.loan_number}').first()
        self.assertIsNotNone(entry)
        lines = {l.account.gl_code: l for l in entry.lines.all()}
        self.assertIn('5910', lines)
        self.assertEqual(lines['5910'].debit_amount, Decimal('95600.00'))
        self.assertIn('1810', lines)
        self.assertEqual(lines['1810'].credit_amount, Decimal('95600.00'))

    def test_write_off_includes_accrued_interest_line_when_present(self):
        loan = self._make_loan(accrued_interest_balance=Decimal('2000.00'))
        self.client.force_login(self.director)
        self.client.post(
            reverse('core:loan_write_off', args=[loan.id]),
            {'reason': 'Client deceased'},
        )
        from core.models import JournalEntry
        entry = JournalEntry.objects.get(reference_number=f'WRITE-OFF-{loan.loan_number}')
        lines = {l.account.gl_code: l for l in entry.lines.all()}
        self.assertIn('1820', lines)
        self.assertEqual(lines['1820'].credit_amount, Decimal('2000.00'))
        self.assertEqual(lines['5910'].debit_amount, Decimal('97600.00'))

    def test_manager_cannot_write_off(self):
        loan = self._make_loan()
        self.client.force_login(self.manager)
        response = self.client.get(reverse('core:loan_write_off', args=[loan.id]))
        self.assertEqual(response.status_code, 403)

    def test_already_written_off_loan_is_rejected(self):
        loan = self._make_loan(status='written_off', outstanding_balance=Decimal('0.00'))
        self.client.force_login(self.director)
        response = self.client.post(
            reverse('core:loan_write_off', args=[loan.id]),
            {'reason': 'x'}, follow=True,
        )
        self.assertContains(response, 'already been written off')
