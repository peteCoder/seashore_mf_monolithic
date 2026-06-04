"""
Management command: correct_mercy_repayment
===========================================

Corrects a missing ₦5,000 repayment on Mercy Saturday's loan that was not
reflected in the loan balance due to a race condition during posting approval.

ROOT CAUSE
----------
When posting LRP20260513130935EV41GL was approved on May 13, 2026, two concurrent
requests both read the same stale outstanding balance (₦108,000). Both subtracted
₦5,000 and saved ₦103,000 — the second write cancelled out the first deduction.
Two Transaction records were created but the balance only moved once.

GHOST TRANSACTION:  TXN20260513170139489770  (₦5,000, May 13 2026)
LINKED TRANSACTION: TXN20260513170143270126  (₦5,000, May 13 2026, tied to posting)

WHAT THIS COMMAND DOES
----------------------
1. Calls loan.record_repayment(5_000) to process the missing payment through the
   full business logic (schedule update, balance update, new transaction record).
2. Annotates the ghost transaction description so it is clearly labelled.

A new correction transaction is created (5th repayment transaction). This is the
cleanest auditable approach — it makes every credit traceable to a real event.

Loan    : 8c62540b-d395-44f2-93d9-be481bda9ae0  (LN20260422151501946926)
Client  : Mercy Saturday
Ghost   : TXN20260513170139489770
Posted  : LRP20260513130935EV41GL

BEFORE                      AFTER
  amount_paid      : 15,000    20,000
  outstanding      : 103,000   98,000

Usage
-----
  python manage.py correct_mercy_repayment --dry-run
  python manage.py correct_mercy_repayment --commit
"""

from decimal import Decimal
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone


LOAN_ID          = '8c62540b-d395-44f2-93d9-be481bda9ae0'
GHOST_TXN_REF    = 'TXN20260513170139489770'
POSTING_REF      = 'LRP20260513130935EV41GL'
CORRECTION_AMOUNT = Decimal('5000.00')

EXPECTED_AMOUNT_PAID    = Decimal('15000.00')
EXPECTED_OUTSTANDING    = Decimal('103000.00')
EXPECTED_AFTER_PAID     = Decimal('20000.00')
EXPECTED_AFTER_BALANCE  = Decimal('98000.00')

CORRECTION_DATE = datetime.date(2026, 5, 13)   # original payment date


