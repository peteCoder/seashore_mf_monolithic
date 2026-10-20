"""
Management command: redate_client_registration
==================================================

Corrects the registration/approval dates on a single client record from
16 Oct 2026 to 17 Oct 2026, per explicit user request.

Client: Okolie Joy (c9c7e594-bc73-4f22-9d08-d60e18d533d6)

Fields changed (time-of-day preserved on the datetime field):
  1. Client.created_at      2026-10-16 13:52:55 -> 2026-10-17 13:52:55
  2. Client.approval_date   2026-10-16           -> 2026-10-17
  3. Client.activation_date 2026-10-16           -> 2026-10-17

Fields deliberately left untouched:
  - Client.approved_at (2026-10-17 07:24) is already the 17th.
  - Client.registration_date is currently unset (None) — nothing to redate.

created_at is updated via queryset.update() rather than instance.save(), to
bypass any save()-time side effects on an unrelated field and because
auto_now_add only fires on INSERT, not UPDATE, so it's safe to set directly
on an existing row either way.

Usage:
    python manage.py redate_client_registration --dry-run
    python manage.py redate_client_registration --confirm
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone


CLIENT_ID = 'c9c7e594-bc73-4f22-9d08-d60e18d533d6'
OLD_DATE = datetime.date(2026, 10, 16)
NEW_DATE = datetime.date(2026, 10, 17)


def _replace_date(original_dt, new_date):
    """Timezone-aware datetime with the same time-of-day as original_dt but
    the calendar date replaced by new_date."""
    local_dt = timezone.localtime(original_dt)
    return timezone.make_aware(datetime.datetime.combine(new_date, local_dt.time()))


class Command(BaseCommand):
    help = "Redate client Okolie Joy's registration/approval dates from 16 Oct 2026 to 17 Oct 2026"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true', help='Show what will change without writing to the DB')
        group.add_argument('--confirm', action='store_true', help='Apply the change')

    def handle(self, *args, **options):
        from core.models import Client

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(f'\n=== redate_client_registration [{mode}] ===\n'))

        client = Client.all_objects.get(id=CLIENT_ID)
        self.stdout.write(f'Client: {client.get_full_name()} ({client.client_id})')

        fields = [
            ('created_at', client.created_at, _replace_date(client.created_at, NEW_DATE)),
            ('approval_date', client.approval_date, NEW_DATE),
            ('activation_date', client.activation_date, NEW_DATE),
        ]

        for name, before, after in fields:
            if before is None:
                raise CommandError(f'{name} is unexpectedly None — aborting, state has changed since this was written.')
            before_date = before.date() if hasattr(before, 'date') else before
            if before_date != OLD_DATE:
                raise CommandError(
                    f'{name} is {before} (date {before_date}), not {OLD_DATE} as expected — '
                    f'aborting, state has changed since this was written.'
                )

        self.stdout.write('\nWILL CHANGE')
        for name, before, after in fields:
            self.stdout.write(f'  {name}: {before} -> {after}')

        self.stdout.write('\nUNCHANGED (already correct / not applicable)')
        self.stdout.write(f'  approved_at: {client.approved_at}')
        self.stdout.write(f'  registration_date: {client.registration_date}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete - no changes written. Re-run with --confirm to apply.\n'))
            return

        with db_transaction.atomic():
            Client.all_objects.filter(id=CLIENT_ID).update(
                created_at=fields[0][2],
                approval_date=fields[1][2],
                activation_date=fields[2][2],
            )

        client.refresh_from_db()
        self.stdout.write(self.style.SUCCESS('\nUpdated.\n'))
        self.stdout.write('FINAL STATE')
        self.stdout.write(f'  created_at: {client.created_at}')
        self.stdout.write(f'  approval_date: {client.approval_date}')
        self.stdout.write(f'  activation_date: {client.activation_date}')
        self.stdout.write(f'  approved_at (unchanged): {client.approved_at}')
