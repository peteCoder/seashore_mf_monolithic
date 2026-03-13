"""
Accounting Logic Tests
=======================

Tests for:
- validate_journal_balance (debits must equal credits)
- JournalEntryLine model constraints
- JournalEntry status transitions
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.utils.accounting_helpers import validate_journal_balance


# =============================================================================
# validate_journal_balance
# =============================================================================

class TestValidateJournalBalance(TestCase):
    """validate_journal_balance() should raise on imbalanced entries."""

    def test_balanced_entry_passes(self):
        lines = [
            {'debit': Decimal('50000'), 'credit': 0},
            {'debit': 0, 'credit': Decimal('50000')},
        ]
        # Should not raise
        validate_journal_balance(lines)

    def test_multi_line_balanced_passes(self):
        lines = [
            {'debit': Decimal('100000'), 'credit': 0},
            {'debit': 0, 'credit': Decimal('70000')},
            {'debit': 0, 'credit': Decimal('30000')},
        ]
        validate_journal_balance(lines)

    def test_imbalanced_entry_raises(self):
        lines = [
            {'debit': Decimal('50000'), 'credit': 0},
            {'debit': 0, 'credit': Decimal('49000')},   # ₦1,000 short
        ]
        with self.assertRaises(ValidationError):
            validate_journal_balance(lines)

    def test_empty_lines_pass(self):
        # All zeros — technically balanced
        validate_journal_balance([])

    def test_string_amounts_handled(self):
        lines = [
            {'debit': '25000.00', 'credit': '0'},
            {'debit': '0', 'credit': '25000.00'},
        ]
        validate_journal_balance(lines)

    def test_missing_keys_treated_as_zero(self):
        lines = [
            {'debit': 10000},   # no 'credit' key
            {'credit': 10000},  # no 'debit' key
        ]
        validate_journal_balance(lines)

    def test_error_message_contains_amounts(self):
        lines = [
            {'debit': 1000, 'credit': 0},
            {'debit': 0, 'credit': 500},
        ]
        try:
            validate_journal_balance(lines)
            self.fail('Expected ValidationError')
        except ValidationError as exc:
            msg = str(exc)
            self.assertIn('1,000', msg)
            self.assertIn('500', msg)


# =============================================================================
# JournalEntry Model
# =============================================================================

class TestJournalEntryModel(TestCase):
    """
    Basic sanity checks on JournalEntry and JournalEntryLine model constraints.
    These tests use the DB but don't require full loan/savings setup.
    """

    @classmethod
    def setUpTestData(cls):
        from core.tests.factories import make_branch, make_user
        from core.models import JournalEntry, ChartOfAccounts, AccountType, AccountCategory

        cls.branch = make_branch()
        cls.user = make_user(cls.branch, role='admin')

        # Ensure required GL accounts exist
        asset_type = AccountType.objects.filter(name='asset').first()
        if asset_type is None:
            # Minimal fallback — real DB already has these seeded
            return

        cls.cash_acct, _ = ChartOfAccounts.objects.get_or_create(
            gl_code='1010',
            defaults={'account_name': 'Cash In Hand', 'account_type': asset_type, 'is_active': True},
        )
        cls.loan_acct, _ = ChartOfAccounts.objects.get_or_create(
            gl_code='1810',
            defaults={'account_name': 'Loan Receivable - Principal', 'account_type': asset_type, 'is_active': True},
        )

    def _make_journal(self, entry_type='manual'):
        from core.models import JournalEntry
        return JournalEntry.objects.create(
            branch=self.branch,
            entry_type=entry_type,
            transaction_date=__import__('datetime').date.today(),
            description='Test journal entry',
            created_by=self.user,
            status='draft',
        )

    def test_create_draft_journal(self):
        from core.models import JournalEntry
        je = self._make_journal()
        self.assertEqual(je.status, 'draft')
        self.assertIsNotNone(je.id)

    def test_journal_entry_line_debit_credit(self):
        from core.models import JournalEntry, JournalEntryLine
        je = self._make_journal()
        if not hasattr(self, 'cash_acct'):
            self.skipTest('GL accounts not seeded in test DB')

        line = JournalEntryLine.objects.create(
            journal_entry=je,
            account=self.cash_acct,
            debit_amount=Decimal('10000.00'),
            credit_amount=Decimal('0.00'),
            description='Cash debit test',
        )
        self.assertEqual(line.debit_amount, Decimal('10000.00'))
        self.assertEqual(line.credit_amount, Decimal('0.00'))