class Command(BaseCommand):
    help = 'Correct missing ₦5,000 repayment on Mercy Saturday loan LN20260422151501946926'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                           help='Show what will change without writing to the DB')
        group.add_argument('--commit', action='store_true',
                           help='Apply the correction')

    def handle(self, *args, **options):
        from core.models import Loan, Transaction, LoanRepaymentPosting

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(f'\n=== correct_mercy_repayment [{mode}] ===\n'))

        # ── 1. Fetch loan ────────────────────────────────────────────────
        try:
            loan = Loan.objects.select_related('client', 'branch').get(id=LOAN_ID)
        except Loan.DoesNotExist:
            raise CommandError(f'Loan {LOAN_ID} not found.')

        self.stdout.write('LOAN')
        self.stdout.write(f'  id              : {loan.id}')
        self.stdout.write(f'  loan_number     : {loan.loan_number}')
        self.stdout.write(f'  client          : {loan.client.get_full_name()}')
        self.stdout.write(f'  status          : {loan.status}')
        self.stdout.write(f'  amount_paid     : {loan.amount_paid}  (expected {EXPECTED_AMOUNT_PAID})')
        self.stdout.write(f'  outstanding_bal : {loan.outstanding_balance}  (expected {EXPECTED_OUTSTANDING})')

        if loan.amount_paid != EXPECTED_AMOUNT_PAID:
            raise CommandError(
                f'Loan.amount_paid is {loan.amount_paid}, expected {EXPECTED_AMOUNT_PAID}. '
                f'Data may have already been corrected or has unexpected state. Aborting.'
            )
        if loan.outstanding_balance != EXPECTED_OUTSTANDING:
            raise CommandError(
                f'Loan.outstanding_balance is {loan.outstanding_balance}, expected {EXPECTED_OUTSTANDING}. '
                f'Aborting.'
            )
        if loan.status not in ('active', 'overdue'):
            raise CommandError(
                f'Loan status is {loan.status!r}; must be active or overdue to record repayment.'
            )

        # ── 2. Repayment schedule summary ────────────────────────────────
        self.stdout.write('\nREPAYMENT SCHEDULE (current state)')
        rows = loan.repayment_schedule.order_by('installment_number')
        for r in rows:
            self.stdout.write(
                f'  Row {r.installment_number}: due={r.due_date}  '
                f'status={r.status}  amount_paid={r.amount_paid}  '
                f'outstanding={r.outstanding_amount}'
            )

        # ── 3. Ghost transaction ─────────────────────────────────────────
        try:
            ghost_txn = Transaction.objects.get(transaction_ref=GHOST_TXN_REF)
        except Transaction.DoesNotExist:
            raise CommandError(f'Ghost transaction {GHOST_TXN_REF} not found. Aborting.')

        self.stdout.write(f'\nGHOST TRANSACTION')
        self.stdout.write(f'  ref            : {ghost_txn.transaction_ref}')
        self.stdout.write(f'  amount         : {ghost_txn.amount}')
        self.stdout.write(f'  balance_before : {ghost_txn.balance_before}')
        self.stdout.write(f'  balance_after  : {ghost_txn.balance_after}')
        self.stdout.write(f'  description    : {ghost_txn.description}')
        self.stdout.write(f'  status         : {ghost_txn.status}')

        # ── 4. Approved posting — find who approved it (correction author) ──
        try:
            posting = LoanRepaymentPosting.objects.select_related('reviewed_by', 'submitted_by').get(
                posting_ref=POSTING_REF
            )
            approver = posting.reviewed_by or posting.submitted_by
        except LoanRepaymentPosting.DoesNotExist:
            raise CommandError(f'Posting {POSTING_REF} not found. Aborting.')

        self.stdout.write(f'\nAPPROVED POSTING')
        self.stdout.write(f'  ref        : {posting.posting_ref}')
        self.stdout.write(f'  reviewed_by: {posting.reviewed_by}')
        self.stdout.write(f'  approver   : {approver}  (will be used as processed_by on correction txn)')

        # ── 5. Show what will change ─────────────────────────────────────
        self.stdout.write(f'\nPROPOSED CHANGES')
        self.stdout.write(f'  Loan.amount_paid        : {EXPECTED_AMOUNT_PAID} → {EXPECTED_AFTER_PAID}')
        self.stdout.write(f'  Loan.outstanding_balance: {EXPECTED_OUTSTANDING} → {EXPECTED_AFTER_BALANCE}')
        self.stdout.write(f'  Repayment schedule rows : will be updated by record_repayment()')
        self.stdout.write(f'  New correction txn      : ₦{CORRECTION_AMOUNT:,.2f} dated {CORRECTION_DATE}')
        self.stdout.write(f'  Ghost txn description   : will be annotated "[DUPLICATE — race condition]"')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete — no changes written. Re-run with --commit to apply.\n'))
            return

        # ── 6. Apply ─────────────────────────────────────────────────────
        with db_transaction.atomic():
            # Record the missing repayment through the standard business logic.
            # This updates loan.amount_paid, loan.outstanding_balance, all schedule
            # rows, and creates a new Transaction + journal entry atomically.
            correction_txn = loan.record_repayment(
                amount=CORRECTION_AMOUNT,
                processed_by=approver,
                description=(
                    f'Correction repayment — ₦5,000 collected {CORRECTION_DATE} '
                    f'not reflected in balance due to race condition on posting '
                    f'{POSTING_REF}. Ghost txn: {GHOST_TXN_REF}.'
                ),
                transaction_date=CORRECTION_DATE,
            )

            # Annotate the ghost transaction so it is identifiable in audits.
            ghost_txn.description = (
                f'[DUPLICATE — race condition] {ghost_txn.description or "Loan repayment"} '
                f'— balance deduction did not apply; corrected by {correction_txn.transaction_ref}'
            )
            ghost_txn.save(update_fields=['description', 'updated_at'])

        # Refresh and report
        loan.refresh_from_db()
        self.stdout.write(self.style.SUCCESS('\n✓ Correction applied successfully.\n'))
        self.stdout.write('LOAN AFTER')
        self.stdout.write(f'  amount_paid     : {loan.amount_paid}')
        self.stdout.write(f'  outstanding_bal : {loan.outstanding_balance}')
        self.stdout.write(f'  status          : {loan.status}')
        self.stdout.write(f'\nNew transaction : {correction_txn.transaction_ref}')
        self.stdout.write(f'Ghost annotated : {GHOST_TXN_REF}')

        self.stdout.write('\nREPAYMENT SCHEDULE (after correction)')
        for r in loan.repayment_schedule.order_by('installment_number'):
            self.stdout.write(
                f'  Row {r.installment_number}: due={r.due_date}  '
                f'status={r.status}  amount_paid={r.amount_paid}  '
                f'outstanding={r.outstanding_amount}'
            )
