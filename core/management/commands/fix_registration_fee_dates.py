"""
Management command: fix_registration_fee_dates
================================================

Corrects Transaction.transaction_date and JournalEntry.transaction_date for
all Registration Fee (₦2,000) and Membership Card Fee (₦100) records that
were saved with the current date instead of the client's registration_date.

Usage:
    python manage.py fix_registration_fee_dates
    python manage.py fix_registration_fee_dates --dry-run
    python manage.py fix_registration_fee_dates --client-id <uuid>
"""

import datetime
import logging

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

FEE_TYPES = ['registration_fee', 'membership_card_fee']


class Command(BaseCommand):
    help = (
        "Fix transaction_date on Registration Fee and Membership Card Fee "
        "transactions (and their linked journal entries) to match the client's "
        "registration_date."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without writing to the database.',
        )
        parser.add_argument(
            '--client-id',
            type=str,
            default=None,
            help='Limit corrections to a single client UUID.',
        )

    def handle(self, *args, **options):
        from core.models import Transaction, JournalEntry, Client

        dry_run = options['dry_run']
        client_id = options['client_id']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be saved.\n'))

        # Base queryset: only the two fee types
        txns = Transaction.objects.filter(
            transaction_type__in=FEE_TYPES,
        ).select_related('client')

        if client_id:
            txns = txns.filter(client__id=client_id)

        txn_fixed = 0
        je_fixed = 0
        skipped = 0

        for txn in txns.iterator():
            client = txn.client

            if not client or not client.registration_date:
                skipped += 1
                continue

            reg_date = client.registration_date  # DateField → date object
            # Convert to timezone-aware datetime (start of day) for DateTimeField
            target_dt = timezone.make_aware(
                datetime.datetime.combine(reg_date, datetime.time.min)
            )

            txn_date_as_date = (
                txn.transaction_date.date()
                if isinstance(txn.transaction_date, datetime.datetime)
                else txn.transaction_date
            )

            needs_update = txn_date_as_date != reg_date

            if needs_update:
                self.stdout.write(
                    f"  Txn {txn.transaction_ref} | client={client.client_id} | "
                    f"type={txn.transaction_type} | "
                    f"current={txn_date_as_date} → target={reg_date}"
                )

                if not dry_run:
                    with db_transaction.atomic():
                        txn.transaction_date = target_dt
                        txn.save(update_fields=['transaction_date'])

                        # Fix linked journal entries
                        linked_journals = JournalEntry.objects.filter(transaction=txn)
                        count = linked_journals.update(transaction_date=reg_date)
                        je_fixed += count

                txn_fixed += 1
            else:
                # Already correct
                pass

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDRY RUN complete. Would fix {txn_fixed} transaction(s). '
                    f'Skipped {skipped} (no registration_date).'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDone. Fixed {txn_fixed} transaction(s) and '
                    f'{je_fixed} journal entry record(s). '
                    f'Skipped {skipped} (no registration_date).'
                )
            )
