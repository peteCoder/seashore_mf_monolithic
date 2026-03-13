"""
Savings Background Tasks
========================

Scheduled tasks:
  post_savings_interest           — Monthly 1st 02:00 WAT: credits interest to all active savings
  alert_fixed_deposit_maturities  — Daily 08:00 WAT: notifies managers of maturing FD accounts
"""

import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def _system_user():
    from core.models import User
    user = User.objects.filter(is_superuser=True).first()
    if user is None:
        raise RuntimeError("No superuser found — create one via createsuperuser first")
    return user


# =============================================================================
# 1. MONTHLY SAVINGS INTEREST POSTING
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def post_savings_interest(self):
    """
    Runs on the 1st of every month at 02:00 WAT.

    For every active savings account with interest_rate_annual > 0:
      1. Calls SavingsAccount.post_interest() — updates balance, creates Transaction
      2. Calls post_savings_interest_journal()  — posts the GL entry

    Idempotent: skips any account whose last_interest_date is already this month.
    """
    from core.models import SavingsAccount
    from core.utils.accounting_helpers import post_savings_interest_journal

    today      = timezone.now().date()
    system_usr = _system_user()

    posted  = 0
    skipped = 0

    accounts = (
        SavingsAccount.objects
        .filter(
            status='active',
            savings_product__interest_rate_annual__gt=Decimal('0.00'),
        )
        .select_related('savings_product', 'branch', 'client')
    )

    for account in accounts:
        # Skip if already processed this month
        last = account.last_interest_date
        if last and last.year == today.year and last.month == today.month:
            skipped += 1
            continue

        try:
            with transaction.atomic():
                txn = account.post_interest(processed_by=system_usr)

                if txn is None:
                    skipped += 1
                    continue

                post_savings_interest_journal(
                    savings_account=account,
                    interest_amount=txn.amount,
                    processed_by=system_usr,
                    transaction_obj=txn,
                    posting_date=today,
                )

                posted += 1
                logger.info(
                    f"Interest ₦{txn.amount} posted to {account.account_number}"
                )

        except Exception as exc:
            logger.error(f"Interest posting failed for {account.account_number}: {exc}")

    logger.info(
        f"post_savings_interest [{today}]: {posted} posted, {skipped} skipped"
    )
    return {'date': str(today), 'accounts_processed': posted, 'skipped': skipped}


# =============================================================================
# 2. DAILY FIXED DEPOSIT MATURITY ALERTS
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def alert_fixed_deposit_maturities(self):
    """
    Runs daily at 08:00 WAT.

    Finds active fixed-deposit accounts maturing within the next 7 days and
    creates in-app Notification records for branch managers and directors.
    Skips accounts already notified today.
    """
    from core.models import SavingsAccount, Notification, User

    today        = timezone.now().date()
    alert_window = today + timedelta(days=7)

    maturing = (
        SavingsAccount.objects
        .filter(
            status='active',
            savings_product__product_type='fixed',
            maturity_date__isnull=False,
            maturity_date__gte=today,
            maturity_date__lte=alert_window,
        )
        .select_related('savings_product', 'branch', 'client')
    )

    created = 0

    for account in maturing:
        days_left = (account.maturity_date - today).days

        # Idempotent: one alert per account per day
        already = Notification.objects.filter(
            notification_type='savings_maturity',
            related_savings=account,
            created_at__date=today,
        ).exists()

        if already:
            continue

        days_label = 'today' if days_left == 0 else f"in {days_left} day(s)"
        message = (
            f"Fixed deposit {account.account_number} for "
            f"{account.client.get_full_name()} matures {days_label} "
            f"({account.maturity_date.strftime('%d %b %Y')}). "
            f"Balance: ₦{account.balance:,.2f}"
        )

        managers = User.objects.filter(
            branch=account.branch,
            role__in=['manager', 'director', 'admin'],
            is_active=True,
        )

        for manager in managers:
            Notification.objects.create(
                user=manager,
                notification_type='savings_maturity',
                title=f"FD Maturing: {account.account_number}",
                message=message,
                is_urgent=(days_left <= 1),
                related_savings=account,
                related_client=account.client,
            )
            created += 1

        logger.info(
            f"Maturity alert for {account.account_number} "
            f"(matures {days_label}) — {managers.count()} recipient(s)"
        )

    logger.info(f"alert_fixed_deposit_maturities [{today}]: {created} notification(s) created")
    return {'date': str(today), 'notifications_created': created}
