"""
Management Command: sync_schedule_payments
==========================================
One-time (and safe-to-rerun) data repair that reconciles
LoanRepaymentSchedule rows whose amount_paid / outstanding_amount /
status fields were never updated because payments were recorded before
the per-row tracking fix was applied.

Algorithm
---------
For every active, overdue, disbursed or completed loan that has
amount_paid > 0:

1. Completed loans  → all schedule rows are fully paid.
   Set each row: amount_paid = total_amount, outstanding_amount = 0,
   status = 'paid', paid_date = loan.completion_date or today.

2. Partially-paid loans → allocate loan.amount_paid across rows in
   installment order (earliest first), exactly mirroring
   record_repayment() logic.
   Only rows whose per-row amount_paid is *less* than what the
   allocation says are updated — rows already correct are left alone.

Usage
-----
    python manage.py sync_schedule_payments            # live run
    python manage.py sync_schedule_payments --dry-run  # preview only
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule


class Command(BaseCommand):
    help = "Sync LoanRepaymentSchedule rows with actual loan payment data."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without writing to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        loans = Loan.objects.filter(
            status__in=['active', 'overdue', 'disbursed', 'completed'],
            amount_paid__gt=0,
        ).prefetch_related('repayment_schedule')

        total_loans = loans.count()
        updated_rows = 0
        loans_touched = 0

        self.stdout.write(f"Scanning {total_loans} loans with amount_paid > 0 ...\n")

        for loan in loans:
            rows = list(
                loan.repayment_schedule.order_by('installment_number')
            )
            if not rows:
                continue

            if loan.status == 'completed':
                # All instalments should be fully paid
                changes = self._mark_all_paid(loan, rows, today, dry_run)
            else:
                # Allocate loan.amount_paid proportionally across rows
                changes = self._allocate_partial(loan, rows, dry_run)

            if changes:
                loans_touched += 1
                updated_rows += changes

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. {'Would update' if dry_run else 'Updated'} "
                f"{updated_rows} schedule row(s) across {loans_touched} loan(s)."
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mark_all_paid(self, loan, rows, today, dry_run):
        """Mark every schedule row for a completed loan as fully paid."""
        paid_date = (
            loan.completion_date.date()
            if loan.completion_date
            else today
        )
        changed = 0
        for row in rows:
            if row.status == 'paid' and row.outstanding_amount == Decimal('0.00'):
                continue  # already correct
            if dry_run:
                self.stdout.write(
                    f"  [DRY] Loan {loan.loan_number} row #{row.installment_number}: "
                    f"mark paid (was status={row.status}, outstanding={row.outstanding_amount})"
                )
            else:
                row.amount_paid = row.total_amount + row.penalty_amount
                row.paid_date = paid_date
                # Let save() recalculate outstanding_amount and status
                row.save(update_fields=[
                    'amount_paid', 'paid_date',
                    'outstanding_amount', 'status', 'updated_at',
                ])
            changed += 1
        return changed

    def _allocate_partial(self, loan, rows, dry_run):
        """
        Re-allocate loan.amount_paid across schedule rows in order.
        Skips rows that already have the correct amount_paid.
        """
        remaining = loan.amount_paid
        changed = 0

        for row in rows:
            if remaining <= Decimal('0.00'):
                break

            row_total = row.total_amount + row.penalty_amount
            allocated = min(remaining, row_total)
            remaining -= allocated

            # Only touch the row if it's under-recorded
            if row.amount_paid >= allocated:
                continue

            if dry_run:
                self.stdout.write(
                    f"  [DRY] Loan {loan.loan_number} row #{row.installment_number}: "
                    f"amount_paid {row.amount_paid} -> {allocated} "
                    f"(outstanding will become {row_total - allocated})"
                )
            else:
                row.amount_paid = allocated
                if allocated >= row_total and not row.paid_date:
                    row.paid_date = timezone.now().date()
                # Let save() recalculate outstanding_amount and status
                row.save(update_fields=[
                    'amount_paid', 'paid_date',
                    'outstanding_amount', 'status', 'updated_at',
                ])
            changed += 1

        return changed
