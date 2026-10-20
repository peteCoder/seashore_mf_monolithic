"""
Management command: revert_client_registration_redate
=========================================================

Reverts redate_client_registration.py: 16 Oct 2026 was correct all along
(it's a Friday; 17 Oct is a Saturday), so this restores the exact original
values on the same client.

Client: Okolie Joy (c9c7e594-bc73-4f22-9d08-d60e18d533d6)

Fields restored to their exact original values:
  1. Client.created_at      2026-10-17 13:52:55.753875+00:00 -> 2026-10-16 13:52:55.753875+00:00
  2. Client.approval_date   2026-10-17                        -> 2026-10-16
  3. Client.activation_date 2026-10-17                        -> 2026-10-16

Untouched (never changed): approved_at, registration_date.

Usage:
    python manage.py revert_client_registration_redate --dry-run
    python manage.py revert_client_registration_redate --confirm
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone


CLIENT_ID = 'c9c7e594-bc73-4f22-9d08-d60e18d533d6'
CURRENT_DATE = datetime.date(2026, 10, 17)
ORIGINAL_DATE = datetime.date(2026, 10, 16)
ORIGINAL_CREATED_AT = datetime.datetime(
    2026, 10, 16, 13, 52, 55, 753875, tzinfo=datetime.timezone.utc
)


class Command(BaseCommand):
    help = "Revert client Okolie Joy's dates back to the original 16 Oct 2026 (a Friday)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true', help='Show what will change without writing to the DB')
        group.add_argument('--confirm', action='store_true', help='Apply the change')

    def handle(self, *args, **options):
        from core.models import Client

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(f'\n=== revert_client_registration_redate [{mode}] ===\n'))

        client = Client.all_objects.get(id=CLIENT_ID)
        self.stdout.write(f'Client: {client.get_full_name()} ({client.client_id})')

        checks = [
            ('created_at', client.created_at, ORIGINAL_CREATED_AT),
            ('approval_date', client.approval_date, ORIGINAL_DATE),
            ('activation_date', client.activation_date, ORIGINAL_DATE),
        ]
        for name, current, restore_to in checks:
            current_date = current.date() if hasattr(current, 'date') else current
            if current_date != CURRENT_DATE:
                raise CommandError(
                    f'{name} is {current} (date {current_date}), not {CURRENT_DATE} as expected — '
                    f'aborting, state has changed since this was written.'
                )

        self.stdout.write('\nWILL RESTORE')
        for name, current, restore_to in checks:
            self.stdout.write(f'  {name}: {current} -> {restore_to}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete - no changes written. Re-run with --confirm to apply.\n'))
            return

        with db_transaction.atomic():
            Client.all_objects.filter(id=CLIENT_ID).update(
                created_at=ORIGINAL_CREATED_AT,
                approval_date=ORIGINAL_DATE,
                activation_date=ORIGINAL_DATE,
            )

        client.refresh_from_db()
        self.stdout.write(self.style.SUCCESS('\nReverted.\n'))
        self.stdout.write('FINAL STATE')
        self.stdout.write(f'  created_at: {client.created_at}')
        self.stdout.write(f'  approval_date: {client.approval_date}')
        self.stdout.write(f'  activation_date: {client.activation_date}')
        self.stdout.write(f'  approved_at (never changed): {client.approved_at}')
