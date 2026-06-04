"""
Management command: delete_mercy_ghost_transaction
====================================================

Removes the ghost (duplicate) loan repayment transaction created by a race
condition on 13 May 2026, along with its journal entry and lines.

BACKGROUND
----------
When posting LRP20260513130935EV41GL was approved, two concurrent requests
both called record_repayment() simultaneously. Each created its own
Transaction and JournalEntry, but because both read the same stale outstanding
balance the loan's amount_paid was only updated once.

The correction command (correct_mercy_repayment) already fixed the loan balance
and created a proper 4th repayment transaction. This command removes the ghost
transaction and its accounting records so the transaction ledger shows exactly
4 repayment entries matching the 4 real economic events.

GHOST TRANSACTION:  TXN20260513170139489770
  - ₦5,000 Loan Repayment, May 13 2026
  - Created by the first (losing) request in the race condition
  - NOT linked to any approved posting
  - balance_before/balance_after based on stale data — WRONG
  - Its journal entries overstate cash receipts and understate loan receivable

WHAT THIS COMMAND DOES
-----------------------
1. Fetches the ghost Transaction by reference and verifies it is not linked
   to any approved posting (so we are definitely removing the right record).
2. Deletes the JournalEntryLine records inside the ghost's JournalEntry.
3. Deletes the JournalEntry record itself.
4. Deletes the ghost Transaction record.
5. Does NOT touch the loan balance (already corrected to ₦98,000 by the
   correct_mercy_repayment command).

AFTER THIS COMMAND
-------------------
  Repayment transactions : 4  (Apr 29, May 06, May 13 legit, correction)
  Loan outstanding       : ₦98,000  (unchanged)
  Journal entries        : 4 loan-repayment JEs matching the 4 transactions

Loan   : 8c62540b-d395-44f2-93d9-be481bda9ae0  (LN20260422151501946926)
Ghost  : TXN20260513170139489770
Legit  : TXN20260513170143270126  (linked to LRP20260513130935EV41GL)

Usage
-----
  python manage.py delete_mercy_ghost_transaction --dry-run
  python manage.py delete_mercy_ghost_transaction --commit
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


GHOST_TXN_REF  = 'TXN20260513170139489770'
LEGIT_TXN_REF  = 'TXN20260513170143270126'
POSTING_REF    = 'LRP20260513130935EV41GL'
LOAN_ID        = '8c62540b-d395-44f2-93d9-be481bda9ae0'


class Command(BaseCommand):
    help = 'Delete ghost duplicate transaction TXN20260513170139489770 and its journal entries'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                           help='Show what will be deleted without writing to the DB')
        group.add_argument('--commit', action='store_true',
                           help='Apply the deletion')

    def handle(self, *args, **options):
        from core.models import Transaction, LoanRepaymentPosting, JournalEntry, Loan

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(
            f'\n=== delete_mercy_ghost_transaction [{mode}] ===\n'
        ))

        # ── 1. Fetch ghost transaction ────────────────────────────────────
        try:
            ghost = Transaction.objects.get(transaction_ref=GHOST_TXN_REF)
        except Transaction.DoesNotExist:
            raise CommandError(f'Ghost transaction {GHOST_TXN_REF} not found. '
                               f'It may have already been deleted.')

        self.stdout.write('GHOST TRANSACTION')
        self.stdout.write(f'  ref            : {ghost.transaction_ref}')
        self.stdout.write(f'  type           : {ghost.transaction_type}')
        self.stdout.write(f'  amount         : {ghost.amount}')
        self.stdout.write(f'  date           : {ghost.transaction_date}')
        self.stdout.write(f'  status         : {ghost.status}')
        self.stdout.write(f'  balance_before : {ghost.balance_before}')
        self.stdout.write(f'  balance_after  : {ghost.balance_after}')
        self.stdout.write(f'  description    : {ghost.description}')

        # ── 2. Safety: confirm no posting is linked to the ghost ──────────
        # The posting should link to the LEGIT transaction, not the ghost.
        linked_postings = LoanRepaymentPosting.objects.filter(transaction=ghost)
        if linked_postings.exists():
            refs = ', '.join(p.posting_ref for p in linked_postings)
            raise CommandError(
                f'Ghost transaction is linked to posting(s): {refs}. '
                f'This is unexpected — aborting to avoid data loss. '
                f'Investigate manually before proceeding.'
            )
        self.stdout.write('  → No approved postings linked to ghost. Safe to delete.')

        # ── 3. Confirm legit transaction and posting are intact ───────────
        try:
            legit = Transaction.objects.get(transaction_ref=LEGIT_TXN_REF)
            self.stdout.write(f'\nLEGIT TRANSACTION')
            self.stdout.write(f'  ref    : {legit.transaction_ref}')
            self.stdout.write(f'  amount : {legit.amount}')
            self.stdout.write(f'  status : {legit.status}')
        except Transaction.DoesNotExist:
            raise CommandError(f'Legitimate transaction {LEGIT_TXN_REF} not found. Aborting.')

        try:
            posting = LoanRepaymentPosting.objects.select_related('transaction').get(
                posting_ref=POSTING_REF
            )
            self.stdout.write(f'\nAPPROVED POSTING')
            self.stdout.write(f'  ref         : {posting.posting_ref}')
            self.stdout.write(f'  status      : {posting.status}')
            linked_txn_ref = posting.transaction.transaction_ref if posting.transaction else 'NULL'
            self.stdout.write(f'  transaction : {linked_txn_ref}')
            if posting.transaction and posting.transaction.transaction_ref != LEGIT_TXN_REF:
                raise CommandError(
                    f'Posting {POSTING_REF} is linked to {linked_txn_ref}, '
                    f'expected {LEGIT_TXN_REF}. Aborting.'
                )
        except LoanRepaymentPosting.DoesNotExist:
            raise CommandError(f'Posting {POSTING_REF} not found. Aborting.')

        # ── 4. Current loan balance ───────────────────────────────────────
        loan = Loan.objects.get(id=LOAN_ID)
        self.stdout.write(f'\nLOAN (will not be changed)')
        self.stdout.write(f'  amount_paid     : {loan.amount_paid}')
        self.stdout.write(f'  outstanding_bal : {loan.outstanding_balance}')

        # ── 5. Find journal entries linked to ghost ───────────────────────
        ghost_jes = list(ghost.journal_entries.prefetch_related('lines').all())
        self.stdout.write(f'\nJOURNAL ENTRIES TO DELETE')
        if not ghost_jes:
            self.stdout.write('  (none found — ghost may have no JEs)')
        total_lines = 0
        for je in ghost_jes:
            line_count = je.lines.count()
            total_lines += line_count
            self.stdout.write(
                f'  JE {je.journal_number}  status={je.status}  '
                f'type={je.entry_type}  lines={line_count}'
            )
            for line in je.lines.select_related('account').all():
                self.stdout.write(
                    f'    GL {line.account.gl_code} '
                    f'({line.account.account_name}): '
                    f'Dr={line.debit_amount}  Cr={line.credit_amount}'
                )

        # ── 6. Repayment transactions after deletion ──────────────────────
        remaining_txns = (
            Transaction.objects
            .filter(loan_id=LOAN_ID, transaction_type='loan_repayment')
            .exclude(transaction_ref=GHOST_TXN_REF)
            .order_by('transaction_date', 'created_at')
        )
        self.stdout.write(f'\nREPAYMENT TRANSACTIONS THAT WILL REMAIN ({remaining_txns.count()})')
        for t in remaining_txns:
            self.stdout.write(f'  {t.transaction_ref}  ₦{t.amount}  {t.transaction_date}  {t.status}')

        # ── 7. Summary of deletions ───────────────────────────────────────
        self.stdout.write(f'\nWILL DELETE')
        self.stdout.write(f'  JournalEntryLine records : {total_lines}')
        self.stdout.write(f'  JournalEntry records     : {len(ghost_jes)}')
        self.stdout.write(f'  Transaction record       : 1  ({GHOST_TXN_REF})')
        self.stdout.write(f'  Loan balance change      : NONE (already correct at ₦{loan.outstanding_balance:,.2f})')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete — no changes written. Re-run with --commit to apply.\n'
            ))
            return

        # ── 8. Apply ─────────────────────────────────────────────────────
        with db_transaction.atomic():
            # Delete JE lines first (FK constraints), then JE headers, then transaction.
            for je in ghost_jes:
                lines_deleted, _ = je.lines.all().delete()
                self.stdout.write(f'  Deleted {lines_deleted} line(s) from JE {je.journal_number}')
                je.hard_delete()
                self.stdout.write(f'  Deleted JE {je.journal_number}')

            ghost.hard_delete()
            self.stdout.write(f'  Deleted transaction {GHOST_TXN_REF}')

        self.stdout.write(self.style.SUCCESS('\n✓ Ghost transaction deleted successfully.\n'))

        # ── 9. Final verification ─────────────────────────────────────────
        loan.refresh_from_db()
        final_count = Transaction.objects.filter(
            loan_id=LOAN_ID, transaction_type='loan_repayment'
        ).count()
        self.stdout.write('FINAL STATE')
        self.stdout.write(f'  Repayment transactions : {final_count}')
        self.stdout.write(f'  Loan amount_paid       : {loan.amount_paid}')
        self.stdout.write(f'  Loan outstanding       : {loan.outstanding_balance}')
