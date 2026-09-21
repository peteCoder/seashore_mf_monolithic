"""
Management command: retire_form_and_maintenance_fees
=======================================================

Applies the 2026-09 management decision on loan product fees to all
existing LoanProduct rows:

  - Loan Form Fee and Loan Maintenance Fee are retired: disable them on
    every product. (LoanProduct.calculate_fees() already ignores these
    fields unconditionally now — this is housekeeping so the product
    records themselves reflect reality, not a behavioural change.)
  - Admin Fee is now tiered by loan amount (see ADMIN_FEE_BRACKETS in
    core/models/all_models.py) instead of a fixed per-product amount.
    Every product's admin_fee_enabled is turned on so the tiered fee
    applies going forward.

This only changes LoanProduct configuration rows. It does NOT touch any
existing Loan record — loans already created keep the fee amounts that
were snapshotted onto them at creation time (loan.loan_form_fee,
loan.loan_maintenance_fee, loan.admin_fee, loan.total_upfront_fees).
Only loans created from this point forward will compute fees using the
new tiered admin-fee logic and zero form/maintenance fee.

The old *_amount fields (loan_form_fee_amount, loan_maintenance_fee_amount,
admin_fee_amount) are left untouched in the database for historical
reference; they are simply no longer read by calculate_fees() or exposed
in the product form.

Usage
-----
  python manage.py retire_form_and_maintenance_fees --dry-run
  python manage.py retire_form_and_maintenance_fees --commit
"""

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction


class Command(BaseCommand):
    help = 'Disable Loan Form Fee / Loan Maintenance Fee and enable tiered Admin Fee on all loan products'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--dry-run', action='store_true',
                            help='Show what will change without writing to the DB')
        group.add_argument('--commit', action='store_true',
                            help='Apply the changes')

    def handle(self, *args, **options):
        from core.models import LoanProduct

        dry_run = options['dry_run']
        mode = 'DRY RUN' if dry_run else 'COMMIT'
        self.stdout.write(self.style.WARNING(
            f'\n=== retire_form_and_maintenance_fees [{mode}] ===\n'
        ))

        products = list(LoanProduct.all_objects.all().order_by('code'))
        self.stdout.write(f'Found {len(products)} loan product(s)\n')

        changes = []
        for p in products:
            before = {
                'loan_form_fee_enabled': p.loan_form_fee_enabled,
                'loan_maintenance_fee_enabled': p.loan_maintenance_fee_enabled,
                'admin_fee_enabled': p.admin_fee_enabled,
            }
            after = {
                'loan_form_fee_enabled': False,
                'loan_maintenance_fee_enabled': False,
                'admin_fee_enabled': True,
            }
            if before != after:
                changes.append((p, before, after))

        for p, before, after in changes:
            self.stdout.write(f'  {p.code} - {p.name}')
            for field in ('loan_form_fee_enabled', 'loan_maintenance_fee_enabled', 'admin_fee_enabled'):
                if before[field] != after[field]:
                    self.stdout.write(f'    {field}: {before[field]} -> {after[field]}')

        if not changes:
            self.stdout.write('  (no products need changes -- already in the target state)')

        self.stdout.write(f'\nWILL UPDATE {len(changes)} of {len(products)} product(s)')

        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nDry run complete - no changes written. Re-run with --commit to apply.\n'
            ))
            return

        with db_transaction.atomic():
            for p, before, after in changes:
                p.loan_form_fee_enabled = after['loan_form_fee_enabled']
                p.loan_maintenance_fee_enabled = after['loan_maintenance_fee_enabled']
                p.admin_fee_enabled = after['admin_fee_enabled']
                p.save(update_fields=[
                    'loan_form_fee_enabled', 'loan_maintenance_fee_enabled',
                    'admin_fee_enabled', 'updated_at',
                ])
                self.stdout.write(f'  Updated {p.code}')

        self.stdout.write(self.style.SUCCESS(f'\n{len(changes)} loan product(s) updated.\n'))

        self.stdout.write('FINAL STATE')
        for p in LoanProduct.all_objects.all().order_by('code'):
            self.stdout.write(
                f'  {p.code}: form_fee_enabled={p.loan_form_fee_enabled}  '
                f'maintenance_fee_enabled={p.loan_maintenance_fee_enabled}  '
                f'admin_fee_enabled={p.admin_fee_enabled}'
            )
