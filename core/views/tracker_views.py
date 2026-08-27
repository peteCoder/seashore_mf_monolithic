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

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Sum, Q, F
from django.shortcuts import render
from django.utils import timezone

from core.models import LoanRepaymentSchedule, Loan, Branch, ClientGroup, PublicHoliday
from core.permissions import PermissionChecker, Permissions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_schedule_qs(user):
    """
    Return the base LoanRepaymentSchedule queryset scoped by the user's role.

    Uses outstanding_amount__gt=0 as the primary "not fully paid" check rather
    than the stored status field, which is a stale DB cache only refreshed on
    save(). Rows bulk-created at disbursement time may have status='pending'
    even when their computed_status would be 'overdue'. We exclude only
    definitively closed rows (paid / waived) by filtering on outstanding_amount.
    """
    checker = PermissionChecker(user)
    qs = LoanRepaymentSchedule.objects.filter(
        outstanding_amount__gt=0,
        loan__status__in=['active', 'overdue', 'disbursed'],
        loan__outstanding_balance__gt=0,
    ).exclude(
        status__in=['paid', 'waived'],
    ).select_related(
        'loan', 'loan__client', 'loan__client__assigned_staff', 'loan__branch', 'loan__loan_product'
    )
    if checker.can_view_all_branches():
        return qs
    if checker.is_manager() and checker.branch:
        return qs.filter(loan__branch=checker.branch)
    if checker.is_staff():
        return qs.filter(loan__client__assigned_staff=user)
    return qs.none()


def _loans_without_schedule(user, checker=None):
    """
    Return active/disbursed loans that have NO LoanRepaymentSchedule rows at all.
    These are invisible to the schedule-based tracker and need separate handling.
    """
    if checker is None:
        checker = PermissionChecker(user)
    qs = Loan.objects.filter(
        status__in=['active', 'overdue', 'disbursed'],
        outstanding_balance__gt=0,
    ).annotate(
        has_schedule=Exists(
            LoanRepaymentSchedule.objects.filter(loan=OuterRef('pk'))
        )
    ).filter(
        has_schedule=False,
    ).select_related('client', 'client__assigned_staff', 'branch', 'loan_product')
    if checker.can_view_all_branches():
        return qs
    if checker.is_manager() and checker.branch:
        return qs.filter(branch=checker.branch)
    if checker.is_staff():
        return qs.filter(client__assigned_staff=user)
    return qs.none()


