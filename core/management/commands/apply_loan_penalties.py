"""
Management Command: apply_loan_penalties
=========================================

Run daily via cron to:
  1. Identify loans that are past their due date (+ grace period) with no
     payment received for the current period.
  2. Set their status to 'overdue'.
  3. Create a LoanPenalty record for each qualifying loan (idempotent —
     skips loans that already have a penalty created today).

Cron example (6:00 AM daily):
    0 6 * * * /path/to/venv/bin/python /path/to/manage.py apply_loan_penalties

Usage:
    python manage.py apply_loan_penalties
    python manage.py apply_loan_penalties --dry-run
    python manage.py apply_loan_penalties --rate 0.03   # 3% of installment
    python manage.py apply_loan_penalties --flat 500    # flat ₦500 penalty
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Loan, LoanPenalty, User


class Command(BaseCommand):
    help = "Apply late-payment penalties to overdue loans (run daily via cron)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would happen without writing to the database.",
        )
        parser.add_argument(
            "--rate",
            type=float,
            default=0.02,
            help=(
                "Penalty as a fraction of the installment amount (default: 0.02 = 2%%). "
                "Ignored if --flat is supplied."
            ),
        )
        parser.add_argument(
            "--flat",
            type=float,
            default=None,
            help="Flat penalty amount in ₦ (overrides --rate).",
        )
        parser.add_argument(
            "--user",
            type=str,
            default=None,
            help="Username of the system user to attribute this job to. "
                 "Defaults to the first admin/director user found.",
        )

    def handle(self, *args, **options):
        dry_run  = options["dry_run"]
        rate     = Decimal(str(options["rate"]))
        flat     = Decimal(str(options["flat"])) if options["flat"] else None
        today    = timezone.now().date()

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
            f"Running apply_loan_penalties for {today} "
            f"(system user: {system_user.get_full_name() or system_user.username})"
        )

        # ------------------------------------------------------------------ #
        # Find candidate loans                                                #
        # ------------------------------------------------------------------ #
        # We look at loans that are active (not yet flagged overdue) OR
        # already overdue, where the next repayment date + grace period
        # has passed and no penalty has been applied today yet.
        candidates = (
            Loan.objects.filter(status__in=["active", "overdue"])
            .select_related("loan_product", "client", "branch")
            .exclude(outstanding_balance__lte=Decimal("0.01"))
        )

        applied   = 0
        skipped   = 0
        errors    = 0

        for loan in candidates:
            try:
                result = self._process_loan(
                    loan=loan,
                    today=today,
                    rate=rate,
                    flat=flat,
                    system_user=system_user,
                    dry_run=dry_run,
                )
                if result == "applied":
                    applied += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"  ERROR processing loan {loan.loan_number}: {exc}"
                    )
                )

        # ------------------------------------------------------------------ #
        # Summary                                                             #
        # ------------------------------------------------------------------ #
        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Done. Penalties applied: {applied} | "
                f"Skipped: {skipped} | Errors: {errors}"
            )
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def _process_loan(self, loan, today, rate, flat, system_user, dry_run):
        """
        Evaluate a single loan and apply a penalty if due.

        Returns 'applied' or 'skipped'.
        """
        # 1. Determine overdue threshold (due date + grace period)
        if not loan.next_repayment_date:
            return "skipped"

        grace_days = (
            loan.loan_product.grace_period_days
            if loan.loan_product
            else 0
        )
        overdue_threshold = loan.next_repayment_date + timezone.timedelta(days=grace_days)

        if overdue_threshold >= today:
            # Next due date is in the future — if loan was marked overdue, reset it
            if loan.status == "overdue":
                if not dry_run:
                    loan.status = "active"
                    loan.save(update_fields=["status", "updated_at"])
                self.stdout.write(
                    f"  {loan.loan_number} → status reset to ACTIVE "
                    f"(next due: {loan.next_repayment_date}, threshold: {overdue_threshold})"
                )
            return "skipped"

        # 2. Mark loan as overdue if not already
        if loan.status == "active":
            if not dry_run:
                loan.status = "overdue"
                loan.save(update_fields=["status", "updated_at"])
            self.stdout.write(
                f"  {loan.loan_number} → status set to OVERDUE "
                f"(due: {loan.next_repayment_date}, grace: {grace_days}d)"
            )

        # 3. Idempotency — skip if penalty already created today
        already_penalized = loan.penalties.filter(
            penalty_type="late_payment",
            created_at__date=today,
        ).exists()

        if already_penalized:
            return "skipped"

        # 4. Calculate penalty amount
        if flat is not None:
            penalty_amount = flat
        else:
            penalty_amount = (loan.installment_amount * rate).quantize(Decimal("0.01"))

        if penalty_amount <= Decimal("0.00"):
            return "skipped"

        # 5. Create the penalty
        days_overdue = (today - overdue_threshold).days
        reason = (
            f"Automatic late-payment penalty — {days_overdue} day(s) overdue "
            f"(due date: {loan.next_repayment_date}, grace: {grace_days} day(s))."
        )

        self.stdout.write(
            f"  {loan.loan_number} → penalty ₦{penalty_amount:,.2f} "
            f"({days_overdue}d overdue)"
        )

        if not dry_run:
            LoanPenalty.objects.create(
                loan=loan,
                penalty_type="late_payment",
                amount=penalty_amount,
                reason=reason,
                created_by=system_user,
            )

        return "applied"

    def _get_system_user(self, username):
        """Return the user to attribute automated actions to."""
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                self.stderr.write(
                    self.style.WARNING(f"User '{username}' not found. Falling back.")
                )

        # Prefer an admin, then director, then any staff
        for role in ("admin", "director", "manager", "staff"):
            user = User.objects.filter(
                user_role=role, is_active=True
            ).order_by("date_joined").first()
            if user:
                return user

        return None
