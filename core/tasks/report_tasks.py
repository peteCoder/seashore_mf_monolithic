"""
Report Scheduling Tasks
=======================

Scheduled tasks that email automated reports to management:

  email_daily_par_digest   — Daily 07:00 WAT
                             PAR snapshot (1 / 30 / 60 / 90) for all directors/admins.

  email_monthly_summary    — 1st of month 06:00 WAT
                             Key KPIs (portfolio, new loans, new savings, collections)
                             for the previous month.
"""

import logging
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _money(amount):
    """Format Decimal amount as ₦x,xxx,xxx"""
    try:
        return f'₦{float(amount):,.2f}'
    except (TypeError, ValueError):
        return '₦0.00'


def _pct(numerator, denominator):
    """Return percentage string with 2 d.p., safely handles zero denominator."""
    if not denominator:
        return '0.00%'
    try:
        return f'{float(numerator) / float(denominator) * 100:.2f}%'
    except (TypeError, ZeroDivisionError):
        return '0.00%'


def _email_style():
    return """
    <style>
        body { font-family: 'Segoe UI', Arial, sans-serif; color: #333; margin:0; padding:0; background:#f4f4f4; }
        .wrap { max-width: 640px; margin: 0 auto; background:#fff; border-radius:8px; overflow:hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,.10); }
        .hdr  { background: linear-gradient(135deg,#eab308,#ca8a04); color:#fff; padding:24px; text-align:center; }
        .hdr h2 { margin:0; font-size:20px; }
        .hdr p  { margin:4px 0 0; font-size:13px; opacity:.9; }
        .body { padding:24px; }
        .kpi-grid { display:flex; flex-wrap:wrap; gap:12px; margin:16px 0; }
        .kpi  { flex:1 1 40%; min-width:120px; padding:14px; border-radius:6px; text-align:center; border:1px solid #eee; }
        .kpi h3 { margin:0 0 4px; font-size:20px; font-weight:700; }
        .kpi p  { margin:0; font-size:11px; color:#666; text-transform:uppercase; letter-spacing:.5px; }
        .kpi.blue   { background:#eff6ff; border-color:#bfdbfe; }
        .kpi.green  { background:#f0fdf4; border-color:#bbf7d0; }
        .kpi.amber  { background:#fffbeb; border-color:#fde68a; }
        .kpi.red    { background:#fef2f2; border-color:#fecaca; }
        .note { font-size:12px; color:#777; margin-top:16px; padding-top:12px; border-top:1px solid #eee; }
        .ftr  { background:#f8f9fa; padding:14px; text-align:center; font-size:11px; color:#aaa; }
    </style>"""


