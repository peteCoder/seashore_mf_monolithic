"""
Shared form-level validators.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone


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
