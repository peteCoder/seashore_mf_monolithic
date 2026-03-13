"""
Management Command: post_savings_interest
==========================================

Run monthly (or per product frequency) via cron to:
  1. Find all active savings accounts whose interest is due for posting.
  2. Call SavingsAccount.post_interest() to credit interest to the balance.
  3. Post the corresponding journal entry (Dr 5010 / Cr 20xx).

The "due" check respects each product's interest_payment_frequency:
  - monthly    → not posted since start of current month
  - quarterly  → not posted since start of current quarter
  - annually   → not posted since start of current year
  - maturity   → skipped (posted separately at account maturity)

Cron example (1st of every month at 7:00 AM):
    0 7 1 * * /path/to/venv/bin/python /path/to/manage.py post_savings_interest

Usage:
    python manage.py post_savings_interest
    python manage.py post_savings_interest --dry-run
    python manage.py post_savings_interest --frequency monthly
    python manage.py post_savings_interest --user system_admin
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import SavingsAccount, User
from core.utils.accounting_helpers import post_savings_interest_journal


class Command(BaseCommand):
    help = "Credit savings interest to active accounts (run monthly via cron)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would happen without writing to the database.",
        )
        parser.add_argument(
            "--frequency",
            type=str,
            default=None,
            choices=["monthly", "quarterly", "annually"],
            help=(
                "Only process accounts with this interest_payment_frequency. "
                "Default: process all due frequencies."
            ),
        )
        parser.add_argument(
            "--user",
            type=str,
            default=None,
            help="Username of the system user to attribute this job to.",
        )

    def handle(self, *args, **options):
        dry_run   = options["dry_run"]
        frequency = options["frequency"]
        today     = timezone.now().date()

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
            f"Running post_savings_interest for {today} "
            f"(system user: {system_user.get_full_name() or system_user.username})"
        )

        # ------------------------------------------------------------------ #
        # Candidate accounts                                                  #
        # ------------------------------------------------------------------ #
        accounts_qs = (
            SavingsAccount.objects.filter(status="active")
            .select_related("savings_product", "client", "branch")
            .exclude(savings_product__interest_rate_annual__lte=0)
            .exclude(savings_product__interest_payment_frequency="maturity")
        )

        if frequency:
            accounts_qs = accounts_qs.filter(
                savings_product__interest_payment_frequency=frequency
            )

        posted  = 0
        skipped = 0
        errors  = 0

        for account in accounts_qs:
            try:
                result = self._process_account(
                    account=account,
                    today=today,
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
                        f"  ERROR on account {account.account_number}: {exc}"
                    )
                )

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Done. Interest posted: {posted} | "
                f"Skipped: {skipped} | Errors: {errors}"
            )
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def _process_account(self, account, today, system_user, dry_run):
        """
        Post interest to a single account if it is due.

        Returns 'posted' or 'skipped'.
        """
        freq = account.savings_product.interest_payment_frequency

        # Check whether interest is due based on frequency
        if not self._is_interest_due(account, freq, today):
            return "skipped"

        # Calculate the interest
        interest = account.calculate_interest(calculation_date=today)

        if interest <= Decimal("0.00"):
            return "skipped"

        self.stdout.write(
            f"  {account.account_number} ({account.client}) "
            f"→ interest ₦{interest:,.2f} ({freq})"
        )

        if dry_run:
            return "posted"

        # Post interest (updates balance, creates Transaction)
        txn = account.post_interest(processed_by=system_user)

        if txn is None:
            return "skipped"

        # Post the journal entry
        try:
            post_savings_interest_journal(
                savings_account=account,
                interest_amount=interest,
                processed_by=system_user,
                transaction_obj=txn,
                posting_date=today,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                f"Journal entry failed for {account.account_number}: {exc}"
            )
            # We don't re-raise — interest was already credited; journal
            # failure must be fixed separately.

        return "posted"

    def _is_interest_due(self, account, freq, today):
        """
        Return True if interest has not yet been posted for the current period.
        """
        last = account.last_interest_date

        if freq == "monthly":
            period_start = today.replace(day=1)
            return last is None or last < period_start

        if freq == "quarterly":
            # Quarter start: Jan, Apr, Jul, Oct
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            period_start = today.replace(month=quarter_month, day=1)
            return last is None or last < period_start

        if freq == "annually":
            period_start = today.replace(month=1, day=1)
            return last is None or last < period_start

        # 'maturity' — skip in this job
        return False

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
