"""
Management command: redate_loan_disbursement
=============================================

Corrects the disbursement date on a loan and rebuilds everything that
depends on it:

  1. Loan.disbursement_date
  2. Loan.first_repayment_date      (recalculated from new disbursement date)
  3. Loan.next_repayment_date       (reset to first_repayment_date when no
                                     repayments have been posted yet)
  4. Loan.final_repayment_date      (recalculated)
  5. Transaction.transaction_date   (the loan_disbursement transaction)
  6. JournalEntry.transaction_date  (DateField  — loan_disbursement journal)
  7. JournalEntry.posting_date      (DateField)
  8. JournalEntry.posted_at         (DateTimeField — "Posted By" audit trail)
  9. JournalEntry.created_at        (DateTimeField — "Created By" audit trail,
                                     updated via queryset.update() to bypass
                                     auto_now_add)
 10. JournalEntry.reference_number  (embedded date digits replaced)
 11. LoanRepaymentSchedule rows     (all deleted and regenerated from scratch)

The original time-of-day (HH:MM:SS) is preserved on all DateTimeFields.

Usage:
    python manage.py redate_loan_disbursement <loan-uuid> <new-date> --dry-run
    python manage.py redate_loan_disbursement <loan-uuid> <new-date> --confirm

Example:
    python manage.py redate_loan_disbursement 5f74e11c-e5c1-4d19-a6d4-067ec84d0a74 2026-03-12 --dry-run
    python manage.py redate_loan_disbursement 5f74e11c-e5c1-4d19-a6d4-067ec84d0a74 2026-03-12 --confirm
"""

import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction
from django.utils import timezone
from dateutil.relativedelta import relativedelta


def _replace_date(original_dt, new_date):
    """
    Timezone-aware datetime with the same time-of-day as original_dt but
    with the calendar date replaced by new_date.
    Falls back to midnight if original_dt is None or not a datetime.
    """
    if original_dt and isinstance(original_dt, datetime.datetime):
        local_dt = timezone.localtime(original_dt)
        return timezone.make_aware(
            datetime.datetime.combine(new_date, local_dt.time())
        )
    return timezone.make_aware(
        datetime.datetime.combine(new_date, datetime.time.min)
    )


def _replace_date_digits(text, old_date, new_date):
    """
    Replace the first occurrence of old_date's YYYYMMDD digits in text
    with new_date's digits.  Returns text unchanged if the pattern isn't found.
    """
    old_digits = old_date.strftime('%Y%m%d')
    new_digits = new_date.strftime('%Y%m%d')
    if old_digits in text:
        return text.replace(old_digits, new_digits, 1)
    return text


