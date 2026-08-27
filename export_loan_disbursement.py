"""
One-off export: all active/disbursed loans, for the GOXI Microloan
Protection submission -- plain CSV, no title/branding row.

Scope (confirmed with user 2026-08-18):
    Loan.status in ('disbursed', 'active', 'overdue', 'completed')
    i.e. every loan that has actually had money paid out to the client,
    whether still being repaid, late, or already fully repaid.
    Excludes: pending_fees, pending_approval, approved, rejected,
    cancelled, written_off (never disbursed / never became a real loan).

NEXT OF KIN / PHONE NO OF NEXT OF KIN: the NextOfKin table has 0 rows for
all 670 clients system-wide, so it's used first (in case it's ever
populated) and falls back to Client.emergency_contact_name/phone, which
IS populated -- but only for 6 of the 477 clients in this loan set.
Confirmed with user 2026-08-18: still worth wiring in as a free win even
at that coverage, since it'll auto-improve as more clients get emergency
contact info on file.

Structure: single header row, one row per loan below it -- no title
row, no blank separator rows (per user feedback on the .xlsx template's
"GOXI LOAN DISBURSEMENT TEMPLATE..." title/watermark row and layout).

Run from the seashore/ directory (same folder as manage.py):
    python export_loan_disbursement.py
"""
import csv
import os
from datetime import datetime

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'seashore.settings')
django.setup()

from core.models.all_models import Loan, NextOfKin

OUTPUT_PATH = f"LOAN_DISBURSEMENT_{datetime.now():%Y-%m-%d_%H%M%S}.csv"

ACTIVE_DISBURSED_STATUSES = ['disbursed', 'active', 'overdue', 'completed']

HEADERS = [
    'S/N',
    'TYPE OF I.D',
    'CUSTOMER I.D NO',
    'CUSTOMER NAME',
    'CUSTOMER ADDRESS',
    'PHONE NO',
    'GENDER',
    'OCCUPATION',
    'DATE OF BIRTH',
    'NEXT OF KIN',
    'PHONE NO OF NEXT OF KIN',
    'DATE DISBURSED',
    'EXPIRY DATE',
    'LOAN TERM',
    'DISBURSEMENT AMOUNT',
]

DATE_FMT = '%Y-%m-%d'


def fmt_date(d):
    return d.strftime(DATE_FMT) if d else ''


def as_text(value):
    """
    Force Excel to keep a numeric-looking value (phone numbers, ID numbers)
    as text instead of silently converting it to scientific notation /
    losing leading zeros. CSV has no cell-format metadata, so the only
    reliable way to stop Excel from doing this is the ="..." formula
    trick, which Excel always honors regardless of column width.
    """
    value = value or ''
    return f'="{value}"'


def main():
    loans = (
        Loan.objects
        .filter(status__in=ACTIVE_DISBURSED_STATUSES)
        .select_related('client')
        .order_by('disbursement_date', 'loan_number')
    )

    client_ids = loans.values_list('client_id', flat=True)
    nok_by_client = {
        n.client_id: n
        for n in NextOfKin.objects.filter(client_id__in=list(client_ids))
    }

    count = 0
    with open(OUTPUT_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)

        for sn, loan in enumerate(loans, start=1):
            client = loan.client
            nok = nok_by_client.get(client.id)

            nok_name = nok.name if nok else (client.emergency_contact_name or '')
            nok_phone = nok.phone if nok else (client.emergency_contact_phone or '')

            writer.writerow([
                sn,
                client.get_id_type_display(),
                as_text(client.id_number),
                client.full_name,
                client.address,
                as_text(client.phone),
                client.get_gender_display(),
                client.occupation,
                fmt_date(client.date_of_birth),
                nok_name,
                as_text(nok_phone) if nok_phone else '',
                fmt_date(loan.disbursement_date.date() if loan.disbursement_date else None),
                fmt_date(loan.final_repayment_date),
                f"{loan.duration_months} Months",
                float(loan.amount_disbursed or loan.principal_amount),
            ])
            count += 1

    print(f"Wrote {count} loans to {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
