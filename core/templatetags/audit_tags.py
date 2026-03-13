"""
Custom template filters for the audit log page.
"""

import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


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
