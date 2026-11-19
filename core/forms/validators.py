"""
Shared form-level validators.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone


def restrict_branch_field_by_role(form, user, field_name='branch'):
    """
    A Manager filtering any list/report may only ever pick their own
    branch; Staff never need a branch picker at all (their data is
    already scoped to their assigned clients, not a branch).

    Audit finding (2026-11-19): search/filter forms across the app
    (clients, loans, savings accounts, savings transactions, groups,
    group savings accounts, journal entries, financial reports) offered
    every branch to every role in the dropdown. The underlying list views
    already scope their base queryset by role before applying this filter
    (see PermissionChecker.filter_clients/filter_loans/etc.), so this was
    not a data leak there — but it was still confusing/wrong-looking UI,
    and for the financial reports (Trial Balance, P&L, Balance Sheet,
    General Ledger, PAR Aging, Loan Officer Performance, Savings
    Maturity, Loan Repayments) there was no such base-queryset
    restriction, so this WAS a real leak there (fixed separately in each
    of those views).

    Call from a form's __init__ after super().__init__(), with a `user`
    kwarg threaded through from the view.
    """
    if form is None or field_name not in form.fields:
        return
    if user is None or not getattr(user, 'is_authenticated', False):
        return
    from core.models import Branch
    role = getattr(user, 'user_role', None)
    if role == 'manager' and user.branch_id:
        form.fields[field_name].queryset = Branch.objects.filter(id=user.branch_id)
        if hasattr(form.fields[field_name], 'empty_label'):
            form.fields[field_name].empty_label = None
        form.fields[field_name].initial = user.branch_id
    elif role == 'staff':
        form.fields[field_name].queryset = Branch.objects.none()


def enforce_no_backdating(user, date_value, field_label='this date'):
    """
    Policy (2026-11-19): a loan repayment or savings transaction (deposit or
    withdrawal) may only be dated today, or yesterday if it is still before
    12:00pm (noon) local time. Anything older, or any future date, is
    rejected — for every role, with no override. This replaces the earlier
    (2026-10-27) rule that gave Admin/Director/HR an unrestricted exemption.

    Call from a form's clean_<field>() or clean(). Silently does nothing if
    date_value is missing (let the field's own required-ness handle that).
    The `user` argument is accepted for call-site compatibility but no
    longer affects the outcome — the window is the same for everyone.
    """
    if date_value is None:
        return
    local_now = timezone.localtime(timezone.now())
    today = local_now.date()
    yesterday = today - timedelta(days=1)

    if date_value == today:
        return
    if date_value == yesterday and local_now.hour < 12:
        return

    if date_value > today:
        raise ValidationError(f"{field_label} cannot be a future date.")
    if date_value == yesterday:
        raise ValidationError(
            f"{field_label} can only be back-dated to yesterday before 12pm. "
            f"That cutoff has passed — please use today's date."
        )
    raise ValidationError(f"{field_label} cannot be more than one day in the past.")
