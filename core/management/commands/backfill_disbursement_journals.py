"""
Management command to backfill missing journal entries for loan disbursement transactions.

For each Transaction(type='loan_disbursement') that has no linked JournalEntry:
  1. If a JournalEntry already exists for the loan (entry_type='loan_disbursement'),
     link it by setting journal_entry.transaction = txn.
  2. Otherwise, create a new journal entry and link it.

Usage:
    python manage.py backfill_disbursement_journals
    python manage.py backfill_disbursement_journals --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill missing journal entries for loan disbursement transactions"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        from core.models import Transaction, JournalEntry
        from core.utils.accounting_helpers import post_loan_disbursement_journal

        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved\n"))

        # All completed loan disbursement transactions with no linked journal entry
        orphan_txns = Transaction.objects.filter(
            transaction_type='loan_disbursement',
            status='completed',
        ).prefetch_related('journal_entries').select_related('loan', 'processed_by')

        orphan_txns = [t for t in orphan_txns if not t.journal_entries.exists()]

        self.stdout.write(f"Found {len(orphan_txns)} disbursement transaction(s) with no linked journal entry.\n")

        linked = 0
        created = 0
        errors = 0

        for txn in orphan_txns:
            loan = txn.loan
            if not loan:
                self.stdout.write(
                    self.style.WARNING(f"  [SKIP] Transaction {txn.id} has no related loan — skipping")
                )
                continue

            self.stdout.write(
                f"  Processing txn {txn.id} | Loan {loan.loan_number} | "
                f"Amount N{txn.amount:,.2f} | Date {txn.transaction_date}"
            )

            # Check if a journal entry already exists for this loan (just not linked)
            existing_je = JournalEntry.objects.filter(
                entry_type='loan_disbursement',
                loan=loan,
                transaction__isnull=True,
            ).first()

            if existing_je:
                if not dry_run:
                    existing_je.transaction = txn
                    existing_je.save(update_fields=['transaction'])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    -> Linked existing journal {existing_je.journal_number} to txn {txn.id}"
                    )
                )
                linked += 1
            else:
                # No journal entry at all — create one
                if not dry_run:
                    try:
                        with db_transaction.atomic():
                            je = post_loan_disbursement_journal(
                                loan,
                                txn.processed_by,
                                transaction_obj=txn,
                            )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"    -> Created new journal {je.journal_number} for txn {txn.id}"
                            )
                        )
                        created += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"    ✗ Error creating journal for txn {txn.id}: {e}")
                        )
                        errors += 1
                else:
                    self.stdout.write(f"    -> Would create new journal entry for txn {txn.id}")
                    created += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN complete — would link {linked}, create {created}, skip errors {errors}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Done — linked {linked} existing, created {created} new, {errors} error(s)"
            ))
