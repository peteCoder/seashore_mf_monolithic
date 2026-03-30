"""
Management command: redate_loan_fees
======================================

Corrects every date on a loan's application-fees payment:

  1. Loan.fees_paid_date                   (DateTimeField)
  2. Transaction.transaction_date          (charges_at_disbursement)
  3. JournalEntry.transaction_date         (DateField)
  4. JournalEntry.posting_date             (DateField)
  5. JournalEntry.posted_at               (DateTimeField — audit trail "Posted By" date)
  6. JournalEntry.created_at              (DateTimeField — audit trail "Created By" date)
                                           auto_now_add so updated via queryset .update()

JournalEntryLine has no date fields — unchanged.
Journal number and transaction_ref are unique identifiers — unchanged.

The original TIME-OF-DAY (HH:MM:SS) is preserved on all DateTimeFields;
only the calendar date is replaced.

Usage:
    python manage.py redate_loan_fees <loan-uuid> <new-date> --dry-run
    python manage.py redate_loan_fees <loan-uuid> <new-date> --confirm

Example:
    python manage.py redate_loan_fees 5f74e11c-e5c1-4d19-a6d4-067ec84d0a74 2026-03-12 --dry-run
    python manage.py redate_loan_fees 5f74e11c-e5c1-4d19-a6d4-067ec84d0a74 2026-03-12 --confirm
"""

import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone


def _replace_date(original_dt, new_date):
    """
    Return a timezone-aware datetime with the same time-of-day as
    original_dt but with the calendar date replaced by new_date.
    If original_dt is None or not a datetime, return midnight on new_date.
    """
    if original_dt and isinstance(original_dt, datetime.datetime):
        local_dt = timezone.localtime(original_dt)
        combined = datetime.datetime.combine(new_date, local_dt.time())
        return timezone.make_aware(combined)
    return timezone.make_aware(datetime.datetime.combine(new_date, datetime.time.min))


