"""
Management command: audit_account
===================================

Prints every journal entry line that has ever touched a given GL account,
ordered by transaction_date, with a running balance.  Useful for diagnosing
why an account balance looks wrong.

Usage:
    python manage.py audit_account <gl_code>
    python manage.py audit_account <gl_code> --from 2026-01-01 --to 2026-03-28
    python manage.py audit_account <gl_code> --branch <branch-id>

Examples:
    python manage.py audit_account 1010
    python manage.py audit_account 1010 --from 2026-03-01 --to 2026-03-28
"""

import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum


class Command(BaseCommand):
    help = "Audit every journal entry line for a GL account with a running balance."

    def add_arguments(self, parser):
        parser.add_argument(
            'gl_code',
            type=str,
            help='GL code of the account to audit (e.g. 1010).',
        )
        parser.add_argument(
            '--from',
            dest='date_from',
            type=str,
            default=None,
            help='Start date YYYY-MM-DD (inclusive). Defaults to beginning of time.',
        )
        parser.add_argument(
            '--to',
            dest='date_to',
            type=str,
            default=None,
            help='End date YYYY-MM-DD (inclusive). Defaults to today.',
        )
        parser.add_argument(
            '--branch',
            dest='branch_id',
            type=str,
            default=None,
            help='Filter by branch UUID (optional).',
        )

    def handle(self, *args, **options):
        from core.models import JournalEntryLine, ChartOfAccounts

        gl_code    = options['gl_code']
        date_from  = options['date_from']
        date_to    = options['date_to']
        branch_id  = options['branch_id']

        # ── Resolve account ───────────────────────────────────────────────────
        try:
            account = ChartOfAccounts.objects.get(gl_code=gl_code)
        except ChartOfAccounts.DoesNotExist:
            raise CommandError(f"No ChartOfAccounts found with GL code: {gl_code}")

        self.stdout.write(
            f"\nAccount: {account.gl_code} — {account.account_name}"
            f"\nType:    {account.account_type}"
            f"\nNormal balance: {getattr(account.account_type, 'normal_balance', 'debit')}"
            "\n" + "=" * 80
        )

        # ── Parse dates ───────────────────────────────────────────────────────
        try:
            df = datetime.date.fromisoformat(date_from) if date_from else None
            dt = datetime.date.fromisoformat(date_to)   if date_to   else datetime.date.today()
        except ValueError as e:
            raise CommandError(f"Invalid date: {e}")

        # ── Build queryset ────────────────────────────────────────────────────
        qs = JournalEntryLine.objects.filter(
            account=account,
            journal_entry__status='posted',
            journal_entry__transaction_date__lte=dt,
        ).select_related(
            'journal_entry', 'journal_entry__branch'
        ).order_by(
            'journal_entry__transaction_date',
            'journal_entry__created_at',
            'id',
        )

        if df:
            qs = qs.filter(journal_entry__transaction_date__gte=df)

        if branch_id:
            qs = qs.filter(journal_entry__branch__id=branch_id)

        # ── Totals ────────────────────────────────────────────────────────────
        agg = qs.aggregate(
            total_debit=Sum('debit_amount'),
            total_credit=Sum('credit_amount'),
        )
        total_debit  = agg['total_debit']  or Decimal('0')
        total_credit = agg['total_credit'] or Decimal('0')

        if df:
            self.stdout.write(f"Period:  {df}  →  {dt}")
        else:
            self.stdout.write(f"Period:  (all time)  →  {dt}")
        self.stdout.write(f"Lines found: {qs.count()}\n")

        # ── Header ────────────────────────────────────────────────────────────
        self.stdout.write(
            f"{'Date':<12} {'Journal':<22} {'Type':<22} {'Description':<35} "
            f"{'Debit':>12} {'Credit':>12} {'Running Bal':>14}"
        )
        self.stdout.write("-" * 135)

        running = Decimal('0')
        normal_balance = getattr(account.account_type, 'normal_balance', 'debit')

        for line in qs:
            je   = line.journal_entry
            dr   = line.debit_amount  or Decimal('0')
            cr   = line.credit_amount or Decimal('0')

            if normal_balance == 'debit':
                running += dr - cr
            else:
                running += cr - dr

            desc = (line.description or je.description or '')[:34]
            date_str   = str(je.transaction_date)
            jnum       = (je.journal_number or '')[:21]
            etype      = (je.get_entry_type_display() if hasattr(je, 'get_entry_type_display') else je.entry_type or '')[:21]

            dr_str  = f"₦{dr:,.2f}"  if dr  else ''
            cr_str  = f"₦{cr:,.2f}"  if cr  else ''
            bal_str = f"₦{running:,.2f}"

            self.stdout.write(
                f"{date_str:<12} {jnum:<22} {etype:<22} {desc:<35} "
                f"{dr_str:>12} {cr_str:>12} {bal_str:>14}"
            )

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write("-" * 135)
        net = total_debit - total_credit
        self.stdout.write(
            f"{'TOTALS':<12} {'':22} {'':22} {'':35} "
            f"{'₦'+f'{total_debit:,.2f}':>12} {'₦'+f'{total_credit:,.2f}':>12} "
            f"{'₦'+f'{net:,.2f}':>14}"
        )

        # ── Date-grouped summary ──────────────────────────────────────────────
        self.stdout.write("\n\nSummary by date:")
        self.stdout.write(f"{'Date':<12} {'Lines':>6} {'Debits':>14} {'Credits':>14} {'Net':>14}")
        self.stdout.write("-" * 65)

        from django.db.models import Count
        date_summary = (
            qs.values('journal_entry__transaction_date')
            .annotate(
                lines=Count('id'),
                debits=Sum('debit_amount'),
                credits=Sum('credit_amount'),
            )
            .order_by('journal_entry__transaction_date')
        )

        running2 = Decimal('0')
        for row in date_summary:
            d  = row['journal_entry__transaction_date']
            dr = row['debits']  or Decimal('0')
            cr = row['credits'] or Decimal('0')
            if normal_balance == 'debit':
                running2 += dr - cr
            else:
                running2 += cr - dr
            n  = row['lines']
            self.stdout.write(
                f"{str(d):<12} {n:>6} {'₦'+f'{dr:,.2f}':>14} {'₦'+f'{cr:,.2f}':>14} "
                f"{'₦'+f'{running2:,.2f}':>14}"
            )

        self.stdout.write(
            f"\nFinal balance of {account.gl_code} — {account.account_name}: "
            + self.style.SUCCESS(f"₦{running2:,.2f}")
            + "\n"
        )
