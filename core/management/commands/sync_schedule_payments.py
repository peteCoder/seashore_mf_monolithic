"""
Management Command: sync_schedule_payments
==========================================

Repairs LoanRepaymentSchedule rows whose status, outstanding_amount, or
amount_paid fields are inconsistent with reality.

TWO CLASSES OF PROBLEM FIXED
------------------------------

1. STALE STATUS  (most common)
   Rows with status='pending' whose due_date has already passed and have no
   payment. The status should be 'overdue' but save() was never called after
   the date moved into the past.
   Fix: bulk UPDATE status='overdue' for all such rows in one SQL statement.

2. AMOUNT-PAID DESYNC  (historical, pre-row-tracking era)
   Rows whose amount_paid is lower than the share of loan.amount_paid that
   should have been allocated to them. Happens when repayments were recorded
   before per-row tracking was in place.
   Fix: re-allocate loan.amount_paid across rows in installment order and
   update any row whose amount_paid is below the expected allocation.

ALSO FIXES
----------
   Rows where outstanding_amount ≠ (total_amount + penalty - amount_paid).
   These can arise if penalty_amount was added after the last save().

Safe to re-run — all checks are idempotent.

Usage
-----
    python manage.py sync_schedule_payments            # live run
    python manage.py sync_schedule_payments --dry-run  # preview only
    python manage.py sync_schedule_payments --loan-id <UUID>  # one loan
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import F, Prefetch
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule


class Command(BaseCommand):
    help = "Sync LoanRepaymentSchedule status, outstanding_amount, and amount_paid with actual data."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without writing to the database.',
        )
        parser.add_argument(
            '--loan-id',
            metavar='UUID',
            help='Process a single loan only.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        loan_id = options.get('loan_id')
        today   = timezone.now().date()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        total_fixed = 0

        # ── Phase 1: Stale pending->overdue status ─────────────────────────────
        total_fixed += self._fix_stale_status(today, dry_run, loan_id)

        # ── Phase 2: Amount-paid desync + wrong outstanding_amount ────────────
        total_fixed += self._fix_amount_desync(today, dry_run, loan_id)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {'Would fix' if dry_run else 'Fixed'} {total_fixed} row(s) total.\n"
        ))

    # -------------------------------------------------------------------------
    # Phase 1 — stale status
    # -------------------------------------------------------------------------

    def _fix_stale_status(self, today, dry_run, loan_id):
        """
        Find all rows where:
          • status = 'pending'      (never updated since due date passed)
          • due_date < today        (the installment is now past-due)
          • amount_paid = 0         (no payment was recorded)
          • outstanding_amount > 0  (something is still owed)

        These should all be status='overdue'.
        Use a single bulk UPDATE — no Python loops needed.
        """
        qs = LoanRepaymentSchedule.objects.filter(
            status='pending',
            due_date__lt=today,
            amount_paid=Decimal('0.00'),
            outstanding_amount__gt=0,
            loan__status__in=['active', 'overdue', 'disbursed'],
        )
        if loan_id:
            qs = qs.filter(loan_id=loan_id)

        count = qs.count()
        if count == 0:
            self.stdout.write("Phase 1 (stale status): nothing to fix.")
            return 0

        if dry_run:
            self.stdout.write(f"Phase 1 (stale status): would update {count} row(s) pending->overdue")
            for row in qs.select_related('loan').order_by('loan__loan_number', 'installment_number')[:50]:
                self.stdout.write(
                    f"  [DRY] {row.loan.loan_number} row#{row.installment_number} "
                    f"due={row.due_date}  pending -> overdue"
                )
            if count > 50:
                self.stdout.write(f"  ... and {count - 50} more")
        else:
            updated = qs.update(status='overdue')
            self.stdout.write(
                self.style.SUCCESS(f"Phase 1 (stale status): updated {updated} row(s) pending->overdue")
            )

        return count

    # -------------------------------------------------------------------------
    # Phase 2 — amount-paid desync + wrong outstanding_amount
    # -------------------------------------------------------------------------

    def _fix_amount_desync(self, today, dry_run, loan_id):
        """
        For every loan with amount_paid > 0, re-allocate loan.amount_paid
        across schedule rows in installment order.  Update any row whose
        stored amount_paid is lower than the allocation.

        Also fixes rows where outstanding_amount ≠ (total + penalty - amount_paid).
        """
        schedule_prefetch = Prefetch(
            'repayment_schedule',
            queryset=LoanRepaymentSchedule.objects.order_by('installment_number'),
            to_attr='ordered_schedule',
        )
        loan_qs = Loan.objects.filter(
            status__in=['active', 'overdue', 'disbursed', 'completed'],
            amount_paid__gt=0,
        ).prefetch_related(schedule_prefetch)

        if loan_id:
            loan_qs = loan_qs.filter(id=loan_id)

        total_loans   = loan_qs.count()
        updated_rows  = 0
        loans_touched = 0

        scope = f'loan {loan_id}' if loan_id else f'{total_loans} loans with amount_paid > 0'
        self.stdout.write(f"\nPhase 2 (amount desync): scanning {scope} ...")

        for loan in loan_qs:
            rows = loan.ordered_schedule
            if not rows:
                continue

            if loan.status == 'completed':
                changes = self._mark_all_paid(loan, rows, today, dry_run)
            else:
                changes = self._allocate_and_fix(loan, rows, today, dry_run)

            if changes:
                loans_touched += 1
                updated_rows  += changes

        self.stdout.write(
            self.style.SUCCESS(
                f"Phase 2 (amount desync): "
                f"{'would update' if dry_run else 'updated'} "
                f"{updated_rows} row(s) across {loans_touched} loan(s)"
            )
        )
        return updated_rows

    def _mark_all_paid(self, loan, rows, today, dry_run):
        """Mark every schedule row for a completed loan as fully paid."""
        paid_date = (
            loan.completion_date.date() if loan.completion_date else today
        )
        changed = 0
        for row in rows:
            if row.status == 'paid' and row.outstanding_amount == Decimal('0.00'):
                continue
            if dry_run:
                self.stdout.write(
                    f"  [DRY] {loan.loan_number} row#{row.installment_number}: "
                    f"mark paid (status={row.status}, outstanding={row.outstanding_amount})"
                )
            else:
                row.amount_paid  = row.total_amount + row.penalty_amount
                row.paid_date    = paid_date
                row.save(update_fields=['amount_paid', 'paid_date', 'outstanding_amount', 'status', 'updated_at'])
            changed += 1
        return changed

    def _allocate_and_fix(self, loan, rows, today, dry_run):
        """
        Re-allocate loan.amount_paid across rows.  Update a row if:
          • amount_paid < expected allocation  (under-recorded payment)
          • outstanding_amount ≠ (total + penalty - amount_paid)  (stale outstanding)
        """
        remaining = loan.amount_paid
        changed   = 0

        for row in rows:
            row_total = row.total_amount + row.penalty_amount

            # How much of loan.amount_paid should be allocated to this row
            if remaining > Decimal('0.00'):
                allocated  = min(remaining, row_total)
                remaining -= allocated
            else:
                allocated = Decimal('0.00')

            expected_outstanding = max(row_total - allocated, Decimal('0.00'))

            amount_wrong      = row.amount_paid < allocated
            outstanding_wrong = row.outstanding_amount != expected_outstanding

            if not amount_wrong and not outstanding_wrong:
                continue

            if dry_run:
                parts = []
                if amount_wrong:
                    parts.append(f"amount_paid {row.amount_paid}->{allocated}")
                if outstanding_wrong:
                    parts.append(f"outstanding {row.outstanding_amount}->{expected_outstanding}")
                self.stdout.write(
                    f"  [DRY] {loan.loan_number} row#{row.installment_number}: "
                    + ", ".join(parts)
                )
            else:
                if amount_wrong:
                    row.amount_paid = allocated
                    if allocated >= row_total and not row.paid_date:
                        row.paid_date = today
                elif outstanding_wrong:
                    # amount_paid is fine; just recalculate outstanding + status
                    pass   # save() will fix it
                row.save(update_fields=['amount_paid', 'paid_date', 'outstanding_amount', 'status', 'updated_at'])
            changed += 1

        return changed
