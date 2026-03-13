"""
Loan Background Tasks
=====================

Scheduled tasks:
  detect_overdue_loans         — Daily 01:00 WAT: marks loans overdue, applies daily penalty
  recalculate_par              — Daily 01:30 WAT: recalculates PAR 1 / 30 / 60 / 90 buckets
  accrue_monthly_loan_interest — Monthly 1st 02:30 WAT: posts month-end interest accrual
"""

import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _system_user():
    from core.models import User
    user = User.objects.filter(is_superuser=True).first()
    if user is None:
        raise RuntimeError("No superuser found — create one via createsuperuser first")
    return user


# =============================================================================
# 1. DETECT OVERDUE LOANS + APPLY DAILY PENALTY
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def detect_overdue_loans(self):
    """
    Runs daily at 01:00 WAT.

    For every active/disbursed loan past its repayment date (after grace period):
      1. Sets loan.status = 'overdue'
      2. Creates one LoanPenalty record per day (idempotent — skips if already posted today)
      3. Posts GL journal: Dr 1820 Interest Receivable / Cr 4170 Late Payment Fee Income
    """
    from core.models import Loan, LoanPenalty
    from core.utils.accounting_helpers import create_journal_entry

    today      = timezone.now().date()
    system_usr = _system_user()

    overdue_count = 0
    penalty_count = 0

    candidates = (
        Loan.objects
        .filter(
            status__in=['active', 'disbursed', 'overdue'],
            next_repayment_date__isnull=False,
            outstanding_balance__gt=Decimal('0.00'),
        )
        .select_related('loan_product', 'branch', 'client')
    )

    for loan in candidates:
        grace_days  = loan.loan_product.grace_period_days or 0
        cutoff_date = today - timedelta(days=grace_days)

        if loan.next_repayment_date >= cutoff_date:
            continue  # still within grace period

        # 1. Mark loan overdue
        if loan.status != 'overdue':
            Loan.objects.filter(pk=loan.pk).update(status='overdue')
            overdue_count += 1
            logger.info(f"Loan {loan.loan_number} → overdue (due: {loan.next_repayment_date})")

        # 2. Skip if penalty already applied today
        already_penalised = LoanPenalty.objects.filter(
            loan=loan,
            penalty_type='late_payment',
            created_at__date=today,
        ).exists()

        if already_penalised:
            continue

        # 3. Calculate penalty: 0.1 % of outstanding per day ≈ 3 % p.m.
        daily_rate     = Decimal('0.001')
        penalty_amount = (loan.outstanding_balance * daily_rate).quantize(Decimal('0.01'))

        if penalty_amount < Decimal('0.01'):
            continue

        days_overdue = (today - loan.next_repayment_date).days

        try:
            with transaction.atomic():
                LoanPenalty.objects.create(
                    loan=loan,
                    penalty_type='late_payment',
                    amount=penalty_amount,
                    reason=(
                        f"Automatic late-payment penalty — {days_overdue} day(s) overdue. "
                        f"Outstanding balance: ₦{loan.outstanding_balance:,.2f}"
                    ),
                    is_paid=False,
                    created_by=system_usr,
                )

                create_journal_entry(
                    entry_type='penalty',
                    transaction_date=today,
                    branch=loan.branch,
                    description=(
                        f"Late payment penalty: {loan.loan_number} — Day {days_overdue}"
                    ),
                    created_by=system_usr,
                    lines=[
                        {
                            'account_code': '1820',
                            'debit':  float(penalty_amount),
                            'credit': 0,
                            'description': f"Penalty receivable: {loan.loan_number}",
                            'client': loan.client,
                        },
                        {
                            'account_code': '4170',
                            'debit':  0,
                            'credit': float(penalty_amount),
                            'description': f"Late payment fee income: {loan.loan_number}",
                            'client': loan.client,
                        },
                    ],
                    loan=loan,
                    reference_number=f"PENALTY-{today.strftime('%Y%m%d')}-{loan.loan_number}",
                    auto_post=True,
                )

                penalty_count += 1
                logger.info(
                    f"Penalty ₦{penalty_amount} applied to {loan.loan_number} "
                    f"({days_overdue} day(s) overdue)"
                )

        except Exception as exc:
            logger.error(f"Failed to apply penalty for {loan.loan_number}: {exc}")

    logger.info(
        f"detect_overdue_loans [{today}]: "
        f"{overdue_count} loans marked overdue, {penalty_count} penalties applied"
    )
    return {
        'date':                 str(today),
        'loans_marked_overdue': overdue_count,
        'penalties_applied':    penalty_count,
    }


