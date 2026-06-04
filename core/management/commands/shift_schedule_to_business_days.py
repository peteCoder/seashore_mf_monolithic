"""
Management command: shift_schedule_to_business_days
====================================================

Shifts LoanRepaymentSchedule due_dates that fall on weekends (Sat/Sun) or
public holidays to the next valid business day.

WHEN TO USE
-----------
Run after adding new public holidays to /settings/public-holidays/.  Loans
disbursed before the holiday was recorded will have schedule rows on the new
holiday date — this command brings them into line.

HOW SHIFTING WORKS — TWO MODES (chosen automatically by frequency)
-------------------------------------------------------------------

WEEKLY / FORTNIGHTLY / MONTHLY / YEARLY loans
  Each installment is an independent date anchor.  Only the rows that land on
  a non-business day are moved; all others stay unchanged.  Duration is
  preserved — the total number of installments is the same.

  Example (weekly):
    Row 4: May 27 (holiday) → May 29         ← shifted
    Row 5: Jun  3 (Fri)     → unchanged      ← independent anchor

DAILY loans
  Every row is exactly one business day after the previous.  If one row
  shifts, every subsequent row must also cascade forward to maintain the
  one-installment-per-business-day invariant and preserve the full loan
  duration.

  Example (daily, two consecutive holidays):
    Row N:   May 26 (Mon)  → unchanged
    Row N+1: May 27 (Tue)  → May 29  (shifted — holiday)
    Row N+2: May 28 (Wed)  → May 30  (cascaded — holiday + N+1 took May 29)
    Row N+3: May 29 (Thu)  → Jun  2  (cascaded — N+2 took May 30)
    Row N+4: May 30 (Fri)  → Jun  3  (cascaded — N+3 took Jun 2)
    ...all subsequent rows cascade by the same offset

WHAT IS UPDATED
---------------
• LoanRepaymentSchedule.due_date          (pending / partial / overdue rows)
• Loan.next_repayment_date                (if it falls on a non-business day)
• Loan.final_repayment_date               (if it falls on a non-business day)

WHAT IS NEVER TOUCHED
---------------------
• paid / waived rows
• principal_amount / interest_amount / total_amount
• amount_paid / outstanding_amount
• status
• Loan balances

Usage
-----
  # Inspect a single loan first
  python manage.py shift_schedule_to_business_days --dry-run --loan-id <UUID>

  # Apply to a single loan
  python manage.py shift_schedule_to_business_days --commit --loan-id <UUID>

  # Inspect the full portfolio
  python manage.py shift_schedule_to_business_days --dry-run

  # Apply to all affected loans
  python manage.py shift_schedule_to_business_days --commit
"""

import datetime
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from core.utils.helpers import next_business_day, add_one_business_day, is_business_day


BATCH_SIZE = 500
MUTABLE_STATUSES = ('pending', 'partial', 'overdue')
DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

DAILY_FREQUENCIES = ('daily',)
ANCHORED_FREQUENCIES = ('weekly', 'fortnightly', 'monthly', 'yearly')


