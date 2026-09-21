"""
Management command: delete_rita_duplicate_charges
====================================================

Removes a duplicate "charges at disbursement" transaction and its journal
entry for Amenaghawon Rita's loan, created by a race condition (two
concurrent requests both recorded the upfront fee collection, ~177ms apart,
each with identical amount/description/processed_by and balance_before=0).
This is the same failure pattern as the earlier Mercy ghost-transaction bug
(see delete_mercy_ghost_transaction.py).

CLIENT : Amenaghawon Rita (6c0cc520-d8d9-4965-8004-06e136da7bd2)
LOAN   : d51ff177-4eb6-4f7f-8c29-1997c7f26726 (LN20260916131703120591)
         principal 150,000, status active, amount_paid 0.00

DUPLICATE PAIR (both: charges_at_disbursement, NGN 8,150, completed,
2026-09-15, "Upfront fees for LN20260916131703120591", same processed_by):
  KEEP   TXN20260917101226884626 (a3a5e41f-a892-4d00-9621-f8e034b557fd)
         JE-20260916-756489 -- this is the transaction the Loan record's
         own `fees_transaction` FK points to, so keeping it preserves
         referential integrity.
  DELETE TXN20260917101226796695 (56a282dc-146c-4ab2-9f5c-478bd6d8ceb8)
         JE-20260916-423196 -- the orphan duplicate, not referenced by
         the loan or anything else.

Both journal entries have identical line composition:
  GL 1010 Cash In Hand              Dr 8,150.00
  GL 4150 Risk Premium Income                      Cr 2,250.00 (x2 lines)
  GL 4165 Loan Maintenance Fee Income              Cr   200.00
  GL 4120 Loan Application Fee Income              Cr   200.00
  GL 4160 Technology Fee Income                    Cr   750.00
  GL 4190 Admin Fee Income                         Cr 2,500.00

WHAT THIS COMMAND DOES
-----------------------
1. Re-verifies both transactions still exist, are identical duplicates,
   and that KEEP is the one referenced by loan.fees_transaction_id.
2. Verifies the DELETE transaction is not linked to any approved
   LoanRepaymentPosting (safety check, same as the Mercy command).
3. Deletes DELETE's JournalEntryLine rows, then its JournalEntry, then the
   Transaction itself (all hard deletes -- these are soft-delete models).
4. Does NOT touch the loan, or the KEEP transaction/journal entry.

Usage
-----
  python manage.py delete_rita_duplicate_charges --dry-run
  python manage.py delete_rita_duplicate_charges --commit
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


LOAN_ID = 'd51ff177-4eb6-4f7f-8c29-1997c7f26726'
KEEP_TXN_ID = 'a3a5e41f-a892-4d00-9621-f8e034b557fd'
DELETE_TXN_ID = '56a282dc-146c-4ab2-9f5c-478bd6d8ceb8'


class Command(BaseCommand):
    help = "Delete the duplicate charges-at-disbursement transaction/JE on Amenaghawon Rita's loan"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                            help='Show what will be deleted without writing to the DB')
        group.add_argument('--commit', action='store_true',
                            help='Apply the deletion')

    def handle(self, *args, **options):
        from core.models import Loan, Transaction, JournalEntry, LoanRepaymentPosting

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(
            f'\n=== delete_rita_duplicate_charges [{mode}] ===\n'
        ))

        # ── 1. Fetch loan and both transactions ───────────────────────────
        loan = Loan.all_objects.get(id=LOAN_ID)
        self.stdout.write('LOAN')
        self.stdout.write(f'  number      : {loan.loan_number}')
        self.stdout.write(f'  status      : {loan.status}')
        self.stdout.write(f'  fees_transaction_id : {loan.fees_transaction_id}')

        try:
            keep = Transaction.all_objects.get(id=KEEP_TXN_ID)
            delete = Transaction.all_objects.get(id=DELETE_TXN_ID)
        except Transaction.DoesNotExist as e:
            raise CommandError(f'Expected transaction not found: {e}')

        if str(loan.fees_transaction_id) != KEEP_TXN_ID:
            raise CommandError(
                f'Loan.fees_transaction_id ({loan.fees_transaction_id}) no longer matches '
                f'the expected KEEP transaction ({KEEP_TXN_ID}). Aborting -- state has changed, '
                f'investigate manually.'
            )

        self.stdout.write('\nKEEP (referenced by loan.fees_transaction)')
        self.stdout.write(f'  {keep.transaction_ref}  amount={keep.amount}  status={keep.status}  created_at={keep.created_at}')

        self.stdout.write('\nDELETE (orphan duplicate)')
        self.stdout.write(f'  {delete.transaction_ref}  amount={delete.amount}  status={delete.status}  created_at={delete.created_at}')

        if keep.amount != delete.amount or keep.transaction_type != delete.transaction_type:
            raise CommandError('KEEP and DELETE transactions are not matching duplicates. Aborting.')

        # ── 2. Safety: confirm DELETE is not linked to any approved posting ──
        linked_postings = LoanRepaymentPosting.all_objects.filter(transaction=delete)
        if linked_postings.exists():
            refs = ', '.join(p.posting_ref for p in linked_postings)
            raise CommandError(
                f'Duplicate transaction is linked to posting(s): {refs}. Aborting to avoid data loss.'
            )
        self.stdout.write('\n  -> Duplicate transaction has no linked postings. Safe to delete.')

        # ── 3. Journal entry / lines for DELETE ───────────────────────────
        delete_jes = list(JournalEntry.all_objects.filter(transaction_id=DELETE_TXN_ID))
        self.stdout.write('\nJOURNAL ENTRY TO DELETE')
        total_lines = 0
        for je in delete_jes:
            lines = list(je.lines(manager='all_objects').select_related('account').all())
            total_lines += len(lines)
            self.stdout.write(f'  {je.journal_number}  status={je.status}  lines={len(lines)}')
            for line in lines:
                self.stdout.write(
                    f'    GL {line.account.gl_code} ({line.account.account_name}): '
                    f'Dr={line.debit_amount}  Cr={line.credit_amount}'
                )

        self.stdout.write('\nWILL DELETE')
        self.stdout.write(f'  JournalEntryLine records : {total_lines}')
        self.stdout.write(f'  JournalEntry records     : {len(delete_jes)}')
        self.stdout.write(f'  Transaction record       : 1  ({delete.transaction_ref})')
        self.stdout.write('\nWILL KEEP UNCHANGED')
        self.stdout.write(f'  Transaction {keep.transaction_ref} and its journal entry')
        self.stdout.write(f'  Loan {loan.loan_number} (fees_transaction_id stays {KEEP_TXN_ID})')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete - no changes written. Re-run with --commit to apply.\n'
            ))
            return

        # ── 4. Apply ─────────────────────────────────────────────────────
        with db_transaction.atomic():
            for je in delete_jes:
                lines_deleted, _ = je.lines(manager='all_objects').all().delete()
                self.stdout.write(f'  Deleted {lines_deleted} line(s) from JE {je.journal_number}')
                je.hard_delete()
                self.stdout.write(f'  Deleted JE {je.journal_number}')

            ref = delete.transaction_ref
            delete.hard_delete()
            self.stdout.write(f'  Deleted transaction {ref}')

        self.stdout.write(self.style.SUCCESS('\nDuplicate charges-at-disbursement record removed.\n'))

        # ── 5. Final verification ─────────────────────────────────────────
        loan.refresh_from_db()
        remaining = Transaction.all_objects.filter(loan_id=LOAN_ID, transaction_type='charges_at_disbursement')
        self.stdout.write('FINAL STATE')
        self.stdout.write(f'  charges_at_disbursement transactions remaining : {remaining.count()}')
        for t in remaining:
            self.stdout.write(f'    {t.transaction_ref}  {t.amount}')
        self.stdout.write(f'  loan.fees_transaction_id : {loan.fees_transaction_id}')
