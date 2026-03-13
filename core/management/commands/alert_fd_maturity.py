"""
Management Command: alert_fd_maturity
======================================

Run daily via cron to notify staff of fixed-deposit accounts approaching
or past their maturity date.

Who gets notified:
  - The client's assigned_staff (if any)
  - The first active manager in the account's branch (if no assigned staff)
  - Additionally, the admin/director if the account is already past maturity

Idempotency:
  - Checks `Notification` objects for today so a re-run won't spam.
  - Reference used for idempotency check:
    "FD-MATURITY-ALERT-{account_number}-{today}"

Cron example (daily at 7:00 AM):
    0 7 * * * /path/to/venv/bin/python /path/to/manage.py alert_fd_maturity

Usage:
    python manage.py alert_fd_maturity
    python manage.py alert_fd_maturity --days 14        # alert 14 days out
    python manage.py alert_fd_maturity --dry-run
    python manage.py alert_fd_maturity --user system_admin
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import SavingsAccount, Notification, User


class Command(BaseCommand):
    help = "Send maturity alerts for fixed-deposit accounts (run daily via cron)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would happen without writing to the database.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Alert window in days ahead of maturity (default: 30).",
        )
        parser.add_argument(
            "--user",
            type=str,
            default=None,
            help="Username of the system user for fallback attribution.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        days_ahead = options["days"]
        today = timezone.now().date()
        alert_window = today + timedelta(days=days_ahead)

        system_user = self._get_system_user(options["user"])

        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}"
            f"Running alert_fd_maturity for {today} "
            f"(window: {days_ahead} days, alert_until: {alert_window})"
        )

        # Find active FD accounts maturing within the window (or already matured)
        accounts = (
            SavingsAccount.objects.filter(
                status="active",
                savings_product__product_type="fixed",
                maturity_date__lte=alert_window,
            )
            .select_related("client", "branch", "savings_product", "client__assigned_staff")
            .order_by("maturity_date")
        )

        alerted = 0
        skipped = 0
        errors = 0

        for account in accounts:
            try:
                result = self._process_account(
                    account=account,
                    today=today,
                    system_user=system_user,
                    dry_run=dry_run,
                )
                if result == "alerted":
                    alerted += 1
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
                f"{prefix}Done. Alerts sent: {alerted} | Skipped: {skipped} | Errors: {errors}"
            )
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _process_account(self, account, today, system_user, dry_run):
        maturity_date = account.maturity_date
        if not maturity_date:
            return "skipped"

        days_to_maturity = (maturity_date - today).days
        already_matured = days_to_maturity < 0

        # Determine urgency
        is_urgent = already_matured or days_to_maturity <= 7

        if already_matured:
            title = f"Fixed Deposit Matured: {account.account_number}"
            message = (
                f"Fixed deposit account {account.account_number} for "
                f"{account.client.get_full_name()} matured on {maturity_date.strftime('%d %b %Y')} "
                f"({abs(days_to_maturity)} days ago). Please action immediately."
            )
        else:
            title = f"Fixed Deposit Maturing in {days_to_maturity} Day{'s' if days_to_maturity != 1 else ''}"
            message = (
                f"Fixed deposit account {account.account_number} for "
                f"{account.client.get_full_name()} will mature on {maturity_date.strftime('%d %b %Y')} "
                f"({days_to_maturity} day{'s' if days_to_maturity != 1 else ''} remaining). "
                f"Principal: ₦{account.balance:,.2f}."
            )

        # Determine the recipients
        recipients = []
        assigned_staff = account.client.assigned_staff if account.client else None
        if assigned_staff and assigned_staff.is_active:
            recipients.append(assigned_staff)

        # Always also notify the first active manager in the branch
        if account.branch:
            manager = (
                User.objects.filter(
                    branch=account.branch,
                    user_role="manager",
                    is_active=True,
                )
                .order_by("date_joined")
                .first()
            )
            if manager and manager not in recipients:
                recipients.append(manager)

        if not recipients:
            if system_user:
                recipients.append(system_user)
            else:
                return "skipped"

        # Idempotency key
        idempotency_ref = f"FD-MATURITY-ALERT-{account.account_number}-{today}"

        # Skip if already alerted today
        already_sent = Notification.objects.filter(
            related_savings=account,
            created_at__date=today,
            notification_type="savings_approved",   # reuse type — see below
        ).exists()

        if already_sent:
            return "skipped"

        self.stdout.write(
            f"  {account.account_number} — maturity: {maturity_date} "
            f"({'PAST' if already_matured else f'{days_to_maturity}d'}) "
            f"→ notify: {', '.join(r.username for r in recipients)}"
        )

        if dry_run:
            return "alerted"

        for recipient in recipients:
            Notification.objects.create(
                user=recipient,
                notification_type="savings_approved",   # closest available type
                title=title,
                message=message,
                related_savings=account,
                related_client=account.client,
                is_urgent=is_urgent,
            )

        return "alerted"

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
