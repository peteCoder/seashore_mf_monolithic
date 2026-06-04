"""
Management command: backfill_group_collection_postings
=======================================================

Creates missing LoanRepaymentPosting records for loan repayments that were
processed through group collection sessions (GroupCollectionSession and
GroupCombinedSession) but never had a posting record created.

ROOT CAUSE
----------
group_collection_approve() and group_combined_collection_approve() called
loan.record_repayment() directly, creating Transaction records but no
LoanRepaymentPosting records.  This caused the "Repayment Postings" tab
on the loan detail page to appear empty even though repayments were made.

WHAT THIS COMMAND DOES
-----------------------
For every approved GroupCollectionSession and GroupCombinedSession:
  1. Iterates each loan item in the session.
  2. Finds the matching loan_repayment Transaction (matched by loan + amount
     + transaction date on or near the session's collection_date).
  3. If no LoanRepaymentPosting already exists for that transaction, creates
     one with status='approved', linking the session's collected_by as
     submitted_by and the session's approved_by as reviewed_by.

Usage
-----
  python manage.py backfill_group_collection_postings --dry-run
  python manage.py backfill_group_collection_postings --commit
"""

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone
from datetime import timedelta

from core.models import (
    GroupCollectionSession, GroupCollectionItem,
    GroupCombinedSession, GroupCombinedLoanItem,
    LoanRepaymentPosting, Transaction,
)


class Command(BaseCommand):
    help = 'Backfill missing LoanRepaymentPosting records for group collection sessions'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                           help='Show what would be created without writing to DB')
        group.add_argument('--commit', action='store_true',
                           help='Apply the changes')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(
            f'\n=== backfill_group_collection_postings [{mode}] ===\n'
        ))

        created = 0
        skipped = 0

        # ── GroupCollectionSession (loan-only sessions) ───────────────────
        self.stdout.write('Processing GroupCollectionSession (loan-only) ...')
        loan_sessions = GroupCollectionSession.objects.filter(
            status='approved'
        ).select_related('group', 'collected_by', 'approved_by').prefetch_related('items__loan')

        for session in loan_sessions:
            for item in session.items.select_related('loan'):
                c, s = self._backfill_item(
                    loan=item.loan,
                    amount=item.amount,
                    collection_date=session.collection_date,
                    submitted_by=session.collected_by,
                    reviewed_by=session.approved_by,
                    notes=f'Group collection: {session.group.name} ({session.collection_date})',
                    dry_run=dry_run,
                )
                created += c
                skipped += s

        # ── GroupCombinedSession (loan + savings) ─────────────────────────
        self.stdout.write('Processing GroupCombinedSession (combined) ...')
        combined_sessions = GroupCombinedSession.objects.filter(
            status='approved'
        ).select_related('group', 'collected_by', 'approved_by').prefetch_related('loan_items__loan')

        for session in combined_sessions:
            for item in session.loan_items.select_related('loan'):
                c, s = self._backfill_item(
                    loan=item.loan,
                    amount=item.amount,
                    collection_date=session.collection_date,
                    submitted_by=session.collected_by,
                    reviewed_by=session.approved_by,
                    notes=f'Group combined collection: {session.group.name} ({session.collection_date})',
                    dry_run=dry_run,
                )
                created += c
                skipped += s

        self.stdout.write(f'\n{"-" * 50}')
        self.stdout.write(f'Postings {"to create" if dry_run else "created"} : {created}')
        self.stdout.write(f'Already existed (skipped)          : {skipped}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete -- no changes written. Re-run with --commit to apply.\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n[OK] {created} posting(s) backfilled.\n'
            ))

    def _backfill_item(self, loan, amount, collection_date,
                       submitted_by, reviewed_by, notes, dry_run):
        """
        Find the transaction for this collection item and create a posting
        if one doesn't already exist.
        Returns (created_count, skipped_count).
        """
        # Find the matching loan_repayment transaction.
        # Match by loan + amount + date within a ±1-day window
        # (timezone offsets can shift the stored date by 1 day).
        txn = Transaction.objects.filter(
            loan=loan,
            transaction_type='loan_repayment',
            amount=amount,
            transaction_date__date__gte=collection_date - timedelta(days=1),
            transaction_date__date__lte=collection_date + timedelta(days=1),
        ).order_by('transaction_date').first()

        if txn is None:
            self.stdout.write(self.style.WARNING(
                f'  WARNING: No matching transaction for {loan.loan_number} '
                f'amount={amount} date={collection_date} -- skipping'
            ))
            return 0, 0

        # Check if a posting already links to this transaction
        if LoanRepaymentPosting.objects.filter(transaction=txn).exists():
            return 0, 1

        if dry_run:
            self.stdout.write(
                f'  [DRY] Would create posting for {loan.loan_number} '
                f'amount={amount} date={collection_date} txn={txn.transaction_ref}'
            )
            return 1, 0

        with db_transaction.atomic():
            LoanRepaymentPosting.objects.create(
                loan=loan,
                client=loan.client,
                branch=loan.branch,
                amount=amount,
                payment_date=collection_date,
                status='approved',
                submitted_by=submitted_by,
                reviewed_by=reviewed_by,
                reviewed_at=timezone.now(),
                transaction=txn,
                submission_notes=notes,
            )

        self.stdout.write(
            f'  Created posting for {loan.loan_number} '
            f'amount={amount} date={collection_date}'
        )
        return 1, 0