def _base_loan_qs(user, checker=None):
    """
    Return every active/overdue/disbursed loan with an outstanding balance,
    scoped by the user's role — regardless of whether it has schedule rows
    or when its next installment is due. Backs the "All Active Loans" tab,
    which exists so a loan that's current/ahead-of-schedule (next due date
    beyond the other tabs' 30-day lookahead) can still always be found.
    """
    if checker is None:
        checker = PermissionChecker(user)
    qs = Loan.objects.filter(
        status__in=['active', 'overdue', 'disbursed'],
        outstanding_balance__gt=0,
    ).select_related('client', 'client__assigned_staff', 'branch', 'loan_product')
    if checker.can_view_all_branches():
        return qs
    if checker.is_manager() and checker.branch:
        return qs.filter(branch=checker.branch)
    if checker.is_staff():
        return qs.filter(client__assigned_staff=user)
    return qs.none()


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

    Access: all roles that can view loans (admin, director, hr, manager, staff).
    Data is automatically scoped to what each role is allowed to see.
    """
    checker = PermissionChecker(request.user)
    # Only roles that can interact with loans may access this page
    allowed_roles = (
        Permissions.CAN_CREATE_LOANS
        + Permissions.CAN_APPROVE_LOANS
    )
    if request.user.user_role not in set(allowed_roles):
        raise PermissionDenied

    today = timezone.localdate()
    week_end  = today + timedelta(days=7)
    month_end = today + timedelta(days=30)

    # ── Branch filter (only meaningful for roles that can see multiple branches) ──
    branches = Branch.objects.filter(is_active=True).order_by('name') if checker.can_view_all_branches() else Branch.objects.none()
    selected_branch = None
    branch_id = request.GET.get('branch', '').strip()
    if branch_id and checker.can_view_all_branches():
        selected_branch = branches.filter(id=branch_id).first()

    # ── Due-date filter ────────────────────────────────────────────────────
    # Optional date_from/date_to narrows every tab's rows down to
    # installments due within the chosen range. Summaries below are computed
    # directly from these same (now-filtered) querysets, so the totals shown
    # automatically reflect the filter too — there's no separate "amount"
    # calculation to keep in sync.
    def _parse_date(raw):
        raw = (raw or '').strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    date_from = _parse_date(request.GET.get('date_from'))
    date_to   = _parse_date(request.GET.get('date_to'))

    base_qs = _base_schedule_qs(request.user)
    if selected_branch:
        base_qs = base_qs.filter(loan__branch=selected_branch)
    if date_from:
        base_qs = base_qs.filter(due_date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(due_date__lte=date_to)

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

    # ── Active loans with NO schedule rows ─────────────────────────────────
    # These are completely invisible to the schedule-based tracker. Show them
    # as a warning so managers can investigate and rebuild their schedules.
    loans_no_schedule_qs = _loans_without_schedule(request.user, checker=checker)
    if selected_branch:
        loans_no_schedule_qs = loans_no_schedule_qs.filter(branch=selected_branch)
    if date_from:
        loans_no_schedule_qs = loans_no_schedule_qs.filter(next_repayment_date__gte=date_from)
    if date_to:
        loans_no_schedule_qs = loans_no_schedule_qs.filter(next_repayment_date__lte=date_to)
    loans_no_schedule = list(
        loans_no_schedule_qs.order_by('next_repayment_date', 'client__first_name')
    )
    loans_no_schedule_today = [
        l for l in loans_no_schedule
        if l.next_repayment_date and l.next_repayment_date <= today
    ]

    # ── All Active Loans (regardless of when their next installment is due) ──
    # Loans that are current/ahead-of-schedule naturally have their next due
    # date beyond the 30-day lookahead of the other tabs and would otherwise
    # never appear anywhere in the tracker. This tab is a catch-all so any
    # active loan can always be found here.
    all_active_loans_qs = _base_loan_qs(request.user, checker=checker)
    if selected_branch:
        all_active_loans_qs = all_active_loans_qs.filter(branch=selected_branch)
    if date_from:
        all_active_loans_qs = all_active_loans_qs.filter(next_repayment_date__gte=date_from)
    if date_to:
        all_active_loans_qs = all_active_loans_qs.filter(next_repayment_date__lte=date_to)
    all_active_loans_qs = all_active_loans_qs.annotate(
        total_installments=Count('repayment_schedule', distinct=True),
        paid_installments=Count(
            'repayment_schedule',
            filter=Q(repayment_schedule__amount_paid__gte=(
                F('repayment_schedule__total_amount') + F('repayment_schedule__penalty_amount')
            )),
            distinct=True
        ),
    ).order_by('next_repayment_date', 'client__first_name')
    all_active_loans_count = all_active_loans_qs.count()

    all_paginator = Paginator(all_active_loans_qs, 25)
    all_active_loans_page = all_paginator.get_page(request.GET.get('all_page'))

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

    # Bump "today" count to include schedule-less loans due today/overdue
    today_summary['count'] += len(loans_no_schedule_today)
    today_summary['outstanding'] += sum(
        (l.outstanding_balance or Decimal('0')) for l in loans_no_schedule_today
    )

    # Unique loan counts
    overdue_loan_count = overdue_rows.values('loan_id').distinct().count()
    today_loan_count   = due_today_rows.values('loan_id').distinct().count() + len(loans_no_schedule_today)

    # ── PAR buckets ────────────────────────────────────────────────────────
    par_buckets = _par_buckets(list(overdue_rows), today)

    # Grand totals for PAR % — scoped to what this user can see
    par_total_qs = LoanRepaymentSchedule.objects.filter(
        loan__status__in=['active', 'overdue', 'disbursed'],
        outstanding_amount__gt=0,
        loan__outstanding_balance__gt=0,
    ).exclude(status__in=['paid', 'waived'])
    if checker.can_view_all_branches():
        if selected_branch:
            par_total_qs = par_total_qs.filter(loan__branch=selected_branch)
    elif checker.is_manager() and checker.branch:
        par_total_qs = par_total_qs.filter(loan__branch=checker.branch)
    elif checker.is_staff():
        par_total_qs = par_total_qs.filter(loan__client__assigned_staff=request.user)
    else:
        par_total_qs = par_total_qs.none()

    total_outstanding_all = (
        par_total_qs.aggregate(s=Sum('outstanding_amount'))['s'] or Decimal('0')
    )

    par_at_risk = (
        overdue_summary['outstanding'] / total_outstanding_all * 100
        if total_outstanding_all > 0
        else Decimal('0')
    )

    # ── Active tab from querystring ────────────────────────────────────────
    tab = request.GET.get('tab', 'overdue')
    if tab not in ('overdue', 'today', 'week', 'month', 'all'):
        tab = 'overdue'

    # Count of rows matching the current filters (branch + tab), shown beneath
    # the filter bar. "Today" bumps in schedule-less loans, same as its summary.
    tab_counts = {
        'overdue': overdue_summary['count'],
        'today':   today_summary['count'],
        'week':    week_summary['count'],
        'month':   month_summary['count'],
        'all':     all_active_loans_count,
    }
    active_tab_count = tab_counts[tab]

    context = {
        'page_title': 'Repayment Tracker',
        'checker': checker,
        'today': today,
        'week_end': week_end,
        'month_end': month_end,
        'tab': tab,
        'active_tab_count': active_tab_count,

        # Branch filter
        'branches': branches,
        'selected_branch': selected_branch,

        # Due-date filter
        'date_from': date_from,
        'date_to': date_to,

        # Row data
        'overdue_rows':    overdue_rows,
        'due_today_rows':  due_today_rows,
        'due_week_rows':   due_week_rows,
        'due_month_rows':  due_month_rows,
        'all_active_loans':       all_active_loans_page,
        'all_active_loans_count': all_active_loans_count,

        # Loans with no schedule rows (invisible to main tracker)
        'loans_no_schedule':       loans_no_schedule,
        'loans_no_schedule_today': loans_no_schedule_today,

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


# ---------------------------------------------------------------------------
# Group repayment tracker
# ---------------------------------------------------------------------------

@login_required
def group_repayment_tracker(request):
    """
    Groups whose meeting day is today — i.e. groups a collector should visit
    today to collect loan repayments.

    Scoping is deliberately NOT the standard can_view_all_branches()/
    is_admin_or_director() grouping (which bundles HR in with admin/director):
      - Admin / Director:  every active group meeting today, any branch.
      - HR / Manager:      active groups meeting today within their own branch.
      - Staff:             active groups meeting today, in their own branch,
                            that they are the assigned loan officer for.
    """
    checker = PermissionChecker(request.user)
    if request.user.user_role not in ('admin', 'director', 'hr', 'manager', 'staff'):
        raise PermissionDenied

    today = timezone.localdate()
    today_name = today.strftime('%A').lower()

    # On a public holiday there's no collection to make, so no groups are
    # shown regardless of their meeting_day — mirrors the dashboard alert.
    holiday_today = PublicHoliday.objects.filter(date=today).first()

    if holiday_today:
        groups = ClientGroup.objects.none()
    else:
        groups = ClientGroup.objects.filter(
            meeting_day=today_name,
            status='active',
        ).select_related('branch', 'loan_officer')

        if checker.is_admin() or checker.is_director():
            pass  # all branches
        elif checker.is_hr() or checker.is_manager():
            groups = groups.filter(branch=checker.branch)
        elif checker.is_staff():
            groups = groups.filter(branch=checker.branch, loan_officer=request.user)

    groups = groups.order_by('branch__name', 'name')
    total_count = groups.count()

    context = {
        'page_title': 'Group Repayment Tracker',
        'checker': checker,
        'today': today,
        'groups': groups,
        'total_count': total_count,
        'holiday_today': holiday_today,
    }
    return render(request, 'groups/repayment_tracker.html', context)
