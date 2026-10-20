"""
Management command: redate_client_approved_at
=================================================

Follow-up to revert_client_registration_redate.py: that command restored
created_at/approval_date/activation_date to 16 Oct 2026, but approved_at
("Approval Date & Time") was left untouched at 17 Oct 2026 — it had already
been on the 17th before any of these corrections started, and only now,
with the whole record settling on the 16th (a Friday; the 17th is a
Saturday), does it need to move too.

Also sets registration_date, which was unset (None) throughout all prior
corrections, to 16 Oct 2026 — per explicit follow-up request that every
date on this record read the 16th.

Client: Okolie Joy (c9c7e594-bc73-4f22-9d08-d60e18d533d6)

Fields changed:
  Client.approved_at        2026-10-17 07:24:03.841703+00:00 -> 2026-10-16 07:24:03.841703+00:00
  Client.registration_date  None                              -> 2026-10-16

Usage:
    python manage.py redate_client_approved_at --dry-run
    python manage.py redate_client_approved_at --confirm
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


CLIENT_ID = 'c9c7e594-bc73-4f22-9d08-d60e18d533d6'
CURRENT_DATE = datetime.date(2026, 10, 17)
NEW_DATE = datetime.date(2026, 10, 16)


class Command(BaseCommand):
    help = "Shift client Okolie Joy's approved_at back one day, from 17 Oct 2026 to 16 Oct 2026"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true', help='Show what will change without writing to the DB')
        group.add_argument('--confirm', action='store_true', help='Apply the change')

    def handle(self, *args, **options):
        from core.models import Client

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(f'\n=== redate_client_approved_at [{mode}] ===\n'))

        client = Client.all_objects.get(id=CLIENT_ID)
        self.stdout.write(f'Client: {client.get_full_name()} ({client.client_id})')

        current = client.approved_at
        if current is None or current.date() != CURRENT_DATE:
            raise CommandError(
                f'approved_at is {current}, not {CURRENT_DATE} as expected — '
                f'aborting, state has changed since this was written.'
            )
        new_approved_at = current.replace(year=NEW_DATE.year, month=NEW_DATE.month, day=NEW_DATE.day)

        if client.registration_date is not None:
            raise CommandError(
                f'registration_date is {client.registration_date}, expected None — '
                f'aborting, state has changed since this was written.'
            )

        self.stdout.write('\nWILL CHANGE')
        self.stdout.write(f'  approved_at: {current} -> {new_approved_at}')
        self.stdout.write(f'  registration_date: {client.registration_date} -> {NEW_DATE}')

        self.stdout.write('\nFor reference (already correct, untouched)')
        self.stdout.write(f'  created_at: {client.created_at}')
        self.stdout.write(f'  approval_date: {client.approval_date}')
        self.stdout.write(f'  activation_date: {client.activation_date}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete - no changes written. Re-run with --confirm to apply.\n'))
            return

        with db_transaction.atomic():
            Client.all_objects.filter(id=CLIENT_ID).update(
                approved_at=new_approved_at,
                registration_date=NEW_DATE,
            )

        client.refresh_from_db()
        self.stdout.write(self.style.SUCCESS('\nUpdated.\n'))
        self.stdout.write(f'FINAL STATE  approved_at: {client.approved_at}')
        self.stdout.write(f'FINAL STATE  registration_date: {client.registration_date}')
