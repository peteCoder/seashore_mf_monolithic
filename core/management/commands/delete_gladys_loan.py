"""
Management command: delete_gladys_loan
======================================

Hard-deletes Gladys Ayo's Med Loan application that is stuck at
'Pending Fee Payment' with only 1 of 2 guarantors added.

No transactions or journal entries have been created for this loan.

Records deleted (in FK order)
------------------------------
  core_guarantor f6a264e6-b267-4e54-ba17-bcc726a14c26  (linked to loan)
  core_loan      c6361711-573b-4f0a-82c1-78a95ac0ca92  (LN20260416160706724451)

Records NOT touched
-------------------
  Client 8bccceba-b2b0-4ad9-9dad-6884015ffb97 (Gladys Ayo) and all her
  other transactions / journal entries remain untouched.

Usage
-----
  python manage.py delete_gladys_loan --dry-run
  python manage.py delete_gladys_loan --commit
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction as db_transaction


LOAN_ID       = 'c6361711-573b-4f0a-82c1-78a95ac0ca92'
LOAN_NUMBER   = 'LN20260416160706724451'
CLIENT_ID     = '8bccceba-b2b0-4ad9-9dad-6884015ffb97'
GUARANTOR_ID  = 'f6a264e6-b267-4e54-ba17-bcc726a14c26'


class Command(BaseCommand):
    help = 'Hard-delete Gladys Ayo pending loan LN20260416160706724451'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true')
        group.add_argument('--commit',  action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT MODE'
        self.stdout.write(self.style.WARNING(f'\n=== delete_gladys_loan [{mode}] ===\n'))

        with connection.cursor() as cur:
            # Verify the loan exists
            cur.execute('SELECT loan_number, status, client_id FROM core_loan WHERE id = %s', [LOAN_ID])
            row = cur.fetchone()
            if not row:
                raise CommandError(f'Loan {LOAN_ID} not found (already deleted?).')
            loan_number, status, client_id = row
            self.stdout.write(f'LOAN')
            self.stdout.write(f'  id          : {LOAN_ID}')
            self.stdout.write(f'  loan_number : {loan_number}')
            self.stdout.write(f'  status      : {status}  (must be pending_fees)')
            self.stdout.write(f'  client_id   : {client_id}  (will NOT be deleted)')
            if str(client_id) != CLIENT_ID:
                raise CommandError(
                    f'Client mismatch: expected {CLIENT_ID}, got {client_id}. Aborting.'
                )
            if status != 'pending_fees':
                raise CommandError(
                    f'Loan status is {status!r}, expected pending_fees. '
                    f'Aborting — do not delete a disbursed or repaid loan this way.'
                )

            # Verify no transactions linked to loan
            cur.execute(
                'SELECT COUNT(*) FROM core_transaction WHERE loan_id = %s', [LOAN_ID]
            )
            txn_count = cur.fetchone()[0]
            self.stdout.write(f'  Linked transactions  : {txn_count}  (must be 0)')
            if txn_count != 0:
                raise CommandError(f'Found {txn_count} transaction(s) linked to this loan. Aborting.')

            # Verify no journal entries linked to loan
            cur.execute(
                'SELECT COUNT(*) FROM core_journalentry WHERE loan_id = %s', [LOAN_ID]
            )
            je_count = cur.fetchone()[0]
            self.stdout.write(f'  Linked journal entries: {je_count}  (must be 0)')
            if je_count != 0:
                raise CommandError(f'Found {je_count} journal entry/entries linked to this loan. Aborting.')

            # Verify no repayment schedule rows
            cur.execute(
                'SELECT COUNT(*) FROM core_loanrepaymentschedule WHERE loan_id = %s', [LOAN_ID]
            )
            sched_count = cur.fetchone()[0]
            self.stdout.write(f'  Repayment schedule rows: {sched_count}  (must be 0)')
            if sched_count != 0:
                raise CommandError(f'Found {sched_count} schedule row(s). Aborting.')

            # Verify the guarantor
            cur.execute(
                'SELECT id, name FROM core_guarantor WHERE loan_id = %s', [LOAN_ID]
            )
            guarantors = cur.fetchall()
            self.stdout.write(f'\nGUARANTORS ({len(guarantors)}) - will be DELETED:')
            for g_id, g_name in guarantors:
                self.stdout.write(f'  id={g_id}  name={g_name}')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\nDry run complete. Re-run with --commit to apply.\n'))
            return

        # Hard delete atomically
        with db_transaction.atomic():
            with connection.cursor() as cur:
                # 1. Delete guarantors (FK child)
                cur.execute('DELETE FROM core_guarantor WHERE loan_id = %s', [LOAN_ID])
                g_deleted = cur.rowcount
                self.stdout.write(f'\nDeleted {g_deleted} guarantor row(s).')

                # 2. Hard-delete the loan itself
                cur.execute('DELETE FROM core_loan WHERE id = %s', [LOAN_ID])
                l_deleted = cur.rowcount
                self.stdout.write(f'Deleted {l_deleted} loan row(s).')

            # Verify nothing remains
            with connection.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM core_loan WHERE id = %s', [LOAN_ID])
                remaining = cur.fetchone()[0]
                if remaining != 0:
                    raise CommandError('Loan row still present after delete. Rolling back.')

        self.stdout.write(self.style.SUCCESS('\nHard deletion complete.\n'))
        self.stdout.write('Summary:')
        self.stdout.write(f'  core_guarantor {GUARANTOR_ID} - DELETED')
        self.stdout.write(f'  core_loan      {LOAN_ID} ({LOAN_NUMBER}) - DELETED')
        self.stdout.write(f'  Client {CLIENT_ID} (Gladys Ayo) - UNTOUCHED')