class Command(BaseCommand):
    help = (
        'Shift loan repayment schedule due_dates that fall on weekends or '
        'public holidays to the next valid business day.'
    )

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            '--dry-run', action='store_true',
            help='Show what will change without writing to the DB',
        )
        mode.add_argument(
            '--commit', action='store_true',
            help='Apply the changes',
        )
        parser.add_argument(
            '--loan-id', metavar='UUID',
            help='Process a single loan only (recommended for first runs)',
        )

    # -------------------------------------------------------------------------

    def handle(self, *args, **options):
        from core.models import LoanRepaymentSchedule, Loan, PublicHoliday

        dry_run  = options['dry_run']
        loan_id  = options.get('loan_id')
        mode     = 'DRY RUN' if dry_run else 'COMMIT'

        self.stdout.write(self.style.WARNING(
            f'\n=== shift_schedule_to_business_days [{mode}] ===\n'
        ))

        # ── 1. Load holidays ──────────────────────────────────────────────────
        holidays = set(PublicHoliday.objects.values_list('date', flat=True))
        holiday_map = dict(PublicHoliday.objects.values_list('date', 'name'))

        self.stdout.write(f'Public holidays loaded : {len(holidays)}')
        if holidays:
            upcoming = sorted(d for d in holidays if d >= datetime.date.today())[:8]
            if upcoming:
                self.stdout.write(
                    '  Upcoming : ' + ', '.join(
                        f'{d} ({holiday_map[d]})' for d in upcoming
                    )
                )

        # ── 2. Scope ──────────────────────────────────────────────────────────
        if loan_id:
            try:
                scope_loans = list(
                    Loan.objects.select_related('client', 'branch').filter(id=loan_id)
                )
            except Exception:
                raise CommandError(f'Invalid loan id: {loan_id}')
            if not scope_loans:
                raise CommandError(f'Loan {loan_id} not found.')
            self.stdout.write(
                f'\nScope : single loan {scope_loans[0].loan_number} '
                f'({scope_loans[0].client.get_full_name() if scope_loans[0].client else "?"})'
            )
        else:
            scope_loans = list(
                Loan.objects.select_related('client', 'branch').filter(
                    status__in=['active', 'overdue', 'disbursed']
                )
            )
            self.stdout.write(f'\nScope : full portfolio ({len(scope_loans)} active/overdue loans)')

        scope_loan_ids = [ln.id for ln in scope_loans]
        loan_by_id = {ln.id: ln for ln in scope_loans}

        # ── 3. Load all mutable schedule rows for scope ───────────────────────
        all_rows = list(
            LoanRepaymentSchedule.objects.filter(
                loan_id__in=scope_loan_ids,
                status__in=MUTABLE_STATUSES,
            ).order_by('loan_id', 'installment_number')
        )
        self.stdout.write(f'Schedule rows in scope : {len(all_rows)}')

        # Group rows by loan
        rows_by_loan = defaultdict(list)
        for row in all_rows:
            rows_by_loan[row.loan_id].append(row)

        # ── 4. Compute new dates per loan ─────────────────────────────────────
        # plan_by_loan: loan_id → list of (row, old_date, new_date)
        # Only entries where old_date != new_date are included.
        plan_by_loan = {}
        total_row_changes = 0
        collision_count   = 0

        for lid, rows in rows_by_loan.items():
            loan_obj = loan_by_id.get(lid)
            if loan_obj is None:
                continue

            freq = loan_obj.repayment_frequency

            if freq in DAILY_FREQUENCIES:
                changes = _plan_daily(rows, holidays)
            else:
                changes = _plan_anchored(rows, holidays)

            if not changes:
                continue

            plan_by_loan[lid] = changes
            total_row_changes += len(changes)

            # Collision check: two changed rows landing on same new date
            new_dates = [new for _, _, new in changes]
            seen = set()
            for d in new_dates:
                if d in seen:
                    collision_count += 1
                seen.add(d)

        self.stdout.write(f'Rows needing shift     : {total_row_changes} across {len(plan_by_loan)} loan(s)')

        if total_row_changes == 0:
            self.stdout.write(self.style.SUCCESS(
                '\nNo schedule rows fall on weekends or public holidays. Nothing to do.\n'
            ))
            return

        # ── 5. Print plan ─────────────────────────────────────────────────────
        for lid, changes in plan_by_loan.items():
            loan_obj = loan_by_id[lid]
            freq     = loan_obj.repayment_frequency
            mode_tag = 'cascade' if freq in DAILY_FREQUENCIES else 'shift'
            label    = (
                f'{loan_obj.loan_number} — '
                f'{loan_obj.client.get_full_name() if loan_obj.client else "?"}'
            )
            self.stdout.write(
                f'\nLOAN  {label}  '
                f'[{freq}, {mode_tag}]  '
                f'Branch: {loan_obj.branch.name if loan_obj.branch else "?"}'
            )

            # Collect new_dates for collision marking
            new_date_seen = set()
            collision_dates = set()
            for _, _, new in changes:
                if new in new_date_seen:
                    collision_dates.add(new)
                new_date_seen.add(new)

            for row, old, new in changes:
                day_old = DAY_NAMES[old.weekday()]
                day_new = DAY_NAMES[new.weekday()]
                if old in holiday_map:
                    reason = f'Holiday: {holiday_map[old]}'
                elif old.weekday() >= 5:
                    reason = 'Weekend'
                else:
                    reason = 'Cascaded from earlier shift'
                collision_flag = '  ⚠ COLLISION' if new in collision_dates else ''
                self.stdout.write(
                    f'  Row {row.installment_number:>3}: '
                    f'{old} ({day_old}, {reason}) '
                    f'→ {new} ({day_new})'
                    f'{collision_flag}'
                )

        # ── 6. Loan-level date fields ─────────────────────────────────────────
        loans_needing_update = []
        for ln in scope_loans:
            nrd_change = frd_change = None
            if ln.next_repayment_date and not is_business_day(ln.next_repayment_date, holidays):
                nrd_change = (ln.next_repayment_date,
                              next_business_day(ln.next_repayment_date, holidays))
            if ln.final_repayment_date and not is_business_day(ln.final_repayment_date, holidays):
                frd_change = (ln.final_repayment_date,
                              next_business_day(ln.final_repayment_date, holidays))
            if nrd_change or frd_change:
                loans_needing_update.append((ln, nrd_change, frd_change))

        if loans_needing_update:
            self.stdout.write(f'\nLOAN-LEVEL DATE FIELDS ({len(loans_needing_update)} loan(s))')
            for ln, nrd, frd in loans_needing_update:
                if nrd:
                    self.stdout.write(
                        f'  {ln.loan_number}  next_repayment_date  : {nrd[0]} → {nrd[1]}'
                    )
                if frd:
                    self.stdout.write(
                        f'  {ln.loan_number}  final_repayment_date : {frd[0]} → {frd[1]}'
                    )

        # ── 7. Summary ────────────────────────────────────────────────────────
        self.stdout.write(f'\n{"─" * 60}')
        self.stdout.write('SUMMARY')
        self.stdout.write(f'  Loans affected              : {len(plan_by_loan)}')
        self.stdout.write(f'  Schedule rows to update     : {total_row_changes}')
        self.stdout.write(f'  Loan-level date fields      : {len(loans_needing_update)}')
        if collision_count:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Date collisions (same new date, same loan) : {collision_count}'
            ))
            self.stdout.write(
                '    This can happen on daily loans when two consecutive holidays\n'
                '    land on the same next-business-day.  Amounts are unchanged;\n'
                '    the tracker will show both rows on that day.  Review manually.'
            )
        self.stdout.write('  AMOUNTS / BALANCES          : UNCHANGED')
        self.stdout.write('  paid / waived rows          : UNTOUCHED')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete — no changes written. Re-run with --commit to apply.\n'
            ))
            return

        # ── 8. Apply changes ──────────────────────────────────────────────────
        self.stdout.write('\nApplying changes ...')

        with db_transaction.atomic():
            # Flatten all (row, new_date) pairs and bulk-update in batches
            flat = [(row, new) for changes in plan_by_loan.values() for row, _, new in changes]
            updated_count = 0
            batch = []

            for row, new_date in flat:
                row.due_date = new_date
                batch.append(row)
                if len(batch) >= BATCH_SIZE:
                    LoanRepaymentSchedule.objects.bulk_update(batch, ['due_date'])
                    updated_count += len(batch)
                    self.stdout.write(f'  ... flushed {updated_count} rows')
                    batch = []

            if batch:
                LoanRepaymentSchedule.objects.bulk_update(batch, ['due_date'])
                updated_count += len(batch)

            self.stdout.write(f'  Schedule rows updated : {updated_count}')

            # Loan-level fields
            for ln, nrd, frd in loans_needing_update:
                update_fields = ['updated_at']
                if nrd:
                    ln.next_repayment_date = nrd[1]
                    update_fields.append('next_repayment_date')
                if frd:
                    ln.final_repayment_date = frd[1]
                    update_fields.append('final_repayment_date')
                ln.save(update_fields=update_fields)

            if loans_needing_update:
                self.stdout.write(
                    f'  Loan date fields updated : {len(loans_needing_update)}'
                )

        # ── 9. Verification ───────────────────────────────────────────────────
        verify_qs = LoanRepaymentSchedule.objects.filter(
            loan_id__in=scope_loan_ids,
            status__in=MUTABLE_STATUSES,
        )
        still_bad = [r for r in verify_qs if not is_business_day(r.due_date, holidays)]

        self.stdout.write(self.style.SUCCESS('\n✓ Shift applied successfully.'))
        self.stdout.write(f'  Rows shifted     : {updated_count}')
        if still_bad:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ Rows still on non-business days: {len(still_bad)}'
            ))
            for r in still_bad[:10]:
                self.stdout.write(
                    f'    Loan {r.loan_id}  Row {r.installment_number}  {r.due_date}'
                )
        else:
            self.stdout.write('  Verification     : 0 rows remain on non-business days ✓')
        self.stdout.write('')