class Command(BaseCommand):
    help = "Re-date a loan's application-fees transaction, journal entry, and audit trail."

    def add_arguments(self, parser):
        parser.add_argument(
            'loan_uuid',
            type=str,
            help='UUID of the loan whose fees date you want to change.',
        )
        parser.add_argument(
            'new_date',
            type=str,
            help='New date in YYYY-MM-DD format (e.g. 2026-03-12).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what will change without writing anything.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually execute the update (required to write).',
        )

    def handle(self, *args, **options):
        from core.models import Loan, Transaction, JournalEntry

        loan_uuid    = options['loan_uuid']
        new_date_str = options['new_date']
        dry_run      = options['dry_run']
        confirm      = options['confirm']

        if not dry_run and not confirm:
            raise CommandError(
                "Pass --dry-run to preview, or --confirm to execute."
            )

        # ── Parse and validate the new date ──────────────────────────────────
        try:
            new_date = datetime.date.fromisoformat(new_date_str)
        except ValueError:
            raise CommandError(
                f"Invalid date '{new_date_str}'. Use YYYY-MM-DD format."
            )

        # ── Resolve loan ──────────────────────────────────────────────────────
        try:
            loan = Loan.all_objects.get(id=loan_uuid)
        except Loan.DoesNotExist:
            raise CommandError(f"No loan found with UUID: {loan_uuid}")

        if not loan.fees_paid:
            raise CommandError(
                f"Loan {loan.loan_number} has no fees payment recorded yet."
            )

        self.stdout.write(
            f"\nLoan:     {loan.loan_number}"
            f"\nClient:   {loan.client.get_full_name()} ({loan.client.client_id})"
            f"\nNew date: {new_date}  ({new_date.strftime('%A, %d %B %Y')})"
            "\n" + "=" * 60
        )

        # ── Find the fees transaction ─────────────────────────────────────────
        fees_txn = None
        if loan.fees_transaction_id:
            try:
                fees_txn = Transaction.all_objects.get(id=loan.fees_transaction_id)
            except Transaction.DoesNotExist:
                pass

        if fees_txn is None:
            fees_txn = Transaction.all_objects.filter(
                loan=loan,
                transaction_type='charges_at_disbursement',
            ).first()

        if fees_txn is None:
            raise CommandError(
                f"No charges_at_disbursement transaction found for loan "
                f"{loan.loan_number}."
            )

        # ── Find the fee-collection journal entry ─────────────────────────────
        fee_journal = JournalEntry.all_objects.filter(
            entry_type='fee_collection',
            transaction=fees_txn,
        ).first()

        if fee_journal is None:
            fee_journal = JournalEntry.all_objects.filter(
                entry_type='fee_collection',
                loan=loan,
            ).first()

        if fee_journal is None:
            raise CommandError(
                f"No fee_collection journal entry found for loan "
                f"{loan.loan_number}."
            )

        # ── Compute replacement datetimes (preserve original time-of-day) ─────
        new_fees_paid_dt   = _replace_date(loan.fees_paid_date,         new_date)
        new_txn_dt         = _replace_date(fees_txn.transaction_date,   new_date)
        new_posted_at_dt   = _replace_date(fee_journal.posted_at,       new_date)
        new_created_at_dt  = _replace_date(fee_journal.created_at,      new_date)

        # ── Compute new reference_number (replace embedded date digits) ───────
        # e.g. TXN20260328073817479776 → TXN20260312073817479776
        old_ref = fee_journal.reference_number or ''
        # Derive the old date from the current fees_paid_date so we replace
        # the right digits even if the ref was originally set differently.
        if loan.fees_paid_date:
            old_date_digits = timezone.localtime(loan.fees_paid_date).strftime('%Y%m%d')
        else:
            old_date_digits = ''
        new_date_digits = new_date.strftime('%Y%m%d')
        new_ref = (
            old_ref.replace(old_date_digits, new_date_digits, 1)
            if old_date_digits and old_date_digits in old_ref
            else old_ref
        )

        # ── Print preview ─────────────────────────────────────────────────────
        self.stdout.write("\nCurrent  →  New")
        self.stdout.write("-" * 60)

        self._show("Loan.fees_paid_date",
                   loan.fees_paid_date, new_fees_paid_dt)

        self._show(f"Transaction [{fees_txn.transaction_ref}]  .transaction_date",
                   fees_txn.transaction_date, new_txn_dt)

        self._show(f"JournalEntry [{fee_journal.journal_number}]  .transaction_date",
                   fee_journal.transaction_date, new_date)

        self._show(f"JournalEntry [{fee_journal.journal_number}]  .posting_date",
                   fee_journal.posting_date, new_date)

        self._show(f"JournalEntry [{fee_journal.journal_number}]  .posted_at  (audit trail)",
                   fee_journal.posted_at, new_posted_at_dt)

        self._show(f"JournalEntry [{fee_journal.journal_number}]  .created_at (audit trail)",
                   fee_journal.created_at, new_created_at_dt)

        self._show(f"JournalEntry [{fee_journal.journal_number}]  .reference_number",
                   old_ref, new_ref)

        line_count = fee_journal.lines.count()
        self.stdout.write(
            f"  JournalEntryLine × {line_count}  — no date fields, unchanged"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN complete — no changes were made.\n")
            )
            return

        # ── Execute inside one atomic block ───────────────────────────────────
        self.stdout.write(self.style.WARNING("\nExecuting update..."))

        with db_transaction.atomic():

            # 1. Loan.fees_paid_date
            loan.fees_paid_date = new_fees_paid_dt
            loan.save(update_fields=['fees_paid_date', 'updated_at'])
            self._done("Loan.fees_paid_date", new_fees_paid_dt)

            # 2. Transaction.transaction_date
            fees_txn.transaction_date = new_txn_dt
            fees_txn.save(update_fields=['transaction_date'])
            self._done("Transaction.transaction_date", new_txn_dt)

            # 3. JournalEntry — transaction_date, posting_date, posted_at
            #    These can go through .save() / update_fields normally.
            fee_journal.transaction_date = new_date
            fee_journal.posting_date     = new_date
            fee_journal.posted_at        = new_posted_at_dt
            fee_journal.save(update_fields=[
                'transaction_date', 'posting_date', 'posted_at'
            ])
            self._done("JournalEntry.transaction_date", new_date)
            self._done("JournalEntry.posting_date",     new_date)
            self._done("JournalEntry.posted_at",        new_posted_at_dt)

            # 4. JournalEntry.created_at — auto_now_add=True so Django ignores
            #    it in .save().  Use a raw queryset .update() to bypass this.
            #    Also update reference_number in the same call.
            JournalEntry.all_objects.filter(pk=fee_journal.pk).update(
                created_at=new_created_at_dt,
                reference_number=new_ref,
            )
            self._done("JournalEntry.created_at (via queryset.update)", new_created_at_dt)
            self._done("JournalEntry.reference_number", new_ref)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. All fees dates for loan {loan.loan_number} "
                f"updated to {new_date}.\n"
            )
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt(self, value):
        if isinstance(value, datetime.datetime):
            return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
        return str(value)

    def _show(self, label, current, new):
        self.stdout.write(
            f"  {label}:\n"
            f"      {self.style.WARNING(self._fmt(current))}  →  "
            f"{self.style.SUCCESS(self._fmt(new))}"
        )

    def _done(self, label, value):
        self.stdout.write(
            f"  [UPDATED] {label} → {self.style.SUCCESS(self._fmt(value))}"
        )
