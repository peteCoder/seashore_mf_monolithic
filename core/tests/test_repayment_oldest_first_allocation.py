"""
Tests for Loan.record_repayment() payment allocation.

Regression coverage for a reported bug: a payment used to "anchor" to
whichever schedule row's due_date was closest to the payment date,
skipping over older overdue/partial rows entirely (they were "intentionally
skipped" per the old code comment). In practice this let arrears pile up
in the repayment tracker forever, since normal repayment posting never
reached back to clear them — only manually running
`rebuild_loan_schedules` (which allocates oldest-first) fixed it.
record_repayment() now always fills the oldest unpaid/overdue row first,
matching rebuild_loan_schedules's _compute_allocation().
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestRecordRepaymentOldestFirstAllocation(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='ROF001')
        cls.staff = make_user(cls.branch, role='staff', email='rof_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='rof_client@test.com')
        cls.product = make_loan_product(code='ROFP001')

    def _make_active_loan(self, **kwargs):
        defaults = dict(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=8,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('59000.00'),  # 8 * 7375, matches screenshot-style rows
        )
        defaults.update(kwargs)
        return Loan.objects.create(**defaults)

    def _make_row(self, loan, n, due_date, amount_paid=Decimal('0.00'), status='pending'):
        return LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=n, due_date=due_date,
            principal_amount=Decimal('6250.00'), interest_amount=Decimal('1125.00'),
            total_amount=Decimal('7375.00'), amount_paid=amount_paid, status=status,
        )

    def test_payment_near_a_later_row_still_clears_the_older_overdue_row_first(self):
        """
        Exact scenario from the reported bug: rows 1-3 paid, row 4 overdue
        (unpaid), row 5 due later. A payment made on/near row 5's due date
        must still go to row 4 first, not skip straight to row 5.
        """
        today = timezone.localdate()
        loan = self._make_active_loan()

        row1 = self._make_row(loan, 1, today - timedelta(weeks=4), amount_paid=Decimal('7375.00'), status='paid')
        row2 = self._make_row(loan, 2, today - timedelta(weeks=3), amount_paid=Decimal('7375.00'), status='paid')
        row3 = self._make_row(loan, 3, today - timedelta(weeks=2), amount_paid=Decimal('7375.00'), status='paid')
        row4 = self._make_row(loan, 4, today - timedelta(weeks=1), status='overdue')  # unpaid, overdue
        row5 = self._make_row(loan, 5, today, status='pending')  # due today

        # record_repayment() now recomputes the WHOLE schedule from
        # loan.amount_paid + this payment (self-healing allocation — see
        # core/utils/repayment_allocation.py), rather than only patching
        # whatever rows are currently unpaid. So the ₦22,125 already
        # reflected in rows 1-3 must also be reflected in loan.amount_paid,
        # or the reallocation has no way to know that money exists.
        loan.amount_paid = Decimal('22125.00')  # 3 x 7375, matching rows 1-3
        loan.save(update_fields=['amount_paid'])

        # Payment posted with a transaction_date matching row 5, not row 4 —
        # this is exactly what used to anchor to row 5 and skip row 4.
        loan.record_repayment(
            amount=Decimal('7375.00'), processed_by=self.staff,
            transaction_date=row5.due_date,
        )

        row4.refresh_from_db()
        row5.refresh_from_db()
        self.assertEqual(row4.status, 'paid')
        self.assertEqual(row4.amount_paid, Decimal('7375.00'))
        # Row 5 must remain untouched — the payment only covered row 4.
        self.assertEqual(row5.status, 'pending')
        self.assertEqual(row5.amount_paid, Decimal('0.00'))

    def test_large_payment_fills_multiple_overdue_rows_in_order(self):
        today = timezone.localdate()
        loan = self._make_active_loan()

        row1 = self._make_row(loan, 1, today - timedelta(weeks=2), status='overdue')
        row2 = self._make_row(loan, 2, today - timedelta(weeks=1), status='overdue')
        row3 = self._make_row(loan, 3, today, status='pending')

        # Enough to clear rows 1 and 2 fully, with nothing left for row 3.
        loan.record_repayment(
            amount=Decimal('14750.00'), processed_by=self.staff,
            transaction_date=today,
        )

        row1.refresh_from_db()
        row2.refresh_from_db()
        row3.refresh_from_db()
        self.assertEqual(row1.status, 'paid')
        self.assertEqual(row2.status, 'paid')
        self.assertEqual(row3.status, 'pending')
        self.assertEqual(row3.amount_paid, Decimal('0.00'))

    def test_partial_payment_only_partially_clears_oldest_row(self):
        today = timezone.localdate()
        loan = self._make_active_loan()

        row1 = self._make_row(loan, 1, today - timedelta(weeks=1), status='overdue')
        row2 = self._make_row(loan, 2, today, status='pending')

        loan.record_repayment(
            amount=Decimal('3000.00'), processed_by=self.staff, transaction_date=today,
        )

        row1.refresh_from_db()
        row2.refresh_from_db()
        self.assertEqual(row1.status, 'partial')
        self.assertEqual(row1.amount_paid, Decimal('3000.00'))
        self.assertEqual(row2.status, 'pending')
        self.assertEqual(row2.amount_paid, Decimal('0.00'))
