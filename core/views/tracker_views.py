"""
Repayment Tracker Views
=======================
Provides a live, schedule-driven view of:
  - Overdue installments (past due, unpaid/partial)
  - Due today
  - Due this week (next 7 days)
  - Due next 30 days
  - PAR summary buckets

No notification records are created here — data is derived entirely from
LoanRepaymentSchedule so it is always up-to-date.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.shortcuts import render
from django.utils import timezone

from core.models import LoanRepaymentSchedule, Loan
from core.permissions import PermissionChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_schedule_qs(user):
    """
    Return the base LoanRepaymentSchedule queryset scoped to the user's branch.
    Only considers active/overdue/disbursed loans with unpaid/partial/overdue rows.
    """
    checker = PermissionChecker(user)
    qs = LoanRepaymentSchedule.objects.filter(
        status__in=['pending', 'partial', 'overdue'],
        outstanding_amount__gt=0,
        loan__status__in=['active', 'overdue', 'disbursed'],
        loan__outstanding_balance__gt=0,
    ).select_related(
        'loan', 'loan__client', 'loan__branch', 'loan__loan_product'
    )
    if not checker.can_view_all_branches() and hasattr(user, 'branch') and user.branch:
        qs = qs.filter(loan__branch=user.branch)
    return qs


def _par_buckets(overdue_rows, today):
    """
    Build PAR buckets from overdue schedule rows.
    Returns dict with keys: par_1_30, par_31_60, par_61_90, par_90plus.
    Each value is {'count': int, 'principal': Decimal, 'total': Decimal}.
    """
    buckets = {
        'current':   {'count': 0, 'principal': Decimal('0'), 'total': Decimal('0')},
        'par_1_30':  {'count': 0, 'principal': Decimal('0'), 'total': Decimal('0')},
        'par_31_60': {'count': 0, 'principal': Decimal('0'), 'total': Decimal('0')},
        'par_61_90': {'count': 0, 'principal': Decimal('0'), 'total': Decimal('0')},
        'par_90plus':{'count': 0, 'principal': Decimal('0'), 'total': Decimal('0')},
    }
    for row in overdue_rows:
        days = (today - row.due_date).days if row.due_date < today else 0
        outstanding = row.outstanding_amount or Decimal('0')
        principal   = row.principal_amount   or Decimal('0')
        if days == 0:
            key = 'current'
        elif days <= 30:
            key = 'par_1_30'
        elif days <= 60:
            key = 'par_31_60'
        elif days <= 90:
            key = 'par_61_90'
        else:
            key = 'par_90plus'
        buckets[key]['count']     += 1
        buckets[key]['principal'] += principal
        buckets[key]['total']     += outstanding
    return buckets


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

@login_required
def loan_repayment_tracker(request):
    """
    Repayment Tracker — shows overdue, today, upcoming installments from the
    LoanRepaymentSchedule table. No notification records are created.
    """
    today = timezone.localdate()
    week_end  = today + timedelta(days=7)
    month_end = today + timedelta(days=30)

    base_qs = _base_schedule_qs(request.user)

    # ── Overdue ────────────────────────────────────────────────────────────
    overdue_rows = (
        base_qs.filter(due_date__lt=today)
        .order_by('due_date', 'loan__client__first_name')
    )

    # ── Due today ──────────────────────────────────────────────────────────
    due_today_rows = (
        base_qs.filter(due_date=today)
        .order_by('loan__client__first_name')
    )

    # ── Due this week (next 7 days, excluding today) ────────────────────────
    due_week_rows = (
        base_qs.filter(due_date__gt=today, due_date__lte=week_end)
        .order_by('due_date', 'loan__client__first_name')
    )

    # ── Due next 30 days (8–30 days out) ───────────────────────────────────
    due_month_rows = (
        base_qs.filter(due_date__gt=week_end, due_date__lte=month_end)
        .order_by('due_date', 'loan__client__first_name')
    )

    # ── Summary aggregates ─────────────────────────────────────────────────
    def _agg(qs):
        agg = qs.aggregate(
            total_outstanding=Sum('outstanding_amount'),
            total_principal=Sum('principal_amount'),
            count=Count('id'),
        )
        return {
            'count':       agg['count'] or 0,
            'outstanding': agg['total_outstanding'] or Decimal('0'),
            'principal':   agg['total_principal']   or Decimal('0'),
        }

    overdue_summary    = _agg(overdue_rows)
    today_summary      = _agg(due_today_rows)
    week_summary       = _agg(due_week_rows)
    month_summary      = _agg(due_month_rows)

    # Unique loan counts
    overdue_loan_count = overdue_rows.values('loan_id').distinct().count()
    today_loan_count   = due_today_rows.values('loan_id').distinct().count()

    # ── PAR buckets ────────────────────────────────────────────────────────
    par_buckets = _par_buckets(list(overdue_rows), today)

    # Grand totals for PAR %
    total_outstanding_all = (
        LoanRepaymentSchedule.objects
        .filter(
            loan__status__in=['active', 'overdue', 'disbursed'],
            status__in=['pending', 'partial', 'overdue'],
        )
        .aggregate(s=Sum('outstanding_amount'))['s'] or Decimal('0')
    )

    par_at_risk = (
        overdue_summary['outstanding'] / total_outstanding_all * 100
        if total_outstanding_all > 0
        else Decimal('0')
    )

    # ── Active tab from querystring ────────────────────────────────────────
    tab = request.GET.get('tab', 'overdue')
    if tab not in ('overdue', 'today', 'week', 'month'):
        tab = 'overdue'

    context = {
        'page_title': 'Repayment Tracker',
        'today': today,
        'week_end': week_end,
        'month_end': month_end,
        'tab': tab,

        # Row data
        'overdue_rows':    overdue_rows,
        'due_today_rows':  due_today_rows,
        'due_week_rows':   due_week_rows,
        'due_month_rows':  due_month_rows,

        # Summaries
        'overdue_summary':      overdue_summary,
        'today_summary':        today_summary,
        'week_summary':         week_summary,
        'month_summary':        month_summary,
        'overdue_loan_count':   overdue_loan_count,
        'today_loan_count':     today_loan_count,

        # PAR
        'par_buckets':          par_buckets,
        'par_at_risk':          round(float(par_at_risk), 1),
        'total_outstanding_all':total_outstanding_all,
    }
    return render(request, 'loans/repayment_tracker.html', context)
