"""
Management Command: accrue_loan_interest
=========================================

Run at month-end via cron to:
  1. For each active/overdue loan, calculate the interest accrued during
     the month (outstanding_balance × monthly_interest_rate).
  2. Post a journal entry: Dr 1820 Interest Receivable / Cr 4010 Interest Income.
  3. Record is idempotent — uses reference format "ACCRUAL-YYYY-MM-{loan_number}"
     so the same loan cannot be accrued twice for the same month.

Note: This records interest on an ACCRUAL BASIS. When the borrower actually
pays, the repayment journal (Dr Cash / Cr Loan Receivable + Interest Income)
should be accompanied by the reversal of this accrual. A full reversal workflow
is not implemented here — this command is suitable for management-reporting
purposes where you want to see earned-but-unreceived income on the balance sheet.

Cron example (last day of month at 11:55 PM):
    55 23 28-31 * * /path/to/venv/bin/python /path/to/manage.py accrue_loan_interest

Or a safer approach — run on the 1st of each month for the PREVIOUS month:
    0 8 1 * * /path/to/venv/bin/python /path/to/manage.py accrue_loan_interest

Usage:
    python manage.py accrue_loan_interest
    python manage.py accrue_loan_interest --year 2026 --month 1
    python manage.py accrue_loan_interest --dry-run
    python manage.py accrue_loan_interest --user system_admin
"""

import calendar
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import JournalEntry, Loan, User
from core.utils.accounting_helpers import post_loan_interest_accrual_journal


class Command(BaseCommand):
    help = "Post month-end loan interest accrual journals (run monthly via cron)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would happen without writing to the database.",
        )
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="Year of the accrual period (default: previous month's year).",
        )
        parser.add_argument(
            "--month",
            type=int,
            default=None,
            help="Month of the accrual period 1-12 (default: previous month).",
        )
        parser.add_argument(
            "--user",
            type=str,
            default=None,
            help="Username of the system user to attribute this job to.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today   = timezone.now().date()

        # Determine the accrual period (default: previous month)
        if options["year"] and options["month"]:
            year  = options["year"]
            month = options["month"]
        else:
            # Previous month
            first_of_this_month = today.replace(day=1)
            prev = first_of_this_month - timezone.timedelta(days=1)
            year  = prev.year
            month = prev.month

        # Validate month range
        if not (1 <= month <= 12):
            self.stderr.write(self.style.ERROR(f"Invalid month: {month}"))
            return

        # Last day of the accrual month
        last_day = calendar.monthrange(year, month)[1]
        accrual_date      = timezone.datetime(year, month, last_day).date()
        accrual_reference = f"ACCRUAL-{year}-{month:02d}"

        system_user = self._get_system_user(options["user"])
        if system_user is None:
            self.stderr.write(
                self.style.ERROR(
                    "No admin or director user found. "
                    "Create one first or pass --user <username>."
                )
            )
            return

        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Running accrue_loan_interest for {year}-{month:02d} "
            f"(accrual date: {accrual_date}) "
            f"(system user: {system_user.get_full_name() or system_user.username})"
        )

        # ------------------------------------------------------------------ #
        # Candidate loans: active or overdue, with outstanding balance        #
        # ------------------------------------------------------------------ #
        loans = (
            Loan.objects.filter(status__in=["active", "overdue"])
            .select_related("loan_product", "client", "branch")
            .exclude(outstanding_balance__lte=Decimal("0.01"))
        )

        posted  = 0
        skipped = 0
        errors  = 0

        for loan in loans:
            try:
                result = self._process_loan(
                    loan=loan,
                    accrual_date=accrual_date,
                    accrual_reference=accrual_reference,
                    system_user=system_user,
                    dry_run=dry_run,
                )
                if result == "posted":
                    posted += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"  ERROR on loan {loan.loan_number}: {exc}"
                    )
                )

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Done. Accruals posted: {posted} | "
                f"Skipped: {skipped} | Errors: {errors}"
            )
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def _process_loan(self, loan, accrual_date, accrual_reference, system_user, dry_run):
        """
        Post interest accrual for a single loan.

        Returns 'posted' or 'skipped'.
        """
        loan_ref = f"{accrual_reference}-{loan.loan_number}"

        # Idempotency: skip if we already posted this accrual for this loan
        already_posted = JournalEntry.objects.filter(
            reference_number=loan_ref,
        ).exists()

        if already_posted:
            return "skipped"

        # Calculate accrued interest for the period
        # Simple: outstanding_balance × monthly_rate
        monthly_rate    = loan.monthly_interest_rate  # e.g. 0.035
        accrued_interest = (
            loan.outstanding_balance * Decimal(str(monthly_rate))
        ).quantize(Decimal("0.01"))

        if accrued_interest <= Decimal("0.00"):
            return "skipped"

        self.stdout.write(
            f"  {loan.loan_number} — outstanding ₦{loan.outstanding_balance:,.2f} "
            f"× {float(monthly_rate) * 100:.2f}% "
            f"= ₦{accrued_interest:,.2f} accrued"
        )

        if dry_run:
            return "posted"

        post_loan_interest_accrual_journal(
            loan=loan,
            accrued_interest=accrued_interest,
            processed_by=system_user,
            accrual_reference=accrual_reference,
            accrual_date=accrual_date,
        )

        # Track the accrued amount on the loan so that record_repayment()
        # knows how much to clear from 1820 instead of booking to 4010.
        loan.accrued_interest_balance = (
            loan.accrued_interest_balance + accrued_interest
        )
        loan.save(update_fields=["accrued_interest_balance", "updated_at"])

        return "posted"

    def _get_system_user(self, username):
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                self.stderr.write(
                    self.style.WARNING(f"User '{username}' not found. Falling back.")
                )

        for role in ("admin", "director", "manager", "staff"):
            user = User.objects.filter(
                user_role=role, is_active=True
            ).order_by("date_joined").first()
            if user:
                return user

        return None
