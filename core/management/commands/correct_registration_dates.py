"""
Management command: correct_registration_dates
===============================================

Corrects the transaction_date on Client Registration Fee and
Membership Card Fee transactions (and their journal entries)
from April 20, 2026 to April 28, 2026 for four clients.

Clients
-------
  1. Rachael Isojie Ehigiator  7bd0aaab
  2. Juliet Ogidi              0c1947a0
  3. Blessing Ewharekuko       cecbbc87
  4. Esther Amadin             e7eefce9

Old date: 2026-04-20  (stored as UTC 2026-04-19 23:00:00+00:00)
New date: 2026-04-28  (stored as UTC 2026-04-27 23:00:00+00:00)

Usage
-----
  python manage.py correct_registration_dates --dry-run
  python manage.py correct_registration_dates --commit
"""

import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone


OLD_DATE     = datetime.date(2026, 4, 20)
NEW_DATE     = datetime.date(2026, 4, 28)
# WAT is UTC+1; midnight local = 23:00 previous day UTC
OLD_DATETIME = datetime.datetime(2026, 4, 19, 23, 0, 0, tzinfo=datetime.timezone.utc)
NEW_DATETIME = datetime.datetime(2026, 4, 27, 23, 0, 0, tzinfo=datetime.timezone.utc)

TRANSACTIONS = [
    # (txn_id, client_name, fee_type)
    ('54a08b60-679b-4ea3-bea1-1ceab60b0dfe', 'Rachael Isojie Ehigiator', 'membership_card_fee'),
    ('13a6cf71-1ba0-4219-b3b1-2b12ba4d335c', 'Rachael Isojie Ehigiator', 'registration_fee'),
    ('db0a971d-a774-40f1-916c-86a8b161e3b0', 'Juliet Ogidi',             'membership_card_fee'),
    ('9e2604ce-e034-4205-8a60-15537c88a8ec', 'Juliet Ogidi',             'registration_fee'),
    ('78626559-0fbf-4a1c-832f-9bb4d7d8f1f2', 'Blessing Ewharekuko',      'membership_card_fee'),
    ('d73fe7eb-e7d8-4539-b657-e86c0d3c421f', 'Blessing Ewharekuko',      'registration_fee'),
    ('d1645723-6c44-4611-83f7-99430a107cd1', 'Esther Amadin',            'membership_card_fee'),
    ('2ee9d680-b952-4bc9-b5ee-668af430cc5f', 'Esther Amadin',            'registration_fee'),
]


class Command(BaseCommand):
    help = 'Correct registration/membership transaction dates from Apr 20 to Apr 28, 2026'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        from core.models import Transaction, JournalEntry

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(
            f'\n=== correct_registration_dates [{mode}] ===\n'
        ))
        self.stdout.write(f'Changing transaction_date: {OLD_DATE} -> {NEW_DATE}\n')

        pairs = []   # (txn, [je, ...])

        for txn_id, client_name, fee_type in TRANSACTIONS:
            try:
                txn = Transaction.objects.get(id=txn_id)
            except Transaction.DoesNotExist:
                raise CommandError(f'Transaction {txn_id} not found.')

            if txn.transaction_date != OLD_DATETIME:
                raise CommandError(
                    f'Transaction {txn.transaction_ref} has unexpected date '
                    f'{txn.transaction_date} (expected {OLD_DATETIME}). Aborting.'
                )
            if txn.transaction_type != fee_type:
                raise CommandError(
                    f'Transaction {txn.transaction_ref} has type {txn.transaction_type!r} '
                    f'(expected {fee_type!r}). Aborting.'
                )

            jes = list(JournalEntry.objects.filter(transaction=txn))
            if not jes:
                raise CommandError(
                    f'No JournalEntry found for transaction {txn.transaction_ref}. Aborting.'
                )
            for je in jes:
                if je.transaction_date != OLD_DATE:
                    raise CommandError(
                        f'JE {je.journal_number} has date {je.transaction_date} '
                        f'(expected {OLD_DATE}). Aborting.'
                    )

            self.stdout.write(
                f'  [{client_name}] {fee_type}'
            )
            self.stdout.write(
                f'    TXN {txn.transaction_ref}  {txn.transaction_date} -> {NEW_DATETIME}'
            )
            for je in jes:
                self.stdout.write(
                    f'    JE  {je.journal_number}  {je.transaction_date} -> {NEW_DATE}'
                )
            pairs.append((txn, jes))

        self.stdout.write(
            f'\n  Total: {len(pairs)} transactions, '
            f'{sum(len(jes) for _, jes in pairs)} journal entries\n'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run complete. Re-run with --commit to apply.\n'))
            return

        with db_transaction.atomic():
            for txn, jes in pairs:
                txn.transaction_date = NEW_DATETIME
                txn.save(update_fields=['transaction_date'])
                for je in jes:
                    je.transaction_date = NEW_DATE
                    je.save(update_fields=['transaction_date'])

        self.stdout.write(self.style.SUCCESS('Correction applied successfully.\n'))
        self.stdout.write(
            f'Updated {len(pairs)} transactions and '
            f'{sum(len(jes) for _, jes in pairs)} journal entries '
            f'from {OLD_DATE} to {NEW_DATE}.'
        )