# =============================================================================
# 2. DAILY PAR RECALCULATION
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def recalculate_par(self):
    """
    Runs daily at 01:30 WAT.

    Calculates Portfolio at Risk (PAR) at 1, 30, 60 and 90-day buckets and
    logs the snapshot. Results are also stored as the task's return value so
    they are visible in django-celery-results / admin.
    """
    from core.models import Loan
    from django.db.models import Sum

    today = timezone.now().date()

    total = (
        Loan.objects
        .filter(status__in=['active', 'disbursed', 'overdue'])
        .aggregate(t=Sum('outstanding_balance'))['t']
        or Decimal('0.00')
    )

    if total == Decimal('0.00'):
        logger.info("recalculate_par: portfolio is empty")
        return {'date': str(today), 'total_portfolio': '0.00'}

    def _par(days):
        cutoff  = today - timedelta(days=days)
        at_risk = (
            Loan.objects
            .filter(
                status__in=['active', 'disbursed', 'overdue'],
                next_repayment_date__lte=cutoff,
            )
            .aggregate(s=Sum('outstanding_balance'))['s']
            or Decimal('0.00')
        )
        pct = (at_risk / total * 100).quantize(Decimal('0.01'))
        return {'pct': str(pct), 'amount': str(at_risk)}

    result = {
        'date':            str(today),
        'total_portfolio': str(total),
        'par_1':           _par(1),
        'par_30':          _par(30),
        'par_60':          _par(60),
        'par_90':          _par(90),
    }

    logger.info(
        f"PAR [{today}]  "
        f"PAR1={result['par_1']['pct']}%  "
        f"PAR30={result['par_30']['pct']}%  "
        f"PAR60={result['par_60']['pct']}%  "
        f"PAR90={result['par_90']['pct']}%"
    )
    return result


# =============================================================================
# 3. MONTHLY LOAN INTEREST ACCRUAL
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def accrue_monthly_loan_interest(self):
    """
    Runs on the 1st of every month at 02:30 WAT.

    For every active/overdue loan with an outstanding balance:
      - Calculates monthly interest = outstanding_balance × monthly_interest_rate
      - Posts GL journal via post_loan_interest_accrual_journal()
      - Increases loan.accrued_interest_balance

    Idempotent: skips any loan whose accrual reference has already been posted
    this period (reference = "ACCRUAL-YYYY-MM-<loan_number>").
    """
    from core.models import Loan, JournalEntry
    from core.utils.accounting_helpers import post_loan_interest_accrual_journal

    today       = timezone.now().date()
    period      = today.strftime('%Y-%m')
    accrual_ref = f"ACCRUAL-{period}"
    system_usr  = _system_user()

    posted  = 0
    skipped = 0

    loans = (
        Loan.objects
        .filter(
            status__in=['active', 'disbursed', 'overdue'],
            outstanding_balance__gt=Decimal('0.00'),
        )
        .select_related('loan_product', 'branch', 'client')
    )

    for loan in loans:
        ref = f"{accrual_ref}-{loan.loan_number}"

        if JournalEntry.objects.filter(reference_number=ref).exists():
            skipped += 1
            continue

        monthly_rate = loan.loan_product.monthly_interest_rate
        accrued      = (loan.outstanding_balance * monthly_rate).quantize(Decimal('0.01'))

        if accrued <= Decimal('0.00'):
            skipped += 1
            continue

        try:
            with transaction.atomic():
                post_loan_interest_accrual_journal(
                    loan=loan,
                    accrued_interest=accrued,
                    processed_by=system_usr,
                    accrual_reference=accrual_ref,
                    accrual_date=today,
                )
                Loan.objects.filter(pk=loan.pk).update(
                    accrued_interest_balance=loan.accrued_interest_balance + accrued
                )
                posted += 1
                logger.info(f"Accrued ₦{accrued} for {loan.loan_number} [{period}]")

        except Exception as exc:
            logger.error(f"Accrual failed for {loan.loan_number}: {exc}")

    logger.info(
        f"accrue_monthly_loan_interest [{period}]: {posted} posted, {skipped} skipped"
    )
    return {'period': period, 'accruals_posted': posted, 'skipped': skipped}
