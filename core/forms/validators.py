"""
Shared form-level validators.
"""
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
    Audit finding (2026-10-27): staff and managers could back-date a
    transaction (loan repayment, savings deposit/withdrawal) to any past
    date with no restriction. Only Admin/Director/HR may still choose a
    date other than today — see PermissionChecker.can_backdate_transactions().

    Call from a form's clean_<field>() or clean(). Silently does nothing if
    user or date_value is missing (let the field's own required-ness / other
    validation handle that).
    """
    if date_value is None or user is None:
        return
    from core.permissions import PermissionChecker
    if date_value != timezone.now().date() and not PermissionChecker(user).can_backdate_transactions():
        raise ValidationError(
            f"You can only use today's date for {field_label}. "
            f"Back-dating requires Admin, Director, or HR."
        )
