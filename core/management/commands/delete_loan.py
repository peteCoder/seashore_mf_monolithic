"""
Management command: delete_loan
================================

Hard-deletes a single loan by UUID and EVERY record associated with it:
transactions, journal entries, journal entry lines, repayment postings,
repayment schedules, penalties, guarantors, collateral, loan notes,
follow-up tasks, payment promises, restructure requests, group collection
items, loan insurance claims, and the loan record itself.

This operation is IRREVERSIBLE. A --dry-run flag is provided for previewing.
You must pass --confirm to actually execute the deletion.

Usage:
    # Preview what will be deleted (safe — no writes)
    python manage.py delete_loan <loan-uuid> --dry-run

    # Execute the deletion (irreversible)
    python manage.py delete_loan <loan-uuid> --confirm
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


class Command(BaseCommand):
    help = "Hard-delete a loan and all associated records by UUID."

    def add_arguments(self, parser):
        parser.add_argument(
            'loan_uuid',
            type=str,
            help='UUID of the loan to delete.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be deleted without making any changes.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Required flag to actually execute the deletion (safety guard).',
        )

    def handle(self, *args, **options):
        from core.models import (
            Loan,
            Transaction,
            JournalEntry,
            JournalEntryLine,
            LoanRepaymentPosting,
            LoanRepaymentSchedule,
            LoanPenalty,
            Guarantor,
            Collateral,
            Notification,
        )
        from core.models.all_models import (
            LoanNote,
            GroupCollectionItem,
            GroupCombinedLoanItem,
            LoanInsuranceClaim,
            FollowUpTask,
            PaymentPromise,
            LoanRestructureRequest,
        )

        dry_run = options['dry_run']
        confirm = options['confirm']
        loan_uuid = options['loan_uuid']

        if not dry_run and not confirm:
            raise CommandError(
                "This operation is irreversible. "
                "Pass --dry-run to preview, or --confirm to execute."
            )

        # ── Resolve loan — use all_objects to include soft-deleted records ──────
        try:
            loan = Loan.all_objects.get(id=loan_uuid)
        except Loan.DoesNotExist:
            raise CommandError(f"No loan found with UUID: {loan_uuid}")

        self.stdout.write(
            f"\nLoan: {loan.loan_number} "
            f"— Client: {loan.client.get_full_name()} ({loan.client.client_id})"
            f"\nStatus: {loan.get_status_display()} "
            f"— Branch: {loan.branch}"
            f"\nPrincipal: ₦{loan.principal_amount:,.2f}"
            "\n" + "=" * 60
        )

        # ── Gather all related querysets ─────────────────────────────────────────

        # Transactions linked directly to this loan
        transactions = Transaction.all_objects.filter(loan=loan)
        txn_ids = list(transactions.values_list('id', flat=True))

        # Journal entries linked to this loan (directly or via its transactions)
        # JournalEntry.loan is SET_NULL — won't cascade, must delete explicitly.
        from django.db.models import Q
        journal_entries = JournalEntry.all_objects.filter(
            Q(loan=loan) | Q(transaction__id__in=txn_ids)
        )
        je_ids = list(journal_entries.values_list('id', flat=True))

        # Journal entry lines belonging to those journal entries
        journal_lines = JournalEntryLine.all_objects.filter(journal_entry__id__in=je_ids)

        # PROTECT-guarded records that must be deleted before the Loan
        loan_repayment_postings = LoanRepaymentPosting.all_objects.filter(loan=loan)
        group_collection_items = GroupCollectionItem.all_objects.filter(loan=loan)
        group_combined_loan_items = GroupCombinedLoanItem.all_objects.filter(loan=loan)
        loan_insurance_claims = LoanInsuranceClaim.all_objects.filter(loan=loan)

        # CASCADE-deleted automatically when Loan is deleted (counted for report)
        schedule_count = LoanRepaymentSchedule.all_objects.filter(loan=loan).count()
        penalty_count = LoanPenalty.all_objects.filter(loan=loan).count()
        note_count = LoanNote.all_objects.filter(loan=loan).count()
        guarantor_count = Guarantor.all_objects.filter(loan=loan).count()
        collateral_count = Collateral.all_objects.filter(loan=loan).count()
        followup_count = FollowUpTask.all_objects.filter(loan=loan).count()
        promise_count = PaymentPromise.all_objects.filter(loan=loan).count()
        restructure_count = LoanRestructureRequest.all_objects.filter(loan=loan).count()
        notification_count = Notification.all_objects.filter(related_loan=loan).count()

        # ── Print deletion report ─────────────────────────────────────────────────
        self._report("Transactions", transactions.count())
        self._report("Journal Entries", journal_entries.count())
        self._report("  Journal Entry Lines", journal_lines.count())
        self._report("Loan Repayment Postings (PROTECT → explicit)", loan_repayment_postings.count())
        self._report("Group Collection Items (PROTECT → explicit)", group_collection_items.count())
        self._report("Group Combined Loan Items (PROTECT → explicit)", group_combined_loan_items.count())
        self._report("Loan Insurance Claims (PROTECT → explicit)", loan_insurance_claims.count())
        self._report("Repayment Schedules (CASCADE)", schedule_count)
        self._report("Penalties (CASCADE)", penalty_count)
        self._report("Loan Notes (CASCADE)", note_count)
        self._report("Guarantors (CASCADE)", guarantor_count)
        self._report("Collateral (CASCADE)", collateral_count)
        self._report("Follow-up Tasks (CASCADE)", followup_count)
        self._report("Payment Promises (CASCADE)", promise_count)
        self._report("Restructure Requests (CASCADE)", restructure_count)
        self._report("Notifications (CASCADE)", notification_count)
        self.stdout.write("-" * 60)
        self._report("LOAN RECORD", 1)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN complete — no changes were made.\n")
            )
            return

        # ── Execute deletion inside a single atomic transaction ──────────────────
        self.stdout.write(self.style.WARNING("\nExecuting deletion..."))

        with db_transaction.atomic():

            # 1. Delete journal entry lines first (FK to JournalEntry)
            jl_deleted, _ = journal_lines.delete()
            self._done("Journal Entry Lines", jl_deleted)

            # 2. Delete journal entries
            #    (JournalEntry.loan is SET_NULL — won't cascade automatically)
            je_deleted, _ = journal_entries.delete()
            self._done("Journal Entries", je_deleted)

            # 3. Delete PROTECT-guarded records before Loan and Transaction
            lrp_deleted, _ = loan_repayment_postings.delete()
            self._done("Loan Repayment Postings", lrp_deleted)

            gc_deleted, _ = group_collection_items.delete()
            self._done("Group Collection Items", gc_deleted)

            gcl_deleted, _ = group_combined_loan_items.delete()
            self._done("Group Combined Loan Items", gcl_deleted)

            ic_deleted, _ = loan_insurance_claims.delete()
            self._done("Loan Insurance Claims", ic_deleted)

            # 4. Delete transactions (PROTECT on Transaction.loan)
            txn_deleted, _ = transactions.delete()
            self._done("Transactions", txn_deleted)

            # 5. Hard-delete the loan itself
            #    Cascades: LoanNote, Guarantor, Collateral, LoanRepaymentSchedule,
            #    LoanPenalty, FollowUpTask, PaymentPromise, LoanRestructureRequest,
            #    Notification.related_loan
            loan_number = loan.loan_number
            loan.delete(hard=True)
            self._done(
                f"Loan {loan_number} + cascaded records "
                f"(schedules, penalties, notes, guarantors, collateral, "
                f"follow-ups, promises, restructures, notifications)",
                1,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nLoan {loan_number} and all associated records have been "
                f"permanently deleted.\n"
            )
        )

    # ── Helpers ──────────────────────────────────────────────────────────────────

    def _report(self, label, count):
        colour = self.style.WARNING if count > 0 else self.style.HTTP_INFO
        self.stdout.write(f"  {label}: {colour(str(count))}")

    def _done(self, label, count):
        self.stdout.write(f"  [DELETED] {label}: {self.style.SUCCESS(str(count))}")