# =============================================================================
# 1. DAILY PAR DIGEST
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def email_daily_par_digest(self):
    """
    Runs daily at 07:00 WAT.

    Computes current PAR 1 / 30 / 60 / 90 buckets and emails a one-page
    summary to every active Director and Admin user.
    """
    from core.models import Loan, User
    from core.email_service import send_email

    today = timezone.now().date()

    # ── Portfolio figures ──────────────────────────────────────────────────
    active_loans = list(
        Loan.objects.filter(status__in=['active', 'overdue', 'disbursed'])
        .only('outstanding_balance', 'status', 'next_payment_date')
    )

    total_portfolio = sum(
        l.outstanding_balance or Decimal('0') for l in active_loans
    )
    active_count   = sum(1 for l in active_loans if l.status != 'overdue')
    overdue_count  = sum(1 for l in active_loans if l.status == 'overdue')

    par = {1: Decimal('0'), 30: Decimal('0'), 60: Decimal('0'), 90: Decimal('0')}
    for loan in active_loans:
        if loan.status != 'overdue' or not loan.next_payment_date:
            continue
        dpd     = (today - loan.next_payment_date).days
        balance = loan.outstanding_balance or Decimal('0')
        if dpd >= 1:
            par[1]  += balance
        if dpd >= 30:
            par[30] += balance
        if dpd >= 60:
            par[60] += balance
        if dpd >= 90:
            par[90] += balance

    def risk_cls(ratio_str):
        """Return CSS class based on PAR ratio."""
        try:
            val = float(ratio_str.rstrip('%'))
        except ValueError:
            return 'green'
        if val >= 10:
            return 'red'
        if val >= 5:
            return 'amber'
        return 'green'

    r1  = _pct(par[1],  total_portfolio)
    r30 = _pct(par[30], total_portfolio)
    r60 = _pct(par[60], total_portfolio)
    r90 = _pct(par[90], total_portfolio)

    # ── Recipients ────────────────────────────────────────────────────────
    recipients = list(
        User.objects.filter(
            user_role__in=['director', 'hr', 'admin'],
            is_active=True, is_approved=True,
        ).values_list('email', flat=True)
    )

    if not recipients:
        logger.info("email_daily_par_digest: no directors/admins found — skipping.")
        return {'status': 'skipped', 'reason': 'no_recipients'}

    subject = f"Daily PAR Digest — {today.strftime('%d %b %Y')}"

    html_content = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    {_email_style()}
    </head><body>
    <div class="wrap">
      <div class="hdr">
        <h2>📊 Daily PAR Digest</h2>
        <p>{today.strftime('%A, %d %B %Y')}</p>
      </div>
      <div class="body">
        <p>Good morning! Here is the Portfolio at Risk summary for <strong>Seashore Microfinance</strong>.</p>
        <div class="kpi-grid">
          <div class="kpi blue">
            <h3>{_money(total_portfolio)}</h3>
            <p>Total Portfolio</p>
          </div>
          <div class="kpi blue">
            <h3>{len(active_loans)}</h3>
            <p>Active Loans ({overdue_count} overdue)</p>
          </div>
          <div class="kpi {risk_cls(r1)}">
            <h3>{r1}</h3>
            <p>PAR 1 ({_money(par[1])})</p>
          </div>
          <div class="kpi {risk_cls(r30)}">
            <h3>{r30}</h3>
            <p>PAR 30 ({_money(par[30])})</p>
          </div>
          <div class="kpi {risk_cls(r60)}">
            <h3>{r60}</h3>
            <p>PAR 60 ({_money(par[60])})</p>
          </div>
          <div class="kpi {risk_cls(r90)}">
            <h3>{r90}</h3>
            <p>PAR 90 ({_money(par[90])})</p>
          </div>
        </div>
        <p class="note">
          PAR &gt; 5% = elevated risk &nbsp;|&nbsp; PAR &gt; 10% = critical<br>
          PAR 1: loans &ge; 1 day past due &nbsp;&bull;&nbsp;
          PAR 30/60/90: &ge; 30/60/90 days past due.<br>
          This is an automated report generated at {timezone.localtime(timezone.now()).strftime('%H:%M')} WAT.
        </p>
      </div>
      <div class="ftr">Seashore Microfinance Bank &mdash; Automated Report &mdash; {today.year}</div>
    </div>
    </body></html>"""

    sent = 0
    for email in recipients:
        if send_email(email, subject, html_content):
            sent += 1

    logger.info(
        "email_daily_par_digest: sent to %d/%d recipients for %s",
        sent, len(recipients), today,
    )
    return {'status': 'sent', 'recipients': sent, 'date': str(today)}


# =============================================================================
# 2. MONTHLY KPI SUMMARY
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def email_monthly_summary(self):
    """
    Runs on the 1st of each month at 06:00 WAT.

    Compiles prior-month KPIs (new loans disbursed, repayments collected,
    new savings opened, active clients) and emails them to directors/admins.
    """
    from core.models import Loan, SavingsAccount, Transaction, User
    from core.email_service import send_email
    from django.db.models import Sum, Count
    from datetime import date

    today      = timezone.now().date()
    first_this = today.replace(day=1)

    # Last month window
    if first_this.month == 1:
        last_month_start = date(first_this.year - 1, 12, 1)
        last_month_end   = date(first_this.year - 1, 12, 31)
        month_label      = last_month_start.strftime('%B %Y')
    else:
        last_month_start = date(first_this.year, first_this.month - 1, 1)
        import calendar
        last_day = calendar.monthrange(first_this.year, first_this.month - 1)[1]
        last_month_end = date(first_this.year, first_this.month - 1, last_day)
        month_label    = last_month_start.strftime('%B %Y')

    # ── KPIs ──────────────────────────────────────────────────────────────
    new_loans = Loan.objects.filter(
        disbursement_date__range=[last_month_start, last_month_end],
    )
    new_loans_count  = new_loans.count()
    new_loans_amount = new_loans.aggregate(s=Sum('principal_amount'))['s'] or Decimal('0')

    repayments = Transaction.objects.filter(
        transaction_type='loan_repayment',
        transaction_date__date__range=[last_month_start, last_month_end],
        status='completed',
    )
    repayment_count  = repayments.count()
    repayment_amount = repayments.aggregate(s=Sum('amount'))['s'] or Decimal('0')

    new_savings = SavingsAccount.objects.filter(
        created_at__date__range=[last_month_start, last_month_end],
    )
    new_savings_count  = new_savings.count()
    savings_deposits   = Transaction.objects.filter(
        transaction_type='savings_deposit',
        transaction_date__date__range=[last_month_start, last_month_end],
        status='completed',
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    active_loan_count  = Loan.objects.filter(
        status__in=['active', 'disbursed', 'overdue']
    ).count()
    overdue_loan_count = Loan.objects.filter(status='overdue').count()

    # ── Recipients ────────────────────────────────────────────────────────
    recipients = list(
        User.objects.filter(
            user_role__in=['director', 'hr', 'admin'],
            is_active=True, is_approved=True,
        ).values_list('email', flat=True)
    )

    if not recipients:
        logger.info("email_monthly_summary: no directors/admins found — skipping.")
        return {'status': 'skipped', 'reason': 'no_recipients'}

    subject = f"Monthly Summary — {month_label}"

    html_content = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    {_email_style()}
    </head><body>
    <div class="wrap">
      <div class="hdr">
        <h2>📈 Monthly Summary</h2>
        <p>{month_label}</p>
      </div>
      <div class="body">
        <p>Here is the key performance summary for <strong>{month_label}</strong>.</p>

        <h4 style="margin:16px 0 8px; color:#ca8a04;">Lending</h4>
        <div class="kpi-grid">
          <div class="kpi blue">
            <h3>{new_loans_count}</h3>
            <p>New Loans Disbursed</p>
          </div>
          <div class="kpi blue">
            <h3>{_money(new_loans_amount)}</h3>
            <p>Total Disbursed</p>
          </div>
          <div class="kpi green">
            <h3>{repayment_count}</h3>
            <p>Repayment Transactions</p>
          </div>
          <div class="kpi green">
            <h3>{_money(repayment_amount)}</h3>
            <p>Total Collected</p>
          </div>
        </div>

        <h4 style="margin:16px 0 8px; color:#ca8a04;">Savings</h4>
        <div class="kpi-grid">
          <div class="kpi blue">
            <h3>{new_savings_count}</h3>
            <p>New Savings Accounts</p>
          </div>
          <div class="kpi green">
            <h3>{_money(savings_deposits)}</h3>
            <p>Total Deposits</p>
          </div>
        </div>

        <h4 style="margin:16px 0 8px; color:#ca8a04;">Portfolio (current)</h4>
        <div class="kpi-grid">
          <div class="kpi blue">
            <h3>{active_loan_count}</h3>
            <p>Active Loans</p>
          </div>
          <div class="kpi {'red' if overdue_loan_count else 'green'}">
            <h3>{overdue_loan_count}</h3>
            <p>Overdue Loans</p>
          </div>
        </div>

        <p class="note">
          This is an automated monthly summary generated on {today.strftime('%d %B %Y')}.
        </p>
      </div>
      <div class="ftr">Seashore Microfinance Bank &mdash; Automated Report &mdash; {today.year}</div>
    </div>
    </body></html>"""

    sent = 0
    for email in recipients:
        if send_email(email, subject, html_content):
            sent += 1

    logger.info(
        "email_monthly_summary: sent to %d/%d recipients for %s",
        sent, len(recipients), month_label,
    )
    return {'status': 'sent', 'recipients': sent, 'month': month_label}
