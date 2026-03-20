"""
Management command: delete_client
==================================

Hard-deletes a client and EVERY record associated with that client,
including transactions, journal entries, loans, savings accounts, guarantors,
collateral, repayment schedules, penalties, notes, postings, notifications,
next of kin, group memberships, and the client record itself.

This operation is IRREVERSIBLE. A --dry-run flag is provided for previewing.
You must pass --confirm to actually execute the deletion.

Usage:
    # Preview what will be deleted (safe — no writes)
    python manage.py delete_client <client-uuid> --dry-run

    # Execute the deletion (irreversible)
    python manage.py delete_client <client-uuid> --confirm
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.db.models import Q


class Command(BaseCommand):
    help = "Hard-delete a client and all associated records by UUID."

    def add_arguments(self, parser):
        parser.add_argument(
            'client_uuid',
            type=str,
            help='UUID of the client to delete.',
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
            Client,
            Loan,
            SavingsAccount,
            Transaction,
            JournalEntry,
            JournalEntryLine,
            LoanRepaymentPosting,
            SavingsDepositPosting,
            SavingsWithdrawalPosting,
            GroupSavingsCollectionItem,
            GroupCombinedLoanItem,
            GroupCombinedSavingsItem,
            GroupCollectionItem,
            LoanInsuranceClaim,
            Notification,
        )

        dry_run = options['dry_run']
        confirm = options['confirm']
        client_uuid = options['client_uuid']

        if not dry_run and not confirm:
            raise CommandError(
                "This operation is irreversible. "
                "Pass --dry-run to preview, or --confirm to execute."
            )

        # ── Resolve client — use all_objects to include soft-deleted records ────
        try:
            client = Client.all_objects.get(id=client_uuid)
        except Client.DoesNotExist:
            raise CommandError(f"No client found with UUID: {client_uuid}")

        self.stdout.write(
            f"\nClient: {client.get_full_name()} "
            f"({client.client_id}) — Branch: {client.branch}\n"
            + "=" * 60
        )

        # ── Gather querysets — all_objects includes soft-deleted rows ─────────
        loans = Loan.all_objects.filter(client=client)
        loan_ids = list(loans.values_list('id', flat=True))

        savings_accounts = SavingsAccount.all_objects.filter(client=client)

        transactions = Transaction.all_objects.filter(client=client)

        # Journal entries linked via transaction, loan, or savings_account
        # JournalEntry is BaseModel too — use all_objects
        journal_entries = JournalEntry.all_objects.filter(
            Q(transaction__client=client)
            | Q(loan__client=client)
            | Q(savings_account__client=client)
        )
        je_ids = list(journal_entries.values_list('id', flat=True))

        journal_lines = JournalEntryLine.all_objects.filter(journal_entry__id__in=je_ids)

        loan_repayment_postings = LoanRepaymentPosting.all_objects.filter(client=client)
        savings_deposit_postings = SavingsDepositPosting.all_objects.filter(client=client)
        savings_withdrawal_postings = SavingsWithdrawalPosting.all_objects.filter(client=client)

        group_savings_items = GroupSavingsCollectionItem.all_objects.filter(client=client)
        combined_loan_items = GroupCombinedLoanItem.all_objects.filter(client=client)
        combined_savings_items = GroupCombinedSavingsItem.all_objects.filter(client=client)

        # PROTECT-guarded loan sub-records (must be deleted before Loan)
        group_collection_items = GroupCollectionItem.all_objects.filter(loan__id__in=loan_ids)
        loan_insurance_claims = LoanInsuranceClaim.all_objects.filter(loan__id__in=loan_ids)

        # Cascade-deleted automatically when Loan is deleted (counted for report only)
        from core.models import (
            LoanRepaymentSchedule,
            LoanPenalty,
            Guarantor,
            Collateral,
            FollowUpTask,
            PaymentPromise,
            LoanRestructureRequest,
        )
        from core.models.all_models import LoanNote
        schedule_count = LoanRepaymentSchedule.all_objects.filter(loan__id__in=loan_ids).count()
        penalty_count = LoanPenalty.all_objects.filter(loan__id__in=loan_ids).count()
        note_count = LoanNote.all_objects.filter(loan__id__in=loan_ids).count()
        guarantor_count = Guarantor.all_objects.filter(loan__id__in=loan_ids).count()
        collateral_count = Collateral.all_objects.filter(loan__id__in=loan_ids).count()
        followup_count = FollowUpTask.all_objects.filter(loan__id__in=loan_ids).count()
        promise_count = PaymentPromise.all_objects.filter(loan__id__in=loan_ids).count()
        restructure_count = LoanRestructureRequest.all_objects.filter(loan__id__in=loan_ids).count()

        # Cascade-deleted when Client is deleted
        from core.models import GroupMembershipRequest
        membership_count = GroupMembershipRequest.all_objects.filter(client=client).count()
        notification_count = Notification.all_objects.filter(related_client=client).count()
        has_nok = hasattr(client, 'next_of_kin')

        # ── Print deletion report ──────────────────────────────────────────────
        self._report("Loans", loans.count())
        self._report("  Repayment Schedules (via Loan CASCADE)", schedule_count)
        self._report("  Penalties (via Loan CASCADE)", penalty_count)
        self._report("  Loan Notes (via Loan CASCADE)", note_count)
        self._report("  Guarantors (via Loan CASCADE)", guarantor_count)
        self._report("  Collateral (via Loan CASCADE)", collateral_count)
        self._report("  Follow-up Tasks (via Loan CASCADE)", followup_count)
        self._report("  Payment Promises (via Loan CASCADE)", promise_count)
        self._report("  Restructure Requests (via Loan CASCADE)", restructure_count)
        self._report("  Group Collection Items (PROTECT → explicit)", group_collection_items.count())
        self._report("  Loan Insurance Claims (PROTECT → explicit)", loan_insurance_claims.count())
        self._report("Savings Accounts", savings_accounts.count())
        self._report("Transactions", transactions.count())
        self._report("  Loan Repayment Postings", loan_repayment_postings.count())
        self._report("  Savings Deposit Postings", savings_deposit_postings.count())
        self._report("  Savings Withdrawal Postings", savings_withdrawal_postings.count())
        self._report("Journal Entries", journal_entries.count())
        self._report("  Journal Entry Lines", journal_lines.count())
        self._report("Group Savings Collection Items", group_savings_items.count())
        self._report("Group Combined Loan Items", combined_loan_items.count())
        self._report("Group Combined Savings Items", combined_savings_items.count())
        self._report("Group Membership Requests (CASCADE)", membership_count)
        self._report("Notifications (CASCADE)", notification_count)
        self._report("Next of Kin (CASCADE)", 1 if has_nok else 0)
        self.stdout.write("-" * 60)
        self._report("CLIENT RECORD", 1)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN complete — no changes were made.\n")
            )
            return

        # ── Execute deletion inside a single atomic transaction ────────────────
        self.stdout.write(self.style.WARNING("\nExecuting deletion..."))

        with db_transaction.atomic():

            # 1. Delete journal entry lines first (FK to JournalEntry)
            jl_deleted, _ = journal_lines.delete()
            self._done("Journal Entry Lines", jl_deleted)

            # 2. Delete journal entries (SET_NULL on transaction/loan/savings_account
            #    means they WON'T cascade — must delete explicitly)
            je_deleted, _ = journal_entries.delete()
            self._done("Journal Entries", je_deleted)

            # 3. Delete PROTECT-guarded loan sub-records before Loan
            gc_deleted, _ = group_collection_items.delete()
            self._done("Group Collection Items", gc_deleted)

            ic_deleted, _ = loan_insurance_claims.delete()
            self._done("Loan Insurance Claims", ic_deleted)

            # 4. Delete PROTECT-guarded client-direct records before Transaction/Loan
            lrp_deleted, _ = loan_repayment_postings.delete()
            self._done("Loan Repayment Postings", lrp_deleted)

            sdp_deleted, _ = savings_deposit_postings.delete()
            self._done("Savings Deposit Postings", sdp_deleted)

            swp_deleted, _ = savings_withdrawal_postings.delete()
            self._done("Savings Withdrawal Postings", swp_deleted)

            gsi_deleted, _ = group_savings_items.delete()
            self._done("Group Savings Collection Items", gsi_deleted)

            cli_deleted, _ = combined_loan_items.delete()
            self._done("Group Combined Loan Items", cli_deleted)

            csi_deleted, _ = combined_savings_items.delete()
            self._done("Group Combined Savings Items", csi_deleted)

            # 5. Delete Transactions (after postings and journal entries are gone)
            txn_deleted, _ = transactions.delete()
            self._done("Transactions", txn_deleted)

            # 6. Delete Loans (cascades: schedules, penalties, notes, guarantors,
            #    collateral, follow-ups, payment promises, restructure requests)
            loan_deleted, loan_breakdown = loans.delete()
            self._done("Loans + cascaded records", loan_deleted)

            # 7. Delete Savings Accounts
            sa_deleted, _ = savings_accounts.delete()
            self._done("Savings Accounts", sa_deleted)

            # 8. Delete the Client itself (cascades: GroupMembershipRequest,
            #    NextOfKin, Notification.related_client)
            # Must use hard=True — BaseModel.delete() soft-deletes by default.
            client_name = client.get_full_name()
            client_id_display = client.client_id
            client.delete(hard=True)
            self._done(f"Client — {client_name} ({client_id_display})", 1)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nClient {client_name} ({client_id_display}) and all associated "
                f"records have been permanently deleted.\n"
            )
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _report(self, label, count):
        colour = self.style.WARNING if count > 0 else self.style.HTTP_INFO
        self.stdout.write(f"  {label}: {colour(str(count))}")

    def _done(self, label, count):
        self.stdout.write(f"  [DELETED] {label}: {self.style.SUCCESS(str(count))}")
