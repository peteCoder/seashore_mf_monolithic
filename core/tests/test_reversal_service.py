"""
Transaction Reversal Service — Integration Tests
==================================================

Proves the full reversal path end-to-end:
  Transaction -> linked JournalEntry(s) -> reverse_transaction()

Covers the bug fixed in this session: JournalEntry.reverse() used to both
(a) mark the original entry status='reversed' (excluded from every trial
balance / account balance query) AND (b) create a second, opposite-direction
journal entry — removing the entry's GL effect twice instead of once.

Also covers the account-side effects reverse_transaction() must apply:
  - loan_repayment reversal -> amount_paid down, outstanding_balance up,
    schedule row reverted (amount_paid + outstanding_amount + status)
  - deposit reversal         -> savings balance down
  - withdrawal reversal      -> savings balance up
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.db.models import Sum

from core.tests.factories import (
    make_branch, make_user, make_client, make_loan_product,
    make_savings_product, make_gl_account,
)
from core.models import (
    Loan, SavingsAccount, LoanRepaymentSchedule,
    Transaction, JournalEntry, JournalEntryLine, AccountType,
)
from core.services.reversal_service import reverse_transaction


def _gl_balance(account, branch):
    t = JournalEntryLine.objects.filter(
        account=account,
        journal_entry__branch=branch,
        journal_entry__status='posted',
    ).aggregate(dr=Sum('debit_amount'), cr=Sum('credit_amount'))
    dr = t['dr'] or Decimal('0')
    cr = t['cr'] or Decimal('0')
    return dr - cr


class ReversalServiceTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='Reversal Test Branch', code='REV001')
        cls.staff = make_user(cls.branch, role='admin', email='rev_admin@test.com')
        cls.rev_client = make_client(cls.branch, cls.staff, email='rev_client@test.com')

        asset_type, _ = AccountType.objects.get_or_create(
            name='asset', defaults={'normal_balance': 'debit'})
        liability_type, _ = AccountType.objects.get_or_create(
            name='liability', defaults={'normal_balance': 'credit'})
        income_type, _ = AccountType.objects.get_or_create(
            name='income', defaults={'normal_balance': 'credit'})

        cls.cash = make_gl_account(gl_code='1010', name='Cash In Hand', account_type=asset_type)
        cls.savings_liability = make_gl_account(gl_code='2010', name='Savings - Regular', account_type=liability_type)
        cls.loan_recv = make_gl_account(gl_code='1810', name='Loan Receivable - Principal', account_type=asset_type)
        cls.interest_income = make_gl_account(gl_code='4010', name='Interest Income', account_type=income_type)

    def _post_je(self, entry_type, lines, txn=None, day=None):
        """Create + post a balanced journal entry with the given (account, dr, cr) lines."""
        je = JournalEntry.objects.create(
            entry_type=entry_type,
            transaction_date=day or date.today(),
            branch=self.branch,
            description=f'Test {entry_type}',
            created_by=self.staff,
            transaction=txn,
            status='draft',
        )
        for account, dr, cr in lines:
            JournalEntryLine.objects.create(
                journal_entry=je, account=account,
                debit_amount=dr, credit_amount=cr,
            )
        je.post(self.staff)
        return je

    # -------------------------------------------------------------------
    # Savings deposit reversal
    # -------------------------------------------------------------------

    def test_deposit_reversal_reduces_balance_and_nets_gl_to_zero(self):
        product = make_savings_product(code='SVPREV1')
        account = SavingsAccount.objects.create(
            client=self.rev_client, savings_product=product, branch=self.branch,
            status='active', balance=Decimal('5000.00'), approval_status='approved',
        )

        txn = Transaction.objects.create(
            transaction_type='deposit', amount=Decimal('2000.00'),
            client=self.rev_client, savings_account=account, branch=self.branch,
            processed_by=self.staff, status='completed',
            balance_before=Decimal('5000.00'), balance_after=Decimal('7000.00'),
            transaction_date=date.today(),
        )
        account.balance = Decimal('7000.00')
        account.save(update_fields=['balance'])

        je = self._post_je(
            'savings_deposit',
            [(self.cash, Decimal('2000.00'), Decimal('0')),
             (self.savings_liability, Decimal('0'), Decimal('2000.00'))],
            txn=txn,
        )

        cash_before = _gl_balance(self.cash, self.branch)

        reverse_transaction(txn=txn, reversed_by=self.staff, reason='Test duplicate deposit')

        account.refresh_from_db()
        txn.refresh_from_db()
        je.refresh_from_db()

        self.assertEqual(account.balance, Decimal('5000.00'))
        self.assertEqual(txn.status, 'reversed')
        self.assertEqual(je.status, 'reversed')

        # GL: the deposit's cash effect must be fully and exactly undone — not doubled.
        cash_after = _gl_balance(self.cash, self.branch)
        self.assertEqual(cash_after, cash_before - Decimal('2000.00'))

        # No second/offsetting journal entry should have been created — only
        # the original JE (now voided) should reference this transaction.
        linked = JournalEntry.objects.filter(transaction=txn)
        self.assertEqual(linked.count(), 1)
        self.assertEqual(linked.first().status, 'reversed')

    # -------------------------------------------------------------------
    # Savings withdrawal reversal
    # -------------------------------------------------------------------

    def test_withdrawal_reversal_increases_balance(self):
        product = make_savings_product(code='SVPREV2')
        account = SavingsAccount.objects.create(
            client=self.rev_client, savings_product=product, branch=self.branch,
            status='active', balance=Decimal('5000.00'), approval_status='approved',
        )

        txn = Transaction.objects.create(
            transaction_type='withdrawal', amount=Decimal('1500.00'),
            client=self.rev_client, savings_account=account, branch=self.branch,
            processed_by=self.staff, status='completed',
            balance_before=Decimal('5000.00'), balance_after=Decimal('3500.00'),
            transaction_date=date.today(),
        )
        account.balance = Decimal('3500.00')
        account.save(update_fields=['balance'])

        self._post_je(
            'savings_withdrawal',
            [(self.savings_liability, Decimal('1500.00'), Decimal('0')),
             (self.cash, Decimal('0'), Decimal('1500.00'))],
            txn=txn,
        )

        reverse_transaction(txn=txn, reversed_by=self.staff, reason='Test wrong withdrawal')

        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('5000.00'))

    # -------------------------------------------------------------------
    # Loan repayment reversal
    # -------------------------------------------------------------------

    def test_loan_repayment_reversal_restores_balance_and_schedule(self):
        loan_product = make_loan_product(code='LNPREV1')
        loan = Loan.objects.create(
            client=self.rev_client, loan_product=loan_product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=1,
            disbursement_method='cash', created_by=self.staff,
            purpose='Test', status='active',
            outstanding_balance=Decimal('100000.00'), amount_paid=Decimal('0.00'),
        )
        schedule = LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=1, due_date=date.today(),
            principal_amount=Decimal('8333.33'), interest_amount=Decimal('1666.67'),
            total_amount=Decimal('10000.00'), outstanding_amount=Decimal('10000.00'),
            amount_paid=Decimal('0.00'), status='pending',
        )

        txn = Transaction.objects.create(
            transaction_type='loan_repayment', amount=Decimal('10000.00'),
            principal_amount=Decimal('8333.33'), interest_amount=Decimal('1666.67'),
            client=self.rev_client, loan=loan, branch=self.branch,
            processed_by=self.staff, status='completed',
            balance_before=Decimal('100000.00'), balance_after=Decimal('90000.00'),
            transaction_date=date.today(),
        )
        # Simulate what the live repayment view would have already applied:
        loan.outstanding_balance = Decimal('90000.00')
        loan.amount_paid = Decimal('10000.00')
        loan.save(update_fields=['outstanding_balance', 'amount_paid'])
        schedule.amount_paid = Decimal('10000.00')
        schedule.outstanding_amount = Decimal('0.00')
        schedule.status = 'paid'
        schedule.save(update_fields=['amount_paid', 'outstanding_amount', 'status'])

        self._post_je(
            'loan_repayment',
            [(self.cash, Decimal('10000.00'), Decimal('0')),
             (self.loan_recv, Decimal('0'), Decimal('8333.33')),
             (self.interest_income, Decimal('0'), Decimal('1666.67'))],
            txn=txn,
        )

        cash_before = _gl_balance(self.cash, self.branch)

        reverse_transaction(txn=txn, reversed_by=self.staff, reason='Duplicate repayment')

        loan.refresh_from_db()
        schedule.refresh_from_db()

        # "deduct from amount paid, add back to repayment/outstanding amount"
        self.assertEqual(loan.amount_paid, Decimal('0.00'))
        self.assertEqual(loan.outstanding_balance, Decimal('100000.00'))

        self.assertEqual(schedule.amount_paid, Decimal('0.00'))
        self.assertEqual(schedule.outstanding_amount, Decimal('10000.00'))
        self.assertIn(schedule.status, ('pending', 'overdue'))

        # GL: cash should drop by exactly the repayment amount, not double it.
        cash_after = _gl_balance(self.cash, self.branch)
        self.assertEqual(cash_after, cash_before - Decimal('10000.00'))

    def test_double_reversal_of_same_journal_entry_is_rejected(self):
        """A JE that is already 'reversed' cannot be reversed again (no re-voiding)."""
        product = make_savings_product(code='SVPREV3')
        account = SavingsAccount.objects.create(
            client=self.rev_client, savings_product=product, branch=self.branch,
            status='active', balance=Decimal('1000.00'), approval_status='approved',
        )
        txn = Transaction.objects.create(
            transaction_type='deposit', amount=Decimal('1000.00'),
            client=self.rev_client, savings_account=account, branch=self.branch,
            processed_by=self.staff, status='completed',
            balance_before=Decimal('0.00'), balance_after=Decimal('1000.00'),
            transaction_date=date.today(),
        )
        je = self._post_je(
            'savings_deposit',
            [(self.cash, Decimal('1000.00'), Decimal('0')),
             (self.savings_liability, Decimal('0'), Decimal('1000.00'))],
            txn=txn,
        )
        reverse_transaction(txn=txn, reversed_by=self.staff, reason='dup')

        je.refresh_from_db()
        with self.assertRaises(ValueError):
            je.reverse(reversed_by=self.staff, reason='second attempt')