# =============================================================================
# DATE PLANNING HELPERS
# =============================================================================

def _plan_anchored(rows, holidays):
    """
    Weekly / fortnightly / monthly / yearly loans.

    Each installment is an independent date anchor.  Only rows that land on a
    non-business day are shifted; all other rows are unchanged.  Subsequent
    rows are NOT cascaded.

    Returns list of (row, old_date, new_date) for changed rows only.
    """
    changes = []
    for row in rows:
        if not is_business_day(row.due_date, holidays):
            new_date = next_business_day(row.due_date, holidays)
            changes.append((row, row.due_date, new_date))
    return changes


def _plan_daily(rows, holidays):
    """
    Daily loans — cascade mode.

    Walks all mutable rows in installment order.  As soon as one row shifts,
    every subsequent row is regenerated as add_one_business_day(prev_new_date)
    so the one-installment-per-business-day invariant is maintained and the
    total loan duration is preserved.

    Returns list of (row, old_date, new_date) for ALL rows whose date changes.
    """
    changes = []
    prev_new_date = None   # tracks the last assigned new date in the cascade

    for row in rows:
        old = row.due_date

        if prev_new_date is None:
            # Cascade has not started yet.
            # Good days pass through unchanged; the first bad day triggers cascade.
            if not is_business_day(old, holidays):
                new = next_business_day(old, holidays)
                changes.append((row, old, new))
                prev_new_date = new
            # else: row is fine, prev_new_date stays None — we do NOT cascade
            # from here because there may be paid rows (gaps) before this point
            # and "add_one_biz(prev_mutable_row)" would produce the wrong anchor.
        else:
            # Cascade is running: every subsequent row must be exactly one
            # business day after the last placed row.
            new = add_one_business_day(prev_new_date, holidays)
            if new != old:
                changes.append((row, old, new))
            prev_new_date = new   # keep tracking even when new == old

    return changes
