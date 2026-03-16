"""
Management Command: cleanup_duplicate_fees
==========================================

Cleans up two categories of bad fee data:

  1. OBSOLETE: id_card_fee transactions — deleted unconditionally because the
     ID Card fee was removed from the registration fee breakdown. Every
     id_card_fee transaction (and its journal entries) should be removed.

  2. DUPLICATES: registration_fee / membership_card_fee that appear more than
     once for the same client — keep the OLDEST, delete the rest.

For each deleted Transaction its JournalEntry records are deleted first
(which cascade-deletes JournalEntryLine records), then the Transaction itself.

Usage:
  # Preview only (no changes):
  python manage.py cleanup_duplicate_fees

  # Actually delete:
  python manage.py cleanup_duplicate_fees --execute
"""

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from core.models import Client, Transaction, JournalEntry


# These types should only ever have ONE entry per client — keep the oldest.
DEDUP_FEE_TYPES = ['registration_fee', 'membership_card_fee']

# These types are completely obsolete and should be deleted regardless of count.
OBSOLETE_FEE_TYPES = ['id_card_fee']


class Command(BaseCommand):
    help = 'Remove obsolete id_card_fee entries and duplicate client registration fee transactions.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            default=False,
            help='Actually delete. Without this flag the command is a dry run.',
        )

    def _delete_transaction(self, txn, execute):
        """Hard-delete a transaction and all its journal entries / lines."""
        journals = JournalEntry.objects.filter(transaction=txn)
        journal_count = journals.count()
        if execute:
            with db_transaction.atomic():
                journals.delete()       # queryset delete → bypasses soft-delete, real SQL DELETE
                txn.delete(hard=True)   # hard=True → BaseModel calls super().delete(), real SQL DELETE
        return journal_count

    def handle(self, *args, **options):
        execute = options['execute']
        mode = 'EXECUTE' if execute else 'DRY RUN'
        self.stdout.write(f'\n[{mode}] Scanning client fee transactions...\n')

        total_txns = 0
        total_journals = 0

        # ── 1. Obsolete id_card_fee transactions ─────────────────────────────
        self.stdout.write('--- Obsolete id_card_fee transactions ---')
        obsolete_txns = Transaction.objects.filter(
            transaction_type__in=OBSOLETE_FEE_TYPES
        ).select_related('client').order_by('created_at')

        if not obsolete_txns.exists():
            self.stdout.write('  None found.\n')
        else:
            for txn in obsolete_txns:
                client_label = (
                    f'{txn.client.get_full_name()} ({txn.client.client_id})'
                    if txn.client else 'no client'
                )
                journals = JournalEntry.objects.filter(transaction=txn)
                journal_count = journals.count()
                self.stdout.write(
                    f'  [{txn.transaction_type}] {txn.transaction_ref}  '
                    f'₦{txn.amount:,.2f}  {txn.created_at.strftime("%Y-%m-%d %H:%M")}  '
                    f'client={client_label}  journals={journal_count}'
                )
                if execute:
                    with db_transaction.atomic():
                        journals.delete()
                        txn.delete(hard=True)
                total_txns += 1
                total_journals += journal_count
            self.stdout.write('')

        # ── 2. Duplicate registration_fee / membership_card_fee ───────────────
        self.stdout.write('--- Duplicate fee transactions (per client) ---')
        found_any_dupes = False

        clients = Client.objects.order_by('created_at')
        for client in clients:
            for fee_type in DEDUP_FEE_TYPES:
                txns = list(
                    Transaction.objects.filter(
                        client=client,
                        transaction_type=fee_type,
                    ).order_by('created_at')
                )
                if len(txns) <= 1:
                    continue

                found_any_dupes = True
                keep = txns[0]
                duplicates = txns[1:]

                self.stdout.write(
                    f'  Client: {client.get_full_name()} ({client.client_id})  '
                    f'type={fee_type}  keeping={keep.transaction_ref}'
                )
                for dup in duplicates:
                    journals = JournalEntry.objects.filter(transaction=dup)
                    journal_count = journals.count()
                    self.stdout.write(
                        f'    Deleting: {dup.transaction_ref}  '
                        f'₦{dup.amount:,.2f}  '
                        f'{dup.created_at.strftime("%Y-%m-%d %H:%M")}  '
                        f'journals={journal_count}'
                    )
                    if execute:
                        with db_transaction.atomic():
                            journals.delete()
                            dup.delete(hard=True)
                    total_txns += 1
                    total_journals += journal_count

        if not found_any_dupes:
            self.stdout.write('  None found.\n')

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('\n' + '─' * 60)
        if total_txns == 0:
            self.stdout.write(self.style.SUCCESS('Nothing to clean up.'))
        elif execute:
            self.stdout.write(self.style.SUCCESS(
                f'Done. Deleted {total_txns} transaction(s) and '
                f'{total_journals} journal entr{"y" if total_journals == 1 else "ies"}.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: would delete {total_txns} transaction(s) and '
                f'{total_journals} journal entr{"y" if total_journals == 1 else "ies"}.\n'
                f'Re-run with --execute to apply.'
            ))
        self.stdout.write('')
