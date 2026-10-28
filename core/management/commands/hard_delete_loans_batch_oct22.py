"""
Management command: hard_delete_loans_batch_oct22
=====================================================

Permanently (hard) deletes 4 loans and every record associated with them,
per explicit user request: these loans will be re-entered properly, and
nothing of the incorrect entries should remain.

LOANS
-----
  450204d0-7721-4cf9-abcc-8046ced72138  LN20261021100613891751  Ojo Abeweri
      pending_fees, no transactions/journals/schedule yet
  c75d543c-e0be-43a8-b923-d2110d9b7084  LN20261019160051167882  Endurance Friday
      active, principal 1,000,000, 2 txns, 2 JEs (7 lines), 24 schedule rows, 2 guarantors
  5c4e4a50-e91a-47c5-b33c-17b40a1741f5  LN20261021152415629776  Jennifer Idopise
      pending_approval, 1 txn (fees only), 1 JE (5 lines), 2 guarantors, no schedule yet
  b37021fb-ade4-420b-9554-41b437da1850  LN20261021150948982453  Osamaru Amas Festus
      active, principal 200,000, 2 txns, 2 JEs (7 lines), 24 schedule rows, 2 guarantors

All 4 have amount_paid = 0.00 and zero repayment postings / insurance claims /
group collection items — verified before writing this, so none of them carry
real repayment history.

WHAT THIS COMMAND DELETES (per loan)
-------------------------------------
1. JournalEntryLine rows on every journal entry linked to the loan
2. Those JournalEntry rows
3. Transaction rows linked to the loan (Transaction.loan is PROTECT, so
   these must go before the loan itself can be deleted)
4. The Loan row itself, which cascades (CASCADE) to:
     LoanRepaymentSchedule, Guarantor, Notification (related_loan),
     LoanNote, Collateral, LoanPenalty, FollowUpTask, PaymentPromise,
     LoanRestructureRequest, VoiceCallLog

Before deleting, re-verifies zero rows in LoanRepaymentPosting,
GroupCollectionItem, GroupCombinedLoanItem, LoanInsuranceClaim for every
loan in the batch, and aborts the whole batch if any are found.

Usage
-----
  python manage.py hard_delete_loans_batch_oct22 --dry-run
  python manage.py hard_delete_loans_batch_oct22 --commit
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_IDS = [
    '450204d0-7721-4cf9-abcc-8046ced72138',
    'c75d543c-e0be-43a8-b923-d2110d9b7084',
    '5c4e4a50-e91a-47c5-b33c-17b40a1741f5',
    'b37021fb-ade4-420b-9554-41b437da1850',
]


class Command(BaseCommand):
    help = 'Hard-delete the 4 batch loans (Oct 22 request) and everything associated with them'

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
            f'\n=== hard_delete_loans_batch_oct22 [{mode}] — {len(LOAN_IDS)} loans ===\n'
        ))

        loans = []
        for loan_id in LOAN_IDS:
            try:
                loans.append(Loan.all_objects.get(id=loan_id))
            except Loan.DoesNotExist:
                raise CommandError(f'Loan {loan_id} not found. It may have already been hard-deleted.')

        totals = {'txns': 0, 'jes': 0, 'lines': 0, 'schedule': 0, 'guarantors': 0, 'notifications': 0}

        per_loan_data = []
        for loan in loans:
            self.stdout.write(f'LOAN {loan.loan_number}  client={loan.client}  status={loan.status}')
            self.stdout.write(f'  principal={loan.principal_amount}  amount_paid={loan.amount_paid}')

            blockers = {
                'LoanRepaymentPosting': LoanRepaymentPosting.all_objects.filter(loan_id=loan.id).count(),
                'GroupCollectionItem': GroupCollectionItem.all_objects.filter(loan_id=loan.id).count(),
                'GroupCombinedLoanItem': GroupCombinedLoanItem.all_objects.filter(loan_id=loan.id).count(),
                'LoanInsuranceClaim': LoanInsuranceClaim.all_objects.filter(loan_id=loan.id).count(),
            }
            blocking = {k: v for k, v in blockers.items() if v}
            if blocking:
                raise CommandError(
                    f'Loan {loan.loan_number} has unexpected related records suggesting real '
                    f'repayment/insurance/group history: {blocking}. Aborting the whole batch — '
                    f'investigate this loan manually before proceeding.'
                )

            txns = list(Transaction.all_objects.filter(loan_id=loan.id))
            txn_ids = [t.id for t in txns]
            jes = list(JournalEntry.all_objects.filter(loan_id=loan.id)) + \
                  list(JournalEntry.all_objects.filter(transaction_id__in=txn_ids).exclude(loan_id=loan.id))

            schedule_count = loan.repayment_schedule(manager='all_objects').count()
            guarantor_count = loan.guarantors(manager='all_objects').count()
            notification_count = loan.notifications(manager='all_objects').count()
            line_count = sum(je.lines(manager='all_objects').count() for je in jes)

            self.stdout.write(f'  -> {len(txns)} txn(s), {len(jes)} JE(s) ({line_count} lines), '
                               f'{schedule_count} schedule row(s), {guarantor_count} guarantor(s), '
                               f'{notification_count} notification(s)')

            totals['txns'] += len(txns)
            totals['jes'] += len(jes)
            totals['lines'] += line_count
            totals['schedule'] += schedule_count
            totals['guarantors'] += guarantor_count
            totals['notifications'] += notification_count

            per_loan_data.append((loan, txns, jes))

        self.stdout.write('\nWILL DELETE ACROSS ALL 4 LOANS (permanently, no trace)')
        self.stdout.write(f"  JournalEntryLine records : {totals['lines']}")
        self.stdout.write(f"  JournalEntry records     : {totals['jes']}")
        self.stdout.write(f"  Transaction records      : {totals['txns']}")
        self.stdout.write(f"  Repayment schedule rows  : {totals['schedule']}")
        self.stdout.write(f"  Guarantors               : {totals['guarantors']}")
        self.stdout.write(f"  Notifications            : {totals['notifications']}")
        self.stdout.write(f"  Loan records             : {len(loans)}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete - no changes written. Re-run with --commit to apply.\n'
            ))
            return

        with db_transaction.atomic():
            for loan, txns, jes in per_loan_data:
                for je in jes:
                    lines_deleted, _ = je.lines(manager='all_objects').all().delete()
                    je.hard_delete()
                self.stdout.write(f'  Deleted {len(jes)} JE(s) for {loan.loan_number}')

                for t in txns:
                    t.hard_delete()
                self.stdout.write(f'  Deleted {len(txns)} transaction(s) for {loan.loan_number}')

                loan_number = loan.loan_number
                loan.hard_delete()
                self.stdout.write(f'  Deleted loan {loan_number} (cascaded schedule/guarantors/notifications)')

        self.stdout.write(self.style.SUCCESS('\nAll 4 loans and associated records permanently deleted.\n'))

        self.stdout.write('FINAL STATE')
        for loan_id in LOAN_IDS:
            self.stdout.write(
                f'  {loan_id}: loan exists={Loan.all_objects.filter(id=loan_id).exists()}  '
                f'txns remaining={Transaction.all_objects.filter(loan_id=loan_id).count()}  '
                f'JEs remaining={JournalEntry.all_objects.filter(loan_id=loan_id).count()}'
            )
