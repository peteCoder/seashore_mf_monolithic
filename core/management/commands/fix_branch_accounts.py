"""
Management command: fix_branch_accounts
=========================================

Re-aligns savings accounts and loans so they belong to the same branch
as their client.  Use this to fix clients that were transferred to a new
branch before the assignment system was updated to cascade the transfer.

Usage:
    # Preview what will change (safe — no writes)
    python manage.py fix_branch_accounts --branch "Upper Ekenhuan" --dry-run

    # Apply the fix
    python manage.py fix_branch_accounts --branch "Upper Ekenhuan"

    # Fix ALL branches at once (any account/loan whose branch != client branch)
    python manage.py fix_branch_accounts --all
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Sync savings account and loan branches to match their client's branch."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '--branch',
            metavar='BRANCH_NAME',
            help='Fix accounts/loans for clients currently in this branch.',
        )
        group.add_argument(
            '--all',
            action='store_true',
            dest='fix_all',
            help='Fix every mismatched account/loan across all branches.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Preview changes without writing anything.',
        )

    def handle(self, *args, **options):
        from core.models import Branch, Client, SavingsAccount, Loan

        dry_run = options['dry_run']
        fix_all = options['fix_all']
        branch_name = options.get('branch')

        if fix_all:
            clients = Client.objects.filter(is_active=True).select_related('branch')
        else:
            try:
                branch = Branch.objects.get(name__iexact=branch_name)
            except Branch.DoesNotExist:
                raise CommandError(f'Branch "{branch_name}" not found. Check the exact name.')
            clients = Client.objects.filter(branch=branch, is_active=True).select_related('branch')

        total_savings_fixed = 0
        total_loans_fixed = 0

        with transaction.atomic():
            for client in clients:
                target_branch = client.branch

                # Savings accounts whose branch differs from the client's branch
                mismatched_savings = SavingsAccount.objects.filter(
                    client=client
                ).exclude(branch=target_branch)

                if mismatched_savings.exists():
                    count = mismatched_savings.count()
                    for acct in mismatched_savings.select_related('branch'):
                        self.stdout.write(
                            f'  Savings {acct.account_number}: '
                            f'{acct.branch.name} → {target_branch.name}'
                        )
                    if not dry_run:
                        mismatched_savings.update(branch=target_branch)
                    total_savings_fixed += count

                # Loans whose branch differs from the client's branch
                mismatched_loans = Loan.objects.filter(
                    client=client
                ).exclude(branch=target_branch)

                if mismatched_loans.exists():
                    count = mismatched_loans.count()
                    for loan in mismatched_loans.select_related('branch'):
                        self.stdout.write(
                            f'  Loan {loan.loan_number}: '
                            f'{loan.branch.name} → {target_branch.name}'
                        )
                    if not dry_run:
                        mismatched_loans.update(branch=target_branch)
                    total_loans_fixed += count

            if dry_run:
                transaction.set_rollback(True)

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done — '
            f'{total_savings_fixed} savings account(s) and '
            f'{total_loans_fixed} loan(s) would be updated.'
            if dry_run else
            f'Done — '
            f'{total_savings_fixed} savings account(s) and '
            f'{total_loans_fixed} loan(s) updated.'
        ))
