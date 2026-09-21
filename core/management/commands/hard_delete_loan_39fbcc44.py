"""
Management command: hard_delete_loan_39fbcc44
================================================

Permanently (hard) deletes loan LN20260910163225792685
(id 39fbcc44-b23f-4453-91b8-a41baf842b83) and every record associated
with it, per an explicit user request to leave no trace of the loan.

LOAN
----
  id     : 39fbcc44-b23f-4453-91b8-a41baf842b83
  number : LN20260910163225792685
  client : Fidelia Monday Emueme
  branch : Murtala Mohammed Way (MMWAYBEN)
  status : active (disbursed, no repayments made yet)

WHAT THIS COMMAND DELETES
--------------------------
1. JournalEntryLine rows belonging to the loan's 2 journal entries
2. JournalEntry rows      : JE-20260910-312768 (fee_collection),
                            JE-20260909-013245 (loan_disbursement)
3. Transaction rows       : TXN20260910164554589076 (charges at disbursement),
                            TXN20260911085632296641 (loan disbursement)
   (Transaction.loan is on_delete=PROTECT, so these must be removed before
   the loan itself can be deleted)
4. The Loan row itself, which cascades (on_delete=CASCADE) to:
     - LoanRepaymentSchedule (24 installments)
     - Guarantor (2)
     - Notification (related_loan, 2)
     - LoanNote, Collateral, LoanPenalty, FollowUpTask, PaymentPromise,
       LoanRestructureRequest, VoiceCallLog (0 rows each, verified below)

Models are soft-delete (BaseModel.delete() just sets deleted_at). This
command uses `.hard_delete()` / the underlying queryset `.delete()` so rows
are actually removed from the database, not just flagged as deleted.

Before deleting, the command re-verifies there are zero rows in the other
PROTECT-related tables (LoanRepaymentPosting, GroupCollectionItem,
GroupCombinedLoanItem, LoanInsuranceClaim) for this loan, and aborts if any
are found (would mean the loan has real repayment/group history that
shouldn't be silently discarded).

Usage
-----
  python manage.py hard_delete_loan_39fbcc44 --dry-run
  python manage.py hard_delete_loan_39fbcc44 --commit
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID = '39fbcc44-b23f-4453-91b8-a41baf842b83'


class Command(BaseCommand):
    help = 'Hard-delete loan 39fbcc44-b23f-4453-91b8-a41baf842b83 and everything associated with it'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                            help='Show what will be deleted without writing to the DB')
        group.add_argument('--commit', action='store_true',
                            help='Apply the deletion')

    def handle(self, *args, **options):
        from core.models import (
            Loan, Transaction, JournalEntry, LoanRepaymentPosting,
            GroupCollectionItem, GroupCombinedLoanItem, LoanInsuranceClaim,
        )

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(
            f'\n=== hard_delete_loan_39fbcc44 [{mode}] ===\n'
        ))

        # ── 1. Fetch loan (use all_objects in case it was soft-deleted already) ──
        try:
            loan = Loan.all_objects.get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found. It may have already been hard-deleted.')

        self.stdout.write('LOAN')
        self.stdout.write(f'  id             : {loan.id}')
        self.stdout.write(f'  number         : {loan.loan_number}')
        self.stdout.write(f'  client         : {loan.client}')
        self.stdout.write(f'  branch         : {loan.branch}')
        self.stdout.write(f'  status         : {loan.status}')
        self.stdout.write(f'  principal      : {loan.principal_amount}')
        self.stdout.write(f'  amount_paid    : {getattr(loan, "amount_paid", None)}')

        # ── 2. Gather related records (all_objects to include any soft-deleted) ──
        txns = list(Transaction.all_objects.filter(loan_id=LOAN_ID))
        txn_ids = [t.id for t in txns]
        jes = list(JournalEntry.all_objects.filter(loan_id=LOAN_ID)) + \
              list(JournalEntry.all_objects.filter(transaction_id__in=txn_ids).exclude(loan_id=LOAN_ID))

        schedule_count = loan.repayment_schedule(manager='all_objects').count()
        guarantor_count = loan.guarantors(manager='all_objects').count()
        notification_count = loan.notifications(manager='all_objects').count()

        self.stdout.write('\nTRANSACTIONS TO DELETE')
        for t in txns:
            self.stdout.write(f'  {t.transaction_ref}  {t.transaction_type}  amount={t.amount}  status={t.status}')

        self.stdout.write('\nJOURNAL ENTRIES TO DELETE')
        total_lines = 0
        for je in jes:
            line_count = je.lines(manager='all_objects').count()
            total_lines += line_count
            self.stdout.write(f'  {je.journal_number}  type={je.entry_type}  status={je.status}  lines={line_count}')
            for line in je.lines(manager='all_objects').select_related('account').all():
                self.stdout.write(
                    f'    GL {line.account.gl_code} ({line.account.account_name}): '
                    f'Dr={line.debit_amount}  Cr={line.credit_amount}'
                )

        self.stdout.write('\nCASCADE-DELETED WITH LOAN')
        self.stdout.write(f'  Repayment schedule rows : {schedule_count}')
        self.stdout.write(f'  Guarantors              : {guarantor_count}')
        self.stdout.write(f'  Notifications           : {notification_count}')

        # ── 3. Safety checks: abort if this loan has real repayment/group history ──
        blockers = {
            'LoanRepaymentPosting': LoanRepaymentPosting.all_objects.filter(loan_id=LOAN_ID).count(),
            'GroupCollectionItem': GroupCollectionItem.all_objects.filter(loan_id=LOAN_ID).count(),
            'GroupCombinedLoanItem': GroupCombinedLoanItem.all_objects.filter(loan_id=LOAN_ID).count(),
            'LoanInsuranceClaim': LoanInsuranceClaim.all_objects.filter(loan_id=LOAN_ID).count(),
        }
        blocking = {k: v for k, v in blockers.items() if v}
        if blocking:
            raise CommandError(
                f'Loan has unexpected related records that suggest real repayment/insurance/'
                f'group history: {blocking}. Aborting to avoid discarding real financial history. '
                f'Investigate manually before proceeding.'
            )
        self.stdout.write('\n  -> No repayment postings, group collection items, or insurance claims found. Safe to proceed.')

        self.stdout.write('\nWILL DELETE (permanently, no trace)')
        self.stdout.write(f'  JournalEntryLine records : {total_lines}')
        self.stdout.write(f'  JournalEntry records     : {len(jes)}')
        self.stdout.write(f'  Transaction records      : {len(txns)}')
        self.stdout.write(f'  Repayment schedule rows  : {schedule_count}')
        self.stdout.write(f'  Guarantors               : {guarantor_count}')
        self.stdout.write(f'  Notifications            : {notification_count}')
        self.stdout.write(f'  Loan record              : 1 ({loan.loan_number})')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete - no changes written. Re-run with --commit to apply.\n'
            ))
            return

        # ── 4. Apply ─────────────────────────────────────────────────────
        with db_transaction.atomic():
            for je in jes:
                lines_deleted, _ = je.lines(manager='all_objects').all().delete()
                self.stdout.write(f'  Deleted {lines_deleted} line(s) from JE {je.journal_number}')
                je.hard_delete()
                self.stdout.write(f'  Deleted JE {je.journal_number}')

            for t in txns:
                ref = t.transaction_ref
                t.hard_delete()
                self.stdout.write(f'  Deleted transaction {ref}')

            loan_number = loan.loan_number
            loan.hard_delete()
            self.stdout.write(f'  Deleted loan {loan_number} (cascaded schedule/guarantors/notifications)')

        self.stdout.write(self.style.SUCCESS('\nLoan and all associated records permanently deleted.\n'))

        # ── 5. Final verification ─────────────────────────────────────────
        self.stdout.write('FINAL STATE')
        self.stdout.write(f'  Loan exists              : {Loan.all_objects.filter(id=LOAN_ID).exists()}')
        self.stdout.write(f'  Transactions remaining   : {Transaction.all_objects.filter(loan_id=LOAN_ID).count()}')
        self.stdout.write(f'  Journal entries remaining: {JournalEntry.all_objects.filter(loan_id=LOAN_ID).count()}')
