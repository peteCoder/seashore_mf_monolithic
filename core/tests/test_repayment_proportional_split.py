"""
Tests for Loan.record_repayment()'s principal/interest split.

Regression coverage for a reported inconsistency: the split used to be
computed by walking the repayment schedule row-by-row (interest owed on
that row first, then principal, with a ₦100 "denomination tolerance" rule
deciding where a rounding overshoot landed). Because field collections are
almost always rounded figures (e.g. ₦5,000 collected against a ₦4,916.67
scheduled installment), real data showed the same ₦83.33-style overshoot
landing in *interest* on some repayments and *principal* on others,
depending on exactly how the payment lined up against the schedule table.

record_repayment() now derives principal/interest from a single, fixed
ratio per loan (total_interest / total_repayment) applied directly to
whatever amount was actually collected. There is no "leftover" any more —
every naira collected is split in the same proportion, regardless of how
it compares to the scheduled installment amount. Schedule-row bookkeeping
(which installment is "paid", used for arrears/PAR/next-due-date tracking)
is intentionally decoupled from this split — see
test_repayment_oldest_first_allocation.py for that behaviour.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestRecordRepaymentProportionalSplit(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(name='PropSplit Branch', code='PSP001')
        cls.staff = make_user(cls.branch, role='staff', email='psp_staff@test.com')
        cls.client_obj = make_client(cls.branch, cls.staff, email='psp_client@test.com')
        cls.product = make_loan_product(code='PSPP001')

    def _make_loan(self, **kwargs):
        # ₦100,000 principal, flat 3%/month × 6 months.
        # Loan.save() unconditionally recomputes total_interest/total_repayment/
        # outstanding_balance from principal_amount + loan_product + duration on
        # every create (see Loan.save() -> calculate_loan_details()), so those
        # three fields can't be set directly via objects.create() kwargs — they
        # come out as 100000 * 0.03 * 6 = 18,000 interest / 118,000 repayment,
        # fixed ratio 18000/118000 ≈ 15.254237%, regardless of what's passed.
        defaults = dict(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=6,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
        )
        defaults.update(kwargs)
        loan = Loan.objects.create(**defaults)
        # These tests create an already-'active' loan directly, skipping the
        # normal pending_approval -> approved -> disburse() lifecycle — it's
        # disburse() that sets outstanding_balance = total_repayment in real
        # usage (a brand-new loan legitimately has outstanding_balance=0
        # until money actually goes out). Reproduce that step explicitly so
        # record_repayment()'s outstanding-balance check has something to
        # work against.
        loan.outstanding_balance = loan.total_repayment
        loan.save(update_fields=['outstanding_balance'])
        return loan

    def _make_row(self, loan, n, due_date, principal, interest, total, status='pending'):
        return LoanRepaymentSchedule.objects.create(
            loan=loan, installment_number=n, due_date=due_date,
            principal_amount=principal, interest_amount=interest,
            total_amount=total, amount_paid=Decimal('0.00'), status=status,
        )

    def test_split_is_the_loan_ratio_applied_to_the_actual_amount_paid(self):
        """
        A repayment that doesn't correspond to any single installment amount
        still splits by the loan's fixed interest:principal ratio.
        """
        loan = self._make_loan()
        # Row's own principal/interest are deliberately NOT in the loan's
        # ratio — proving they're no longer read for the split.
        self._make_row(
            loan, 1, timezone.localdate(),
            principal=Decimal('4000.00'), interest=Decimal('1000.00'),
            total=Decimal('5000.00'),
        )

        txn = loan.record_repayment(
            amount=Decimal('5000.00'), processed_by=self.staff,
            transaction_date=timezone.localdate(),
        )

        # 5000 * (18000/118000) = 762.7118... -> 762.71
        self.assertEqual(txn.interest_amount, Decimal('762.71'))
        self.assertEqual(txn.principal_amount, Decimal('4237.29'))
        self.assertEqual(txn.principal_amount + txn.interest_amount, txn.amount)

    def test_rounded_overpayment_is_not_specially_routed_to_either_bucket(self):
        """
        The exact real-world pattern that was inconsistent: a schedule row
        for ₦4,916.67 (₦4,166.67 principal + ₦750 interest), collected as a
        rounded ₦5,000. Old behaviour, depending on which code path ran,
        gave either (750 / 4250) or (833.33 / 4166.67). Neither should occur
        now — the split must be identical to any other ₦5,000 repayment on
        this loan.
        """
        loan = self._make_loan()
        row = self._make_row(
            loan, 1, timezone.localdate(),
            principal=Decimal('4166.67'), interest=Decimal('750.00'),
            total=Decimal('4916.67'),
        )

        txn = loan.record_repayment(
            amount=Decimal('5000.00'), processed_by=self.staff,
            transaction_date=timezone.localdate(),
        )

        self.assertEqual(txn.interest_amount, Decimal('762.71'))
        self.assertEqual(txn.principal_amount, Decimal('4237.29'))
        self.assertNotEqual((txn.principal_amount, txn.interest_amount),
                             (Decimal('4250.00'), Decimal('750.00')))
        self.assertNotEqual((txn.principal_amount, txn.interest_amount),
                             (Decimal('4166.67'), Decimal('833.33')))

        # Row bookkeeping is unaffected by the split: the row is fully paid
        # (capped at its own total, per the DB CHECK constraint) regardless
        # of how the payment was divided between principal and interest.
        row.refresh_from_db()
        self.assertEqual(row.status, 'paid')
        self.assertEqual(row.amount_paid, Decimal('4916.67'))

    def test_principal_and_interest_always_reconcile_to_the_amount_paid(self):
        """No rounding drift for a range of odd amounts."""
        loan = self._make_loan()
        for n, amount in enumerate(
            [Decimal('1.00'), Decimal('12345.67'), Decimal('99999.99')], start=1
        ):
            self._make_row(
                loan, n, timezone.localdate() + timedelta(days=n),
                principal=Decimal('0.00'), interest=Decimal('0.00'),
                total=amount,
            )

        for amount in [Decimal('1.00'), Decimal('12345.67'), Decimal('99999.99')]:
            txn = loan.record_repayment(
                amount=amount, processed_by=self.staff,
                transaction_date=timezone.localdate(),
            )
            self.assertEqual(txn.principal_amount + txn.interest_amount, amount)

    def test_zero_total_repayment_does_not_crash_and_treats_all_as_principal(self):
        """Defensive: a loan with no total_repayment set falls back to ratio 0."""
        loan = self._make_loan()
        # Loan.save() recomputes total_interest/total_repayment on every create,
        # so force the zero-repayment edge case via a bare queryset update
        # (bypasses save()) rather than fighting the recalculation.
        Loan.objects.filter(pk=loan.pk).update(
            total_interest=Decimal('0.00'), total_repayment=Decimal('0.00'),
        )
        loan.refresh_from_db()
        self._make_row(
            loan, 1, timezone.localdate(),
            principal=Decimal('0.00'), interest=Decimal('0.00'),
            total=Decimal('5000.00'),
        )

        txn = loan.record_repayment(
            amount=Decimal('5000.00'), processed_by=self.staff,
            transaction_date=timezone.localdate(),
        )

        self.assertEqual(txn.interest_amount, Decimal('0.00'))
        self.assertEqual(txn.principal_amount, Decimal('5000.00'))
