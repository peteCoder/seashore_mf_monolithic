"""
Management command: redate_client_registration_fees
========================================================

Follow-up to redate_client_registration.py / revert_client_registration_redate.py
/ redate_client_approved_at.py: those corrected the Client record's own date
fields to 16 Oct 2026, but the two fee-collection Transactions created at
registration (Registration Fee, Membership Card Fee) and their linked
JournalEntry rows were still recording 17 Oct 2026 — discovered by the user
from the transaction list.

Client: Okolie Joy (c9c7e594-bc73-4f22-9d08-d60e18d533d6)

Records changed (time-of-day preserved; shifted back exactly one day):
  Transaction  e4a17c2b-29ea-42e9-8bc5-6ceb3e921857  (Registration Fee, NGN 2,000)
    transaction_date, created_at, updated_at : 17 Oct -> 16 Oct
    transaction_ref : TXN20261017072404871417 -> TXN20261016072404871417

  Transaction  d38ffd1c-305b-420c-81c9-77769a4b42e8  (Membership Card Fee, NGN 500)
    transaction_date, created_at, updated_at : 17 Oct -> 16 Oct
    transaction_ref : TXN20261017072406329477 -> TXN20261016072406329477

  JournalEntry  545313aa-eb3a-40a2-9fa1-65dd9273c932  (JE-20261017-290224)
    transaction_date, posting_date, posted_at, created_at : 17 Oct -> 16 Oct
    journal_number     : JE-20261017-290224      -> JE-20261016-290224
    reference_number   : TXN20261017072404871417 -> TXN20261016072404871417 (mirrors the transaction above)

  JournalEntry  bd6c722c-44a7-4177-9ced-44beb79f9386  (JE-20261017-027197)
    transaction_date, posting_date, posted_at, created_at : 17 Oct -> 16 Oct
    journal_number     : JE-20261017-027197      -> JE-20261016-027197
    reference_number   : TXN20261017072406329477 -> TXN20261016072406329477

JournalEntryLine rows are untouched (they have no date fields of their own).

Usage:
    python manage.py redate_client_registration_fees --dry-run
    python manage.py redate_client_registration_fees --confirm
"""

import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


CLIENT_ID = 'c9c7e594-bc73-4f22-9d08-d60e18d533d6'
CURRENT_DATE = datetime.date(2026, 10, 17)
NEW_DATE = datetime.date(2026, 10, 16)

TRANSACTION_IDS = [
    'e4a17c2b-29ea-42e9-8bc5-6ceb3e921857',
    'd38ffd1c-305b-420c-81c9-77769a4b42e8',
]
JOURNAL_ENTRY_IDS = [
    '545313aa-eb3a-40a2-9fa1-65dd9273c932',
    'bd6c722c-44a7-4177-9ced-44beb79f9386',
]


def _shift_back_one_day(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value - datetime.timedelta(days=1)
    return value - datetime.timedelta(days=1)


def _swap_date_digits(text):
    """Replace the leading '20261017' date segment with '20261016'."""
    old_digits = CURRENT_DATE.strftime('%Y%m%d')
    new_digits = NEW_DATE.strftime('%Y%m%d')
    if old_digits not in text:
        raise CommandError(f'Expected date digits {old_digits} not found in {text!r} — aborting.')
    return text.replace(old_digits, new_digits, 1)


class Command(BaseCommand):
    help = "Redate Okolie Joy's registration fee transaction/journal entries from 17 Oct 2026 to 16 Oct 2026"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true', help='Show what will change without writing to the DB')
        group.add_argument('--confirm', action='store_true', help='Apply the change')

    def handle(self, *args, **options):
        from core.models import Client, Transaction, JournalEntry

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(f'\n=== redate_client_registration_fees [{mode}] ===\n'))

        client = Client.objects.get(id=CLIENT_ID)
        self.stdout.write(f'Client: {client.get_full_name()} ({client.client_id})\n')

        txns = list(Transaction.objects.filter(id__in=TRANSACTION_IDS))
        if len(txns) != len(TRANSACTION_IDS):
            raise CommandError('Not all expected transactions were found — state has changed since this was written.')

        jes = list(JournalEntry.objects.filter(id__in=JOURNAL_ENTRY_IDS))
        if len(jes) != len(JOURNAL_ENTRY_IDS):
            raise CommandError('Not all expected journal entries were found — state has changed since this was written.')

        plan = []

        for t in txns:
            if t.transaction_date.date() != CURRENT_DATE:
                raise CommandError(f'{t.transaction_ref}: transaction_date is not {CURRENT_DATE} — aborting.')
            new_ref = _swap_date_digits(t.transaction_ref)
            if Transaction.objects.filter(transaction_ref=new_ref).exclude(id=t.id).exists():
                raise CommandError(f'{new_ref} already exists on another transaction — aborting.')
            plan.append(('Transaction', t.transaction_ref, t, {
                'transaction_date': _shift_back_one_day(t.transaction_date),
                'created_at': _shift_back_one_day(t.created_at),
                'updated_at': _shift_back_one_day(t.updated_at),
                'transaction_ref': new_ref,
            }))

        for je in jes:
            if je.transaction_date != CURRENT_DATE:
                raise CommandError(f'{je.journal_number}: transaction_date is not {CURRENT_DATE} — aborting.')
            new_journal_number = _swap_date_digits(je.journal_number)
            new_reference_number = _swap_date_digits(je.reference_number)
            if JournalEntry.objects.filter(journal_number=new_journal_number).exclude(id=je.id).exists():
                raise CommandError(f'{new_journal_number} already exists on another journal entry — aborting.')
            plan.append(('JournalEntry', je.journal_number, je, {
                'transaction_date': NEW_DATE,
                'posting_date': _shift_back_one_day(je.posting_date) if je.posting_date else None,
                'posted_at': _shift_back_one_day(je.posted_at),
                'created_at': _shift_back_one_day(je.created_at),
                'journal_number': new_journal_number,
                'reference_number': new_reference_number,
            }))

        self.stdout.write('WILL CHANGE')
        for kind, label, obj, changes in plan:
            self.stdout.write(f'\n  {kind} {label}')
            for field, new_value in changes.items():
                self.stdout.write(f'    {field}: {getattr(obj, field)} -> {new_value}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\n\nDry run complete - no changes written. Re-run with --confirm to apply.\n'))
            return

        with db_transaction.atomic():
            for kind, label, obj, changes in plan:
                model = Transaction if kind == 'Transaction' else JournalEntry
                model.objects.filter(id=obj.id).update(**changes)

        self.stdout.write(self.style.SUCCESS('\n\nUpdated.\n'))
        self.stdout.write('FINAL STATE')
        for t in Transaction.objects.filter(id__in=TRANSACTION_IDS):
            self.stdout.write(f'  {t.transaction_ref}  transaction_date={t.transaction_date}')
        for je in JournalEntry.objects.filter(id__in=JOURNAL_ENTRY_IDS):
            self.stdout.write(
                f'  {je.journal_number}  transaction_date={je.transaction_date}  '
                f'posting_date={je.posting_date}  posted_at={je.posted_at}'
            )
