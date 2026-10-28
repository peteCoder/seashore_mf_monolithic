"""
Custom template filters for the audit log page.
"""

import json

from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()

_REVERSIBLE_TYPES = {'loan_repayment', 'deposit', 'withdrawal'}
_REVERSAL_ROLES   = {'admin', 'director', 'hr'}

# Audit finding (2026-10-27): must match core.services.reversal_service.REVERSAL_WINDOW_DAYS —
# duplicated here (not imported) because importing a service module from a
# templatetags module at Django app-load time risks circular imports.
_REVERSAL_WINDOW_DAYS = 30


@register.filter(name='can_reverse')
def can_reverse(user):
    """Return True if the user is allowed to reverse transactions."""
    if not user or not user.is_authenticated:
        return False
    return getattr(user, 'user_role', '') in _REVERSAL_ROLES


@register.filter(name='is_reversible')
def is_reversible(txn):
    """Return True if the transaction can be reversed."""
    if txn is None:
        return False
    if txn.status != 'completed' or txn.transaction_type not in _REVERSIBLE_TYPES:
        return False
    if txn.transaction_date is None:
        return False
    txn_date = txn.transaction_date.date() if hasattr(txn.transaction_date, 'date') else txn.transaction_date
    return (timezone.now().date() - txn_date).days <= _REVERSAL_WINDOW_DAYS


@register.filter(name='tojson')
def to_changes_json(changes_dict):
    """
    Convert an auditlog changes_dict  {field: [old, new], ...}
    into a JSON array  [{field, old, new}, ...]  for Alpine.js consumption.

    Usage in template:
        {{ log.changes_dict|tojson }}
    """
    if not changes_dict:
        return mark_safe('[]')

    rows = []
    for field, values in changes_dict.items():
        if isinstance(values, (list, tuple)) and len(values) >= 2:
            old_val, new_val = values[0], values[1]
        else:
            old_val, new_val = None, values

        rows.append({
            'field': str(field),
            'old':   str(old_val) if old_val is not None else '',
            'new':   str(new_val) if new_val is not None else '',
        })

    return mark_safe(json.dumps(rows, ensure_ascii=False))
