"""
Data-quality flag report: clients (within the active/disbursed loan set)
that share the same id_number with another, unrelated client.

Companion to export_loan_disbursement.py -- run after that export if you
also want the flag list refreshed. This does NOT modify any data; it
only reports what needs human review before it's trusted for anything
external (e.g. the GOXI submission).

Run from the seashore/ directory (same folder as manage.py):
    python export_duplicate_id_flags.py
"""
import csv
import os
from datetime import datetime

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'seashore.settings')
django.setup()

from core.models.all_models import Loan

OUTPUT_PATH = f"DUPLICATE_ID_FLAGS_{datetime.now():%Y-%m-%d_%H%M%S}.csv"

ACTIVE_DISBURSED_STATUSES = ['disbursed', 'active', 'overdue', 'completed']

HEADERS = ['ID NUMBER', 'TIMES REUSED', 'CLIENT ID', 'CLIENT NAME', 'ID TYPE']


def main():
    loans = (
        Loan.objects
        .filter(status__in=ACTIVE_DISBURSED_STATUSES)
        .select_related('client')
    )

    clients = {l.client_id: l.client for l in loans}

    by_id_number = {}
    for c in clients.values():
        idn = (c.id_number or '').strip()
        if idn:
            by_id_number.setdefault(idn, []).append(c)

    duplicates = {idn: cs for idn, cs in by_id_number.items() if len(cs) > 1}

    count = 0
    with open(OUTPUT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        for idn, cs in sorted(duplicates.items(), key=lambda kv: -len(kv[1])):
            for c in cs:
                writer.writerow([idn, len(cs), c.client_id, c.full_name, c.get_id_type_display()])
                count += 1

    print(
        f"{len(duplicates)} duplicate ID numbers, {count} affected client "
        f"records -> {OUTPUT_PATH}"
    )


if __name__ == '__main__':
    main()
