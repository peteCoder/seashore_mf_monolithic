"""
Tests for the self-healing schedule reallocation in Loan.record_repayment().

Regression coverage for a reported bug: an older allocation path could
"anchor" a payment to whichever schedule row's due_date was closest to the
payment date, skipping over older overdue/partial rows entirely. That left
loans with schedules like:

    Row 7   Partial
    Row 8   Overdue     (unpaid — skipped)
    Row 9   Overdue     (unpaid — skipped)
    Row 10  Overdue     (unpaid — skipped)
    Row 11  Overdue     (unpaid — skipped)
    Row 12  Paid        (payment anchored here instead of row 8)

record_repayment() now recomputes the ENTIRE schedule from the loan's total
amount received on every call — oldest row first — via
core.utils.repayment_allocation.allocate_schedule_from_total(). A row
wrongly marked 'paid' has no special protection: if the oldest-first math
says the money hasn't actually reached it yet, it gets pulled back to
'pending'/'overdue' and the money goes to the rows that were skipped.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product
from core.utils.repayment_allocation import allocate_schedule_from_total


class TestAllocateScheduleFromTotal(TestCase):
    """Unit tests for the pure allocation function, no DB/Loan involved."""

    def _rows(self, loan, statuses_and_paid):
        rows = []
        for n, (status, paid) in enumerate(statuses_and_paid, start=1):
            rows.append(LoanRepaymentSchedule.objects.create(
                loan=loan, installment_number=n,
                due_date=timezone.localdate() + timedelta(weeks=n),
                principal_amount=Decimal('900.00'), interest_amount=Decimal('100.00'),
                total_amount=Decimal('1000.00'), amount_paid=paid, status=status,
            ))
        return rows

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='SelfHeal Branch', code='SHB001')
        cls.staff = make_user(cls.branch, role='staff', email='shb_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='shb_client@test.com')
        cls.product = make_loan_product(code='SHBP001')

    def _bare_loan(self):
        # Not saved through the normal lifecycle — these unit tests only
        # need somewhere to hang LoanRepaymentSchedule rows via FK.
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('10000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
        )
        return loan

    def test_a_wrongly_paid_later_row_is_pulled_back(self):
        """
        The exact real-world pattern: row 3 wrongly 'paid' while rows 1-2
        are untouched. Total actually received (1000) only covers row 1.
        """
        loan = self._bare_loan()
        rows = self._rows(loan, [
            ('pending', Decimal('0.00')),   # row 1 — should end up paid
            ('overdue', Decimal('0.00')),   # row 2 — should stay unpaid
            ('paid',    Decimal('1000.00')),  # row 3 — wrongly paid, must be pulled back
        ])

        changes, next_due = allocate_schedule_from_total(
            rows, total_received=Decimal('1000.00'), completion_date=timezone.localdate(),
        )
        by_row = {row.id: new_paid for row, new_paid in changes}

        self.assertEqual(by_row[rows[0].id], Decimal('1000.00'))  # row 1 now fully paid
        self.assertNotIn(rows[1].id, by_row)                      # row 2 unchanged (still 0)
        self.assertEqual(by_row[rows[2].id], Decimal('0.00'))     # row 3 corrected back to 0
        self.assertIsNone(rows[2].paid_date)                      # stale paid_date cleared
        self.assertEqual(next_due, rows[1].due_date)               # row 2 is next due

    def test_fully_paid_loan_has_no_next_due(self):
        loan = self._bare_loan()
        rows = self._rows(loan, [('pending', Decimal('0.00'))])
        changes, next_due = allocate_schedule_from_total(
            rows, total_received=Decimal('1000.00'), completion_date=timezone.localdate(),
        )
        self.assertIsNone(next_due)


class TestRecordRepaymentSelfHeals(TestCase):
    """Integration test: record_repayment() itself repairs a corrupted schedule."""

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='SelfHeal2 Branch', code='SHB002')
        cls.staff = make_user(cls.branch, role='staff', email='shb2_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='shb2_client@test.com')
        cls.product = make_loan_product(code='SHBP002')

    def test_next_repayment_pulls_a_wrongly_paid_row_back_and_fills_the_real_gap(self):
        """
        Reproduces /loans/7542ded9.../ shape: a later row was wrongly marked
        paid while earlier rows sat untouched. The NEXT repayment recorded
        on the loan — a normal, unrelated payment — must correct this,
        without anyone running a manual rebuild.
        """
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
        )
        today = timezone.localdate()
        row1 = LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=1, due_date=today - timedelta(weeks=2),
            principal_amount=Decimal('4166.67'), interest_amount=Decimal('750.00'),
            total_amount=Decimal('4916.67'), amount_paid=Decimal('0.00'), status='overdue',
        )
        row2 = LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=2, due_date=today - timedelta(weeks=1),
            principal_amount=Decimal('4166.67'), interest_amount=Decimal('750.00'),
            total_amount=Decimal('4916.67'), amount_paid=Decimal('0.00'), status='overdue',
        )
        # Row 3 wrongly marked paid (simulating the old anchor-to-date bug) —
        # money that should have gone to rows 1-2 landed here instead.
        row3 = LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=3, due_date=today,
            principal_amount=Decimal('4166.67'), interest_amount=Decimal('750.00'),
            total_amount=Decimal('4916.67'), amount_paid=Decimal('4916.67'),
            status='paid', paid_date=today,
        )
        # loan.amount_paid must reflect the real total received so far —
        # only row 3's payment has actually happened.
        loan.amount_paid = Decimal('4916.67')
        loan.outstanding_balance = Decimal('9833.34')  # 2 remaining installments
        loan.save(update_fields=['amount_paid', 'outstanding_balance'])

        # A brand-new, unrelated payment comes in.
        loan.record_repayment(
            amount=Decimal('4916.67'), processed_by=self.staff, transaction_date=today,
        )

        row1.refresh_from_db()
        row2.refresh_from_db()
        row3.refresh_from_db()

        # Total received is now 4916.67 + 4916.67 = 9833.34 -> exactly two
        # full installments. Oldest-first, that's rows 1 and 2 fully paid;
        # row 3's wrongly-applied money is pulled back to nothing.
        self.assertEqual(row1.status, 'paid')
        self.assertEqual(row1.amount_paid, Decimal('4916.67'))
        self.assertEqual(row2.status, 'paid')
        self.assertEqual(row2.amount_paid, Decimal('4916.67'))
        # Row 3 is due exactly today, not in the past, so an unpaid row
        # is 'pending' rather than 'overdue' (see computed_status).
        self.assertEqual(row3.status, 'pending')
        self.assertEqual(row3.amount_paid, Decimal('0.00'))
        self.assertIsNone(row3.paid_date)

        # No more "Paid after Overdue" — paid rows are a clean prefix.
        statuses = [row1.status, row2.status, row3.status]
        first_non_paid = next(i for i, s in enumerate(statuses) if s != 'paid')
        self.assertTrue(all(s == 'paid' for s in statuses[:first_non_paid]))
        self.assertTrue(all(s != 'paid' for s in statuses[first_non_paid:]))
