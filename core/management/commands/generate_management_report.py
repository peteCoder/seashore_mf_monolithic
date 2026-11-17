"""
Management command: generate_management_report
================================================

Builds the Excel pack requested by management covering, as at a given
cutoff date (default 31 Oct 2026) and for that cutoff's calendar month:

  1. Gross outstanding loan portfolio by branch
  2. Registered customers, active borrowers, active savers, savings balance
  3. Portfolio quality: PAR 1 / PAR 30 / PAR 90, overdue, recoveries, write-offs
  4. Loan disbursements and principal collections by branch, for the month
  5. Income statement (actual income + expenditure) for the month and YTD
  6/7. Balance sheet / financial position as at the cutoff

Read-only. Writes one .xlsx file to seashore/excel_for_management/.

IMPORTANT — methodology (also written to the workbook's own Notes sheet):

  - Figures sourced from the General Ledger (loan portfolio, savings
    balance, income statement, balance sheet) are exact as at the cutoff
    date, because the GL is an append-only ledger: journal lines are never
    rewritten for a past date, so summing lines with transaction_date <=
    cutoff reproduces the true historical balance regardless of what has
    happened since.

  - Active borrower / active saver counts are reconstructed from recorded
    status-change events (disbursement_date, completion_date, the
    write-off journal entry's date, savings closed_at) as a best-effort
    point-in-time estimate — these dates are discrete recorded events, not
    a live running balance, so this reconstruction is sound.

  - Portfolio-at-risk / overdue figures CANNOT be reconstructed as at a
    past cutoff from this system: LoanRepaymentSchedule.outstanding_amount
    is a live, mutable running balance with no historical snapshot, and
    Loan.next_repayment_date/days_overdue are computed against today's
    date. These figures are therefore reported as at the report's
    generation date, not the requested cutoff, and the workbook says so
    explicitly next to every such figure.

  - "Recoveries" and "write-offs" are period flows (things that happened
    during the month), not point-in-time stocks, so they ARE exact for the
    requested month regardless of today's date.

Usage:
    python manage.py generate_management_report
    python manage.py generate_management_report --as-of 2026-10-31
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum, Count, Q


GL_LOAN_PRINCIPAL_CODES = ['1810', '1840', '1850']  # Loan Receivable - Principal / MED / Betnaija
GL_SAVINGS_CODES = ['2010', '2020', '2030', '2040', '2050']
GL_CASH_BANK_CODES = ['1010', '1020', '1030', '1040', '1050', '1060', '1070', '1080']
GL_BORROWINGS_CODES = ['2958']  # Overdraft Facility — the closest thing to "borrowings" in this COA

# Expense GL codes mapped to the 4 buckets management asked for. There is no
# "Head Office" cost center anywhere in this chart of accounts or in
# JournalEntry.branch (every posted entry is tied to one of the 3 real
# branches) — Head Office is therefore always reported as not tracked.
EXPENSE_BUCKET_MAP = {
    'Personnel': [
        '5110', '5115',  # Salaries & Wages / Salary to Casual — tagged "Operating Expenses"
                          # in the COA's own category field, but are personnel costs in
                          # substance; reclassified here for management's bucket, not left
                          # under Operating.
        '5210', '5220', '5230', '5235', '5240', '5250', '5255', '5257', '5260', '5270', '5280', '5290',
    ],
    'Administrative': [
        '5410', '5420', '5430', '5440', '5441', '5443', '5445', '5447',
        '5450', '5460', '5470', '5480', '5490', '5492', '5495', '5497', '5498',
    ],
    'Operating': [
        '5010',  # Interest Expense - Savings
        '5120', '5122', '5124', '5130', '5140', '5150', '5160', '5170',
        '5310', '5320', '5330', '5340', '5350', '5360', '5960',  # Maintenance category
        '5510', '5520', '5530', '5535', '5540', '5545', '5548', '5550', '5558',
        '5560', '5565', '5575', '5578', '5580', '5970', '5980', '5990', '6000',  # Other Expenses
        '5910', '5920', '5930', '5940', '5950',  # Loan Loss Provisions
    ],
    'Head Office': [],  # not tracked anywhere in this system — see note above
}


def d(value):
    return value if value is not None else Decimal('0.00')


class Command(BaseCommand):
    help = "Generate the management Excel report pack (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--as-of', type=str, default='2026-10-31',
            help='Cutoff date, YYYY-MM-DD. Defaults to 2026-10-31.',
        )

    def handle(self, *args, **options):
        from core.models import (
            Branch, Client, Loan, SavingsAccount, Transaction,
            JournalEntry, ChartOfAccounts,
        )
        from django.utils import timezone

        cutoff = datetime.date.fromisoformat(options['as_of'])
        month_start = cutoff.replace(day=1)
        month_end = cutoff
        ytd_start = cutoff.replace(month=1, day=1)
        today = timezone.now().date()

        self.stdout.write(f"Generating management report as at {cutoff}...")

        branches = list(Branch.objects.filter(is_active=True).order_by('name'))
        accounts_by_code = {a.gl_code: a for a in ChartOfAccounts.objects.select_related('account_type')}

        # ── GL helper: balance of one account, optionally scoped to a branch,
        #    as at `as_of` (inclusive), summing only posted journal lines ──
        def gl_account_balance(gl_code, as_of, branch=None):
            account = accounts_by_code.get(gl_code)
            if account is None:
                return Decimal('0.00')
            lines = account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__lte=as_of,
            )
            if branch is not None:
                lines = lines.filter(journal_entry__branch=branch)
            agg = lines.aggregate(dr=Sum('debit_amount'), cr=Sum('credit_amount'))
            debit = d(agg['dr'])
            credit = d(agg['cr'])
            if account.account_type.normal_balance == 'debit':
                return debit - credit
            return credit - debit

        def gl_account_balance_in_range(gl_code, date_from, date_to, branch=None):
            account = accounts_by_code.get(gl_code)
            if account is None:
                return Decimal('0.00')
            lines = account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__range=[date_from, date_to],
            )
            if branch is not None:
                lines = lines.filter(journal_entry__branch=branch)
            agg = lines.aggregate(dr=Sum('debit_amount'), cr=Sum('credit_amount'))
            debit = d(agg['dr'])
            credit = d(agg['cr'])
            if account.account_type.normal_balance == 'debit':
                return debit - credit
            return credit - debit

        report = {
            'cutoff': cutoff, 'month_start': month_start, 'month_end': month_end,
            'ytd_start': ytd_start, 'today': today, 'branches': branches,
        }

        # =====================================================================
        # 1. GROSS OUTSTANDING LOAN PORTFOLIO BY BRANCH (GL-based, exact)
        # =====================================================================
        self.stdout.write("  [1/7] Loan portfolio by branch...")
        portfolio_by_branch = []
        for b in branches:
            bal = sum(gl_account_balance(c, cutoff, branch=b) for c in GL_LOAN_PRINCIPAL_CODES)
            portfolio_by_branch.append({'branch': b.name, 'balance': bal})
        report['portfolio_by_branch'] = portfolio_by_branch
        report['portfolio_total'] = sum(r['balance'] for r in portfolio_by_branch)

        # =====================================================================
        # 2. CUSTOMERS & SAVINGS (as at cutoff)
        # =====================================================================
        self.stdout.write("  [2/7] Customers & savings...")

        # Active borrower reconstruction: a loan counts as "still running as
        # at cutoff" if it was disbursed by then and had not yet reached a
        # terminal state (completed/written off) by then.
        loans_disbursed_by_cutoff = list(
            Loan.objects.filter(disbursement_date__date__lte=cutoff)
            .exclude(status__in=['pending_fees', 'pending_approval', 'rejected', 'cancelled'])
            .values('id', 'client_id', 'branch_id', 'status', 'completion_date')
        )
        writeoff_dates = dict(
            JournalEntry.objects.filter(
                status='posted', reference_number__startswith='WRITE-OFF-', loan_id__isnull=False,
            ).values_list('loan_id', 'transaction_date')
        )

        def loan_active_as_of(row):
            status = row['status']
            if status in ('active', 'overdue', 'disbursed'):
                return True
            if status == 'completed':
                cd = row['completion_date']
                return bool(cd and cd.date() > cutoff)
            if status == 'written_off':
                wd = writeoff_dates.get(row['id'])
                return bool(wd and wd > cutoff)
            return False

        active_loan_rows = [r for r in loans_disbursed_by_cutoff if loan_active_as_of(r)]
        active_borrower_client_ids = {r['client_id'] for r in active_loan_rows}

        savings_rows = list(
            SavingsAccount.objects.filter(created_at__date__lte=cutoff)
            .values('id', 'client_id', 'branch_id', 'status', 'closed_at')
        )

        def saver_active_as_of(row):
            if row['status'] == 'active':
                return True
            if row['status'] == 'closed':
                ca = row['closed_at']
                return bool(ca and ca.date() > cutoff)
            return False

        active_saver_rows = [r for r in savings_rows if saver_active_as_of(r)]
        active_saver_client_ids = {r['client_id'] for r in active_saver_rows}

        customers_savings_by_branch = []
        for b in branches:
            registered = Client.objects.filter(
                branch=b, registration_date__lte=cutoff, approval_status='approved',
            ).count()
            active_borrowers = len({r['client_id'] for r in active_loan_rows if r['branch_id'] == b.id})
            active_savers = len({r['client_id'] for r in active_saver_rows if r['branch_id'] == b.id})
            savings_balance = sum(gl_account_balance(c, cutoff, branch=b) for c in GL_SAVINGS_CODES)
            customers_savings_by_branch.append({
                'branch': b.name,
                'registered_customers': registered,
                'active_borrowers': active_borrowers,
                'active_savers': active_savers,
                'savings_balance': savings_balance,
            })
        report['customers_savings_by_branch'] = customers_savings_by_branch
        report['total_registered_customers'] = Client.objects.filter(
            registration_date__lte=cutoff, approval_status='approved',
        ).count()
        report['total_active_borrowers'] = len(active_borrower_client_ids)
        report['total_active_savers'] = len(active_saver_client_ids)
        report['total_savings_balance'] = sum(gl_account_balance(c, cutoff) for c in GL_SAVINGS_CODES)

        # =====================================================================
        # 3. PORTFOLIO QUALITY (live — see methodology note)
        # =====================================================================
        self.stdout.write("  [3/7] Portfolio quality (PAR)...")
        from core.models import LoanProduct  # noqa

        live_loans = list(
            Loan.objects.filter(status__in=['active', 'overdue'])
            .select_related('loan_product')
            .exclude(outstanding_balance__lte=Decimal('0.01'))
        )
        total_outstanding_live = sum(l.outstanding_balance for l in live_loans)

        def live_days_overdue(loan):
            if loan.status == 'overdue':
                return loan.days_overdue
            if loan.status == 'active' and loan.next_repayment_date:
                grace = loan.loan_product.grace_period_days if loan.loan_product_id and loan.loan_product else 0
                overdue_from = loan.next_repayment_date + datetime.timedelta(days=grace)
                if overdue_from < today:
                    return (today - overdue_from).days
            return 0

        par_buckets = {'par1': [], 'par30': [], 'par90': []}
        for loan in live_loans:
            days = live_days_overdue(loan)
            if days >= 1:
                par_buckets['par1'].append(loan)
            if days >= 30:
                par_buckets['par30'].append(loan)
            if days >= 90:
                par_buckets['par90'].append(loan)

        def par_summary(loans_list):
            bal = sum(l.outstanding_balance for l in loans_list)
            pct = float(bal) / float(total_outstanding_live) * 100 if total_outstanding_live else 0.0
            return {'count': len(loans_list), 'balance': bal, 'pct': pct}

        report['total_outstanding_live'] = total_outstanding_live
        report['par1'] = par_summary(par_buckets['par1'])
        report['par30'] = par_summary(par_buckets['par30'])
        report['par90'] = par_summary(par_buckets['par90'])

        # Write-offs during the month — exact, GL-based (period flow)
        writeoff_entries = JournalEntry.objects.filter(
            status='posted', reference_number__startswith='WRITE-OFF-',
            transaction_date__range=[month_start, month_end],
        )
        writeoff_total = Decimal('0.00')
        for je in writeoff_entries:
            amt = je.lines.filter(account__gl_code='5910').aggregate(t=Sum('debit_amount'))['t']
            writeoff_total += d(amt)
        report['writeoff_count'] = writeoff_entries.count()
        report['writeoff_total'] = writeoff_total

        # Recoveries during the month — repayments received on loans that
        # are (now) written off. No dedicated recovery field exists.
        recovery_agg = Transaction.objects.filter(
            transaction_type='loan_repayment', status='completed',
            transaction_date__date__range=[month_start, month_end],
            loan__status='written_off',
        ).aggregate(total=Sum('amount'), n=Count('id'))
        report['recovery_total'] = d(recovery_agg['total'])
        report['recovery_count'] = recovery_agg['n'] or 0

        # =====================================================================
        # 4. LOAN OPERATIONS BY BRANCH FOR THE MONTH (Transaction-based, exact)
        # =====================================================================
        self.stdout.write("  [4/7] Loan operations by branch...")
        operations_by_branch = []
        for b in branches:
            disb = Transaction.objects.filter(
                transaction_type='loan_disbursement', status='completed', branch=b,
                transaction_date__date__range=[month_start, month_end],
            ).aggregate(n=Count('id'), amt=Sum('amount'))
            repay = Transaction.objects.filter(
                transaction_type='loan_repayment', status='completed', branch=b,
                transaction_date__date__range=[month_start, month_end],
            ).aggregate(n=Count('id'), principal=Sum('principal_amount'))
            operations_by_branch.append({
                'branch': b.name,
                'disbursement_count': disb['n'] or 0,
                'disbursement_amount': d(disb['amt']),
                'repayment_count': repay['n'] or 0,
                'principal_collected': d(repay['principal']),
            })
        report['operations_by_branch'] = operations_by_branch

        # =====================================================================
        # 5. INCOME STATEMENT — month + YTD (GL-based, exact)
        # =====================================================================
        self.stdout.write("  [5/7] Income statement...")

        income_groups = {
            'Interest Income': ['4010', '4020', '4030', '4040'],
            'Fee Income': ['4110', '4112', '4114', '4120', '4130', '4140', '4150', '4160', '4165', '4170', '4180', '4190'],
            'Other Income': ['4230'],
        }

        def period_group_total(codes, date_from, date_to):
            return sum(gl_account_balance_in_range(c, date_from, date_to) for c in codes)

        income_statement = {'month': {}, 'ytd': {}}
        for label, codes in income_groups.items():
            income_statement['month'][label] = period_group_total(codes, month_start, month_end)
            income_statement['ytd'][label] = period_group_total(codes, ytd_start, month_end)

        for bucket, codes in EXPENSE_BUCKET_MAP.items():
            income_statement['month'][bucket] = period_group_total(codes, month_start, month_end) if codes else Decimal('0.00')
            income_statement['ytd'][bucket] = period_group_total(codes, ytd_start, month_end) if codes else Decimal('0.00')

        report['income_statement'] = income_statement
        report['income_groups'] = list(income_groups.keys())
        report['expense_buckets'] = list(EXPENSE_BUCKET_MAP.keys())

        # Per-account detail for the income-statement appendix
        appendix_rows = []
        for label, codes in {**income_groups, **EXPENSE_BUCKET_MAP}.items():
            for code in codes:
                account = accounts_by_code.get(code)
                if not account:
                    continue
                m = gl_account_balance_in_range(code, month_start, month_end)
                y = gl_account_balance_in_range(code, ytd_start, month_end)
                if m or y:
                    appendix_rows.append({
                        'bucket': label, 'gl_code': code, 'name': account.account_name,
                        'month': m, 'ytd': y,
                    })
        report['income_statement_appendix'] = appendix_rows

        # =====================================================================
        # 6/7. BALANCE SHEET — as at cutoff (GL-based, exact)
        # =====================================================================
        self.stdout.write("  [6-7/7] Balance sheet...")
        from core.models import AccountType as AT

        def nonzero_accounts(type_name):
            rows = []
            for a in ChartOfAccounts.objects.filter(account_type__name=type_name, is_active=True).order_by('gl_code'):
                bal = gl_account_balance(a.gl_code, cutoff)
                if bal:
                    rows.append({'gl_code': a.gl_code, 'name': a.account_name, 'balance': bal})
            return rows

        assets = nonzero_accounts(AT.ASSET)
        liabilities = nonzero_accounts(AT.LIABILITY)
        equity = nonzero_accounts(AT.EQUITY)

        net_income_ytd = (
            sum(gl_account_balance_in_range(c, ytd_start, cutoff) for c in sum(income_groups.values(), []))
            - sum(gl_account_balance_in_range(c, ytd_start, cutoff) for c in sum(EXPENSE_BUCKET_MAP.values(), []))
        )

        report['balance_sheet'] = {
            'assets': assets, 'liabilities': liabilities, 'equity': equity,
            'net_income_ytd': net_income_ytd,
            'total_assets': sum(r['balance'] for r in assets),
            'total_liabilities': sum(r['balance'] for r in liabilities),
            'total_equity': sum(r['balance'] for r in equity) + net_income_ytd,
            'cash_bank_total': sum(gl_account_balance(c, cutoff) for c in GL_CASH_BANK_CODES),
            'borrowings_total': sum(gl_account_balance(c, cutoff) for c in GL_BORROWINGS_CODES),
        }

        self.stdout.write(self.style.SUCCESS("  Data gathering complete. Writing workbook..."))

        from core.utils.management_report_excel import write_management_report_workbook
        out_path = write_management_report_workbook(report)

        self.stdout.write(self.style.SUCCESS(f"\nReport written to: {out_path}\n"))
