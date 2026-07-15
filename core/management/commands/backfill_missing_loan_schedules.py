"""
Management command: backfill_missing_loan_schedules
=====================================================

Fixes loans that are active/overdue/disbursed with an outstanding balance
but have ZERO LoanRepaymentSchedule rows. Such loans are structurally
invisible to /loans/repayment-tracker/ (which is built entirely from
LoanRepaymentSchedule rows) even though they still owe money — this is
the root cause of "repayment tracker only shows newly disbursed loans,
excluding old ones".

ROOT CAUSE
----------
Loan.disburse() used to swallow any failure while generating/persisting
the repayment schedule (an empty result from generate_repayment_schedule(),
or an outright exception) and still report "disbursed successfully". The
most common trigger was Loan.number_of_installments being stuck at its
model default of 0 — which happens for any loan that never went through
Loan.save()'s creation-time calculate_loan_details() call (e.g. rows
created via bulk_create(), which bypasses save() entirely, or loans from
before that calculation existed). Loan.disburse() has since been fixed to
self-heal this at disbursement time and to fail loudly instead of
silently — but that only prevents new occurrences. This command repairs
loans that were already affected.

WHAT IT DOES
------------
For every active/overdue/disbursed loan with outstanding_balance > 0 and
no LoanRepaymentSchedule rows:
1. If number_of_installments is 0, recompute it from duration_months and
   repayment_frequency (same formula Loan.disburse() now uses).
2. Generate and persist a fresh schedule via generate_repayment_schedule().
3. Re-allocate any existing APPROVED LoanRepaymentPosting records against
   the new rows (oldest-first), so a client who has genuinely been paying
   does not appear to have paid nothing.
4. Refresh next_repayment_date/final_repayment_date and drop a stale
   'overdue' loan-status back to 'active' (overdue is tracked at the
   schedule-row level, same convention as rebuild_loan_schedules.py).

Loans that still can't produce a schedule after the recalculation (e.g.
duration_months is itself 0, or an unexpected error) are reported and
skipped — they need manual review, not blind data changes.

WHAT IT DOES NOT TOUCH
-----------------------
- Loan.amount_paid / Loan.outstanding_balance — never modified.
- Transaction records — never modified.
- Loans that already have schedule rows — never touched.

Usage
-----
    python manage.py backfill_missing_loan_schedules --dry-run
    python manage.py backfill_missing_loan_schedules --commit
    python manage.py backfill_missing_loan_schedules --commit --loan-id <UUID>
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction, close_old_connections
from django.db.models import Exists, OuterRef, Prefetch
from django.utils import timezone

from core.models import Loan, LoanRepaymentSchedule, LoanRepaymentPosting
from core.utils.helpers import generate_repayment_schedule
from core.utils.money import MoneyCalculator
from core.management.commands.rebuild_loan_schedules import _compute_allocation


class Command(BaseCommand):
    help = (
        'Backfill LoanRepaymentSchedule rows for active/overdue/disbursed loans '
        'that have none, so they stop being invisible to the repayment tracker.'
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--commit', action='store_true')
        target = parser.add_mutually_exclusive_group()
        target.add_argument('--loan-id', metavar='UUID',
                             help='Process a single loan by UUID')
        target.add_argument('--loan-number', metavar='LN...',
                             help='Process a single loan by loan number')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        loan_id = options.get('loan_id')
        loan_number = options.get('loan_number')
        mode = 'DRY RUN' if dry_run else 'COMMIT'

        self.stdout.write(self.style.WARNING(
            f'\n=== backfill_missing_loan_schedules [{mode}] ===\n'
        ))

        today = timezone.now().date()

        base_qs = Loan.objects.filter(
            status__in=['active', 'overdue', 'disbursed'],
            outstanding_balance__gt=0,
        ).annotate(
            has_schedule=Exists(
                LoanRepaymentSchedule.objects.filter(loan=OuterRef('pk'))
            )
        ).filter(has_schedule=False)

        if loan_id:
            base_qs = base_qs.filter(id=loan_id)
        elif loan_number:
            base_qs = base_qs.filter(loan_number=loan_number)

        loan_ids = list(base_qs.values_list('id', flat=True))
        total = len(loan_ids)
        fixed = skipped = errors = 0

        self.stdout.write(f'Scope: {total} loan(s) with no repayment schedule\n')

        BATCH = 3
        for batch_start in range(0, total, BATCH):
            close_old_connections()
            batch = loan_ids[batch_start: batch_start + BATCH]

            loans = (
                Loan.objects
                .filter(id__in=batch)
                .select_related('loan_product', 'client')
                .prefetch_related(
                    Prefetch(
                        'repayment_postings',
                        queryset=LoanRepaymentPosting.objects.filter(
                            status='approved'
                        ).order_by('payment_date', 'created_at'),
                        to_attr='approved_postings',
                    )
                )
            )

            for loan in loans:
                client_name = loan.client.get_full_name() if loan.client else '?'

                # ── Self-heal number_of_installments if it's the legacy 0 ──────
                update_fields = []
                if not loan.number_of_installments or loan.number_of_installments <= 0:
                    freq_map = {
                        'daily':       loan.duration_months * 20,
                        'weekly':      loan.duration_months * 4,
                        'fortnightly': loan.duration_months * 2,
                        'monthly':     loan.duration_months,
                        'yearly':      max(1, loan.duration_months // 12),
                    }
                    recalculated_n = freq_map.get(loan.repayment_frequency, loan.duration_months)
                    if recalculated_n and recalculated_n > 0:
                        loan.number_of_installments = recalculated_n
                        update_fields.append('number_of_installments')
                        if not loan.installment_amount and loan.total_repayment:
                            loan.installment_amount = MoneyCalculator.round_money(
                                loan.total_repayment / recalculated_n
                            )
                            update_fields.append('installment_amount')

                try:
                    schedule_items = generate_repayment_schedule(loan)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'SKIP {loan.loan_number} ({client_name}) — generate failed: {e}'
                    ))
                    skipped += 1
                    continue

                if not schedule_items:
                    self.stdout.write(self.style.ERROR(
                        f'SKIP {loan.loan_number} ({client_name}) — could not generate '
                        f'a schedule (number_of_installments={loan.number_of_installments}, '
                        f'duration_months={loan.duration_months}). Needs manual review.'
                    ))
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  {loan.loan_number} -- {client_name}: '
                        f'would create {len(schedule_items)} installment(s)'
                        + (' + recalculate number_of_installments' if update_fields else '')
                    )
                    fixed += 1
                    continue

                try:
                    with db_transaction.atomic():
                        if update_fields:
                            loan.save(update_fields=update_fields)

                        schedule_objects = [
                            LoanRepaymentSchedule(
                                loan=loan,
                                installment_number=item['installment_number'],
                                due_date=item['due_date'],
                                principal_amount=item['principal_amount'],
                                interest_amount=item['interest_amount'],
                                total_amount=item['total_amount'],
                                outstanding_amount=item['total_amount'],
                                amount_paid=Decimal('0.00'),
                                status='pending',
                            )
                            for item in schedule_items
                        ]
                        LoanRepaymentSchedule.objects.bulk_create(schedule_objects)

                        # Allocate existing approved postings against the new rows
                        saved_rows = list(
                            LoanRepaymentSchedule.objects
                            .filter(loan=loan)
                            .order_by('installment_number')
                        )
                        postings = getattr(loan, 'approved_postings', [])
                        changes, next_due = _compute_allocation(saved_rows, postings, today)
                        for row, new_paid in changes:
                            row.amount_paid = new_paid
                            row.save(update_fields=[
                                'amount_paid', 'paid_date',
                                'outstanding_amount', 'status', 'updated_at',
                            ])

                        loan_update_fields = ['final_repayment_date', 'updated_at']
                        loan.final_repayment_date = saved_rows[-1].due_date
                        if next_due:
                            loan.next_repayment_date = next_due
                            loan_update_fields.append('next_repayment_date')
                        if loan.status == 'overdue':
                            loan.status = 'active'
                            loan_update_fields.append('status')
                        loan.save(update_fields=loan_update_fields)

                    self.stdout.write(
                        f'  FIXED {loan.loan_number} -- {client_name}: '
                        f'{len(schedule_objects)} installment(s) created'
                    )
                    fixed += 1

                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'ERROR {loan.loan_number} ({client_name}): {e}'
                    ))
                    errors += 1

            self.stdout.write(
                f'  Batch {batch_start // BATCH + 1}: '
                f'{min(batch_start + BATCH, total)}/{total} done '
                f'(fixed={fixed} skipped={skipped} errors={errors})'
            )

        self.stdout.write(f'\n{"-" * 60}')
        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run: {fixed} loan(s) would be fixed, {skipped} would need '
                f'manual review.\nRe-run with --commit to apply.\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'[OK] fixed={fixed}  skipped={skipped}  errors={errors}\n'
            ))