class Command(BaseCommand):
    help = (
        "Correct a loan's disbursement date and rebuild all dependent records "
        "(repayment schedule, disbursement transaction, journal entry)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'loan_uuid',
            type=str,
            help='UUID of the loan to correct.',
        )
        parser.add_argument(
            'new_date',
            type=str,
            help='Correct disbursement date in YYYY-MM-DD format.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview all changes without writing anything.',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually execute the updates (required to write).',
        )

    def handle(self, *args, **options):
        from core.models import (
            Loan, Transaction, JournalEntry, LoanRepaymentSchedule,
        )
        from core.utils.helpers import (
            generate_repayment_schedule,
            next_business_day,
            add_one_business_day,
        )

        loan_uuid    = options['loan_uuid']
        new_date_str = options['new_date']
        dry_run      = options['dry_run']
        confirm      = options['confirm']

        if not dry_run and not confirm:
            raise CommandError(
                "Pass --dry-run to preview, or --confirm to execute."
            )

        # ── Parse date ────────────────────────────────────────────────────────
        try:
            new_date = datetime.date.fromisoformat(new_date_str)
        except ValueError:
            raise CommandError(
                f"Invalid date '{new_date_str}'. Use YYYY-MM-DD format."
            )

        # ── Resolve loan ──────────────────────────────────────────────────────
        try:
            loan = Loan.all_objects.select_related(
                'loan_product', 'client', 'branch'
            ).get(id=loan_uuid)
        except Loan.DoesNotExist:
            raise CommandError(f"No loan found with UUID: {loan_uuid}")

        if loan.status not in ('active', 'overdue', 'completed'):
            raise CommandError(
                f"Loan {loan.loan_number} has status "
                f"'{loan.get_status_display()}' — disbursement date can only "
                f"be corrected on a disbursed loan."
            )

        old_disburse_date = (
            timezone.localtime(loan.disbursement_date).date()
            if loan.disbursement_date else None
        )
        if old_disburse_date is None:
            raise CommandError(
                f"Loan {loan.loan_number} has no disbursement_date recorded."
            )

        self.stdout.write(
            f"\nLoan:          {loan.loan_number}"
            f"\nClient:        {loan.client.get_full_name()} "
            f"({loan.client.client_id})"
            f"\nFrequency:     {loan.get_repayment_frequency_display()}"
            f"\nInstallments:  {loan.number_of_installments}"
            f"\nOld date:      {old_disburse_date}  "
            f"({old_disburse_date.strftime('%A')})"
            f"\nNew date:      {new_date}  ({new_date.strftime('%A')})"
            "\n" + "=" * 60
        )

        # ── Calculate new repayment dates ─────────────────────────────────────
        grace_days = 0
        try:
            if loan.loan_product_id and loan.loan_product:
                grace_days = loan.loan_product.grace_period_days or 0
        except Exception:
            pass

        schedule_start        = new_date + datetime.timedelta(days=grace_days)
        new_first_repayment   = loan.calculate_next_payment_date(schedule_start)
        new_next_repayment    = new_first_repayment   # all pending — no payments yet

        # Final repayment date = first + (n-1) periods
        n    = loan.number_of_installments
        freq = loan.repayment_frequency
        if freq == 'daily':
            _d = new_first_repayment
            for _ in range(n - 1):
                _d = add_one_business_day(_d)
            new_final_repayment = _d
        elif freq == 'weekly':
            new_final_repayment = next_business_day(
                new_first_repayment + datetime.timedelta(weeks=n - 1)
            )
        elif freq == 'fortnightly':
            new_final_repayment = next_business_day(
                new_first_repayment + datetime.timedelta(weeks=(n - 1) * 2)
            )
        elif freq == 'yearly':
            new_final_repayment = next_business_day(
                new_first_repayment + relativedelta(years=n - 1)
            )
        else:  # monthly
            new_final_repayment = next_business_day(
                new_first_repayment + relativedelta(months=n - 1)
            )

        new_disburse_dt = _replace_date(loan.disbursement_date, new_date)

        # ── Find disbursement transaction ─────────────────────────────────────
        disburse_txn = Transaction.all_objects.filter(
            loan=loan,
            transaction_type='loan_disbursement',
        ).first()

        # ── Find disbursement journal entry ───────────────────────────────────
        disburse_journal = None
        if disburse_txn:
            disburse_journal = JournalEntry.all_objects.filter(
                entry_type='loan_disbursement',
                transaction=disburse_txn,
            ).first()
        if disburse_journal is None:
            disburse_journal = JournalEntry.all_objects.filter(
                entry_type='loan_disbursement',
                loan=loan,
            ).first()

        # ── Existing schedule rows ────────────────────────────────────────────
        existing_schedule = LoanRepaymentSchedule.all_objects.filter(loan=loan)
        existing_count    = existing_schedule.count()

        # ── Preview ───────────────────────────────────────────────────────────
        self.stdout.write("\nLoan date fields:")
        self._show("  disbursement_date",
                   loan.disbursement_date,  new_disburse_dt)
        self._show("  first_repayment_date",
                   loan.first_repayment_date, new_first_repayment)
        self._show("  next_repayment_date",
                   loan.next_repayment_date,  new_next_repayment)
        self._show("  final_repayment_date",
                   loan.final_repayment_date, new_final_repayment)

        if disburse_txn:
            self.stdout.write(
                f"\nDisbursement transaction [{disburse_txn.transaction_ref}]:"
            )
            self._show("  transaction_date",
                       disburse_txn.transaction_date,
                       _replace_date(disburse_txn.transaction_date, new_date))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\n  No loan_disbursement transaction found — skipping."
                )
            )

        if disburse_journal:
            old_ref     = disburse_journal.reference_number or ''
            new_ref     = _replace_date_digits(old_ref, old_disburse_date, new_date)
            self.stdout.write(
                f"\nDisbursement journal [{disburse_journal.journal_number}]:"
            )
            self._show("  transaction_date",
                       disburse_journal.transaction_date, new_date)
            self._show("  posting_date",
                       disburse_journal.posting_date, new_date)
            self._show("  posted_at",
                       disburse_journal.posted_at,
                       _replace_date(disburse_journal.posted_at, new_date))
            self._show("  created_at",
                       disburse_journal.created_at,
                       _replace_date(disburse_journal.created_at, new_date))
            self._show("  reference_number", old_ref, new_ref)
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\n  No loan_disbursement journal entry found — skipping."
                )
            )

        self.stdout.write(
            f"\nRepayment schedule:  "
            f"{self.style.WARNING(str(existing_count))} existing rows will be "
            f"deleted and {self.style.SUCCESS(str(n))} rows regenerated."
        )
        self.stdout.write(
            f"  New schedule: {new_first_repayment} → {new_final_repayment}"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN complete — no changes were made.\n")
            )
            return

        # ── Execute ───────────────────────────────────────────────────────────
        self.stdout.write(self.style.WARNING("\nExecuting update..."))

        with db_transaction.atomic():

            # 1. Update loan date fields
            loan.disbursement_date     = new_disburse_dt
            loan.first_repayment_date  = new_first_repayment
            loan.next_repayment_date   = new_next_repayment
            loan.final_repayment_date  = new_final_repayment
            loan.save(update_fields=[
                'disbursement_date', 'first_repayment_date',
                'next_repayment_date', 'final_repayment_date', 'updated_at',
            ])
            self._done("Loan disbursement_date",    new_disburse_dt)
            self._done("Loan first_repayment_date", new_first_repayment)
            self._done("Loan next_repayment_date",  new_next_repayment)
            self._done("Loan final_repayment_date", new_final_repayment)

            # 2. Update disbursement transaction
            if disburse_txn:
                new_txn_dt = _replace_date(disburse_txn.transaction_date, new_date)
                disburse_txn.transaction_date = new_txn_dt
                disburse_txn.save(update_fields=['transaction_date'])
                self._done("Transaction.transaction_date", new_txn_dt)

            # 3. Update disbursement journal entry
            if disburse_journal:
                new_posted_at  = _replace_date(disburse_journal.posted_at,  new_date)
                new_created_at = _replace_date(disburse_journal.created_at, new_date)
                new_ref        = _replace_date_digits(
                    disburse_journal.reference_number or '',
                    old_disburse_date, new_date,
                )
                disburse_journal.transaction_date = new_date
                disburse_journal.posting_date     = new_date
                disburse_journal.posted_at        = new_posted_at
                disburse_journal.save(update_fields=[
                    'transaction_date', 'posting_date', 'posted_at',
                ])
                # created_at is auto_now_add — must use queryset.update()
                JournalEntry.all_objects.filter(pk=disburse_journal.pk).update(
                    created_at=new_created_at,
                    reference_number=new_ref,
                )
                self._done("JournalEntry.transaction_date", new_date)
                self._done("JournalEntry.posting_date",     new_date)
                self._done("JournalEntry.posted_at",        new_posted_at)
                self._done("JournalEntry.created_at",       new_created_at)
                self._done("JournalEntry.reference_number", new_ref)

            # 4. Delete existing schedule rows (hard delete — these are just
            #    calculated data, not financial records)
            deleted_count, _ = existing_schedule.delete()
            self._done(f"LoanRepaymentSchedule rows deleted", deleted_count)

            # 5. Regenerate schedule from the now-corrected loan dates
            #    (loan.disbursement_date and first_repayment_date are already
            #     updated in memory and saved above)
            schedule_items = generate_repayment_schedule(loan)
            if schedule_items:
                LoanRepaymentSchedule.objects.bulk_create([
                    LoanRepaymentSchedule(
                        loan=loan,
                        installment_number=item['installment_number'],
                        due_date=item['due_date'],
                        principal_amount=item['principal_amount'],
                        interest_amount=item['interest_amount'],
                        total_amount=item['total_amount'],
                        outstanding_amount=item['total_amount'],
                        status='pending',
                    )
                    for item in schedule_items
                ])
                self._done(
                    f"LoanRepaymentSchedule rows created",
                    len(schedule_items),
                )
                self.stdout.write(
                    f"    First due: {schedule_items[0]['due_date']}  "
                    f"Last due: {schedule_items[-1]['due_date']}"
                )
            else:
                self.stdout.write(
                    self.style.WARNING("  No schedule items generated.")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Loan {loan.loan_number} disbursement date corrected "
                f"to {new_date}. Schedule rebuilt with {n} installments.\n"
            )
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt(self, value):
        if isinstance(value, datetime.datetime):
            return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
        return str(value) if value is not None else '(none)'

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
