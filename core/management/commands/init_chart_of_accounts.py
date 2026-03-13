"""
Management command to initialize the Chart of Accounts for Seashore Microfinance

This command creates:
- Account Types (Asset, Liability, Equity, Income, Expense)
- Account Categories (sub-classifications)
- Chart of Accounts entries (GL accounts)

Usage:      
    python manage.py init_chart_of_accounts
    python manage.py init_chart_of_accounts --reset  # Delete existing and recreate
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import AccountType, AccountCategory, ChartOfAccounts


class Command(BaseCommand):
    help = 'Initialize the Chart of Accounts with standard microfinance accounts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete existing accounts and recreate from scratch',
        )

    def handle(self, *args, **options):
        reset = options['reset']

        if reset:
            self.stdout.write(self.style.WARNING('Deleting existing accounts...'))
            with transaction.atomic():
                ChartOfAccounts.objects.all().delete()
                AccountCategory.objects.all().delete()
                AccountType.objects.all().delete()

        self.stdout.write(self.style.SUCCESS('\n=== Initializing Chart of Accounts ===\n'))

        # Create Account Types
        self.create_account_types()

        # Create Account Categories
        self.create_account_categories()

        # Create Chart of Accounts
        self.create_chart_of_accounts()

        self.stdout.write(self.style.SUCCESS('\n[SUCCESS] Chart of Accounts initialized successfully!\n'))

    def create_account_types(self):
        """Create the five main account types"""
        self.stdout.write('Creating Account Types...')

        account_types = [
            {
                'name': AccountType.ASSET,
                'normal_balance': 'debit',
                'description': 'Resources owned by the organization (cash, receivables, assets)'
            },
            {
                'name': AccountType.LIABILITY,
                'normal_balance': 'credit',
                'description': 'Obligations owed to others (savings deposits, payables)'
            },
            {
                'name': AccountType.EQUITY,
                'normal_balance': 'credit',
                'description': 'Owner\'s stake in the business (capital, retained earnings)'
            },
            {
                'name': AccountType.INCOME,
                'normal_balance': 'credit',
                'description': 'Revenue earned from operations (interest income, fees)'
            },
            {
                'name': AccountType.EXPENSE,
                'normal_balance': 'debit',
                'description': 'Costs incurred in operations (salaries, rent, utilities)'
            },
        ]

        for type_data in account_types:
            account_type, created = AccountType.objects.get_or_create(
                name=type_data['name'],
                defaults={
                    'normal_balance': type_data['normal_balance'],
                    'description': type_data['description']
                }
            )
            if created:
                self.stdout.write(f'  [+] Created: {account_type.get_name_display()}')
            else:
                self.stdout.write(f'  [*] Exists: {account_type.get_name_display()}')

    def create_account_categories(self):
        """Create account categories (sub-classifications)"""
        self.stdout.write('\nCreating Account Categories...')

        # Get account types
        asset_type = AccountType.objects.get(name=AccountType.ASSET)
        liability_type = AccountType.objects.get(name=AccountType.LIABILITY)
        equity_type = AccountType.objects.get(name=AccountType.EQUITY)
        income_type = AccountType.objects.get(name=AccountType.INCOME)
        expense_type = AccountType.objects.get(name=AccountType.EXPENSE)

        categories = [
            # Asset Categories
            {'name': 'Cash & Bank', 'account_type': asset_type, 'code_prefix': '10',
             'description': 'Cash on hand and bank balances'},
            {'name': 'Loan Receivables', 'account_type': asset_type, 'code_prefix': '18',
             'description': 'Loans disbursed to clients'},
            {'name': 'Other Assets', 'account_type': asset_type, 'code_prefix': '19',
             'description': 'Fixed assets, prepaid expenses, etc.'},

            # Liability Categories
            {'name': 'Savings & Deposits', 'account_type': liability_type, 'code_prefix': '20',
             'description': 'Client savings deposits'},
            {'name': 'Interest Payable', 'account_type': liability_type, 'code_prefix': '21',
             'description': 'Interest owed on savings'},
            {'name': 'Other Liabilities', 'account_type': liability_type, 'code_prefix': '29',
             'description': 'Accounts payable, accrued expenses'},

            # Equity Categories
            {'name': 'Capital', 'account_type': equity_type, 'code_prefix': '30',
             'description': 'Share capital and retained earnings'},
            {'name': 'Current Year', 'account_type': equity_type, 'code_prefix': '31',
             'description': 'Current year profit or loss'},

            # Income Categories
            {'name': 'Interest Income', 'account_type': income_type, 'code_prefix': '40',
             'description': 'Interest earned from loans'},
            {'name': 'Fee Income', 'account_type': income_type, 'code_prefix': '41',
             'description': 'Fees collected from clients'},

            # Expense Categories
            {'name': 'Interest Expense', 'account_type': expense_type, 'code_prefix': '50',
             'description': 'Interest paid on savings'},
            {'name': 'Operating Expenses', 'account_type': expense_type, 'code_prefix': '51',
             'description': 'Salaries, rent, utilities'},
            {'name': 'Loan Loss Provisions', 'account_type': expense_type, 'code_prefix': '59',
             'description': 'Provision for bad debts'},

            # ---- New Categories ----
            {'name': 'Staff Receivables', 'account_type': asset_type, 'code_prefix': '12',
             'description': 'Loans and advances granted to staff members'},
            {'name': 'Accumulated Depreciation', 'account_type': asset_type, 'code_prefix': '13',
             'description': 'Contra-asset accounts for accumulated depreciation on fixed assets (credit normal balance)'},
            {'name': 'Loan Loss Reserve', 'account_type': asset_type, 'code_prefix': '16',
             'description': 'Contra-asset reserves set aside against expected loan losses by PAR aging bucket (credit normal balance)'},
            {'name': 'Other Income', 'account_type': income_type, 'code_prefix': '42',
             'description': 'Non-operational income such as donations, gifts, and first fruit'},
            {'name': 'Staff Costs', 'account_type': expense_type, 'code_prefix': '52',
             'description': 'Allowances, welfare, bonuses, and other staff-related expenditures beyond base salary'},
            {'name': 'Maintenance', 'account_type': expense_type, 'code_prefix': '53',
             'description': 'Maintenance and repair costs for equipment, buildings, vehicles, and office'},
            {'name': 'Administrative', 'account_type': expense_type, 'code_prefix': '54',
             'description': 'Audit, consultancy, legal, travel, and general administrative costs'},
            {'name': 'Other Expenses', 'account_type': expense_type, 'code_prefix': '55',
             'description': 'Security, bank charges, transport, and other miscellaneous expenses'},
        ]

        for cat_data in categories:
            category, created = AccountCategory.objects.get_or_create(
                code_prefix=cat_data['code_prefix'],
                defaults={
                    'name': cat_data['name'],
                    'account_type': cat_data['account_type'],
                    'description': cat_data['description']
                }
            )
            if created:
                self.stdout.write(f'  [+] Created: {category.code_prefix} - {category.name}')
            else:
                self.stdout.write(f'  [*] Exists: {category.code_prefix} - {category.name}')

    def create_chart_of_accounts(self):
        """Create the actual GL accounts"""
        self.stdout.write('\nCreating Chart of Accounts...')

        # Get account types
        asset_type = AccountType.objects.get(name=AccountType.ASSET)
        liability_type = AccountType.objects.get(name=AccountType.LIABILITY)
        equity_type = AccountType.objects.get(name=AccountType.EQUITY)
        income_type = AccountType.objects.get(name=AccountType.INCOME)
        expense_type = AccountType.objects.get(name=AccountType.EXPENSE)

        # Get categories
        cash_cat = AccountCategory.objects.get(code_prefix='10')
        loan_cat = AccountCategory.objects.get(code_prefix='18')
        asset_other_cat = AccountCategory.objects.get(code_prefix='19')
        savings_cat = AccountCategory.objects.get(code_prefix='20')
        interest_payable_cat = AccountCategory.objects.get(code_prefix='21')
        liability_other_cat = AccountCategory.objects.get(code_prefix='29')
        capital_cat = AccountCategory.objects.get(code_prefix='30')
        current_year_cat = AccountCategory.objects.get(code_prefix='31')
        interest_income_cat = AccountCategory.objects.get(code_prefix='40')
        fee_income_cat = AccountCategory.objects.get(code_prefix='41')
        interest_expense_cat = AccountCategory.objects.get(code_prefix='50')
        operating_expense_cat = AccountCategory.objects.get(code_prefix='51')
        provision_cat = AccountCategory.objects.get(code_prefix='59')

        # New categories
        staff_receivables_cat = AccountCategory.objects.get(code_prefix='12')
        accumulated_dep_cat = AccountCategory.objects.get(code_prefix='13')
        loan_loss_reserve_cat = AccountCategory.objects.get(code_prefix='16')
        other_income_cat = AccountCategory.objects.get(code_prefix='42')
        staff_costs_cat = AccountCategory.objects.get(code_prefix='52')
        maintenance_cat = AccountCategory.objects.get(code_prefix='53')
        administrative_cat = AccountCategory.objects.get(code_prefix='54')
        other_expenses_cat = AccountCategory.objects.get(code_prefix='55')

        accounts = [
            # ====================================================================
            # ASSETS
            # ====================================================================

            # Cash & Bank (1000-1099)
            {
                'gl_code': '1010',
                'account_name': 'Cash In Hand',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Physical cash held at branches',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1020',
                'account_name': 'Cash at Bank - Main Operating Account',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Primary bank account for operations',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1030',
                'account_name': 'Cash at Bank - Savings Account',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Bank savings account',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1040',
                'account_name': 'Petty Cash',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Small cash fund for minor expenses',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # Loan Receivables (1800-1899)
            {
                'gl_code': '1810',
                'account_name': 'Loan Receivable - Principal',
                'account_type': asset_type,
                'account_category': loan_cat,
                'description': 'Outstanding loan principal from clients',
                'is_control_account': False,
                'allows_manual_entries': False,  # System-generated only
            },
            {
                'gl_code': '1820',
                'account_name': 'Interest Receivable - Loans',
                'account_type': asset_type,
                'account_category': loan_cat,
                'description': 'Accrued interest on loans',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '1830',
                'account_name': 'Loan Fees Receivable',
                'account_type': asset_type,
                'account_category': loan_cat,
                'description': 'Unpaid loan-related fees',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # Other Assets (1900-1999)
            {
                'gl_code': '1910',
                'account_name': 'Prepaid Expenses',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Expenses paid in advance',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1920',
                'account_name': 'Fixed Assets',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Property, equipment, furniture',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # LIABILITIES
            # ====================================================================

            # Savings & Deposits (2000-2099)
            {
                'gl_code': '2010',
                'account_name': 'Savings Deposits - Regular',
                'account_type': liability_type,
                'account_category': savings_cat,
                'description': 'Regular savings deposits from clients',
                'is_control_account': False,
                'allows_manual_entries': False,  # System-generated only
            },
            {
                'gl_code': '2020',
                'account_name': 'Savings Deposits - Fixed',
                'account_type': liability_type,
                'account_category': savings_cat,
                'description': 'Fixed term deposits from clients',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '2030',
                'account_name': 'Savings Deposits - Target',
                'account_type': liability_type,
                'account_category': savings_cat,
                'description': 'Target savings deposits from clients',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '2040',
                'account_name': 'Savings Deposits - Children',
                'account_type': liability_type,
                'account_category': savings_cat,
                'description': 'Children savings deposits',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # Interest Payable (2100-2199)
            {
                'gl_code': '2110',
                'account_name': 'Interest Payable - Savings',
                'account_type': liability_type,
                'account_category': interest_payable_cat,
                'description': 'Accrued interest payable on savings deposits',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # Other Liabilities (2900-2999)
            {
                'gl_code': '2910',
                'account_name': 'Accounts Payable',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Outstanding bills and invoices',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '2920',
                'account_name': 'Accrued Expenses',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Expenses incurred but not yet paid',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # EQUITY
            # ====================================================================

            # Capital (3000-3099)
            {
                'gl_code': '3010',
                'account_name': 'Share Capital',
                'account_type': equity_type,
                'account_category': capital_cat,
                'description': 'Initial and additional capital invested',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '3020',
                'account_name': 'Retained Earnings',
                'account_type': equity_type,
                'account_category': capital_cat,
                'description': 'Accumulated profits from prior years',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # Current Year (3100-3199)
            {
                'gl_code': '3110',
                'account_name': 'Current Year Profit/Loss',
                'account_type': equity_type,
                'account_category': current_year_cat,
                'description': 'Net profit or loss for current financial year',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # ====================================================================
            # INCOME
            # ====================================================================

            # Interest Income (4000-4099)
            {
                'gl_code': '4010',
                'account_name': 'Interest Income - Loans',
                'account_type': income_type,
                'account_category': interest_income_cat,
                'description': 'Interest earned on loans to clients',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4020',
                'account_name': 'Interest Income - Investments',
                'account_type': income_type,
                'account_category': interest_income_cat,
                'description': 'Interest earned from bank deposits and investments',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # Fee Income (4100-4199)
            {
                'gl_code': '4110',
                'account_name': 'Registration Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Client registration fees',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4112',
                'account_name': 'ID Card Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Fee collected for issuing client ID cards',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4114',
                'account_name': 'Membership Card Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Fee collected for issuing client membership cards',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4120',
                'account_name': 'Loan Application Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Loan form and application fees',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4130',
                'account_name': 'Loan Insurance Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Insurance fees collected on loans',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4140',
                'account_name': 'Processing Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Loan processing fees',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4150',
                'account_name': 'Risk Premium Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Risk premium fees',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4160',
                'account_name': 'Technology Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Technology and platform fees',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4170',
                'account_name': 'Late Payment Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Penalty fees for late payments',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # ====================================================================
            # EXPENSES
            # ====================================================================

            # Interest Expense (5000-5099)
            {
                'gl_code': '5010',
                'account_name': 'Interest Expense - Savings',
                'account_type': expense_type,
                'account_category': interest_expense_cat,
                'description': 'Interest paid to clients on savings deposits',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # Operating Expenses (5100-5199)
            {
                'gl_code': '5110',
                'account_name': 'Salaries & Wages',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Staff salaries and wages',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5120',
                'account_name': 'Rent Expense',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Office and branch rental costs',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5130',
                'account_name': 'Utilities Expense',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Electricity, water, internet, phone',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5140',
                'account_name': 'Office Supplies',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Stationery, printing, and office supplies',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # Loan Loss Provisions (5900-5999)
            {
                'gl_code': '5910',
                'account_name': 'Provision for Bad Debts',
                'account_type': expense_type,
                'account_category': provision_cat,
                'description': 'General provision for uncollectible loans',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # CASH & BANK — Additional Bank Accounts (10xx)
            # ====================================================================
            {
                'gl_code': '1050',
                'account_name': 'Cash at Bank - Globus Bank',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Globus Bank operating account',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1060',
                'account_name': 'Cash at Bank - Zenith Bank',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Zenith Bank operating account',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1070',
                'account_name': 'Cash at Bank - First Bank',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'First Bank operating account',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1080',
                'account_name': 'Domiciliary Account',
                'account_type': asset_type,
                'account_category': cash_cat,
                'description': 'Foreign currency domiciliary bank account',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # STAFF RECEIVABLES (12xx)
            # ====================================================================
            {
                'gl_code': '1210',
                'account_name': 'Staff Loans Receivable',
                'account_type': asset_type,
                'account_category': staff_receivables_cat,
                'description': 'Loans and salary advances given to staff members, to be recovered via payroll deductions',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # ACCUMULATED DEPRECIATION (13xx) — Contra-Asset (Credit Normal Balance)
            # Note: These are contra-asset accounts. Balances here offset the
            # corresponding fixed asset values on the Balance Sheet.
            # ====================================================================
            {
                'gl_code': '1310',
                'account_name': 'Accumulated Depreciation - Computer Equipment',
                'account_type': asset_type,
                'account_category': accumulated_dep_cat,
                'description': 'Contra-asset: total depreciation charged to date on computer equipment (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1320',
                'account_name': 'Accumulated Depreciation - Motor Vehicles',
                'account_type': asset_type,
                'account_category': accumulated_dep_cat,
                'description': 'Contra-asset: total depreciation charged to date on motor vehicles (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1330',
                'account_name': 'Accumulated Depreciation - Land & Buildings',
                'account_type': asset_type,
                'account_category': accumulated_dep_cat,
                'description': 'Contra-asset: total depreciation charged to date on land and buildings (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # LOAN LOSS RESERVE (16xx) — Contra-Asset PAR Aging Buckets
            # Note: These are contra-asset reserves that offset loan receivables
            # on the Balance Sheet. Each bucket corresponds to an overdue aging band.
            # ====================================================================
            {
                'gl_code': '1610',
                'account_name': 'Loan Loss Reserve - 0 to 30 Days',
                'account_type': asset_type,
                'account_category': loan_loss_reserve_cat,
                'description': 'Contra-asset: reserve against loans overdue 0-30 days (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1620',
                'account_name': 'Loan Loss Reserve - 31 to 60 Days',
                'account_type': asset_type,
                'account_category': loan_loss_reserve_cat,
                'description': 'Contra-asset: reserve against loans overdue 31-60 days (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1630',
                'account_name': 'Loan Loss Reserve - 61 to 90 Days',
                'account_type': asset_type,
                'account_category': loan_loss_reserve_cat,
                'description': 'Contra-asset: reserve against loans overdue 61-90 days (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1640',
                'account_name': 'Loan Loss Reserve - 91 Days & Above',
                'account_type': asset_type,
                'account_category': loan_loss_reserve_cat,
                'description': 'Contra-asset: reserve against loans overdue 91+ days — loss category (credit normal balance)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # LOAN RECEIVABLES — Additional (18xx)
            # ====================================================================
            {
                'gl_code': '1840',
                'account_name': 'Loan Receivable - MED Clients',
                'account_type': asset_type,
                'account_category': loan_cat,
                'description': 'Outstanding principal from Micro-Enterprise Development (MED) loan clients',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # ====================================================================
            # OTHER ASSETS — Additional Fixed Assets & Prepaid (19xx)
            # ====================================================================
            {
                'gl_code': '1912',
                'account_name': 'Office Rent Prepaid',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Office rent paid in advance, pending monthly recognition as Rent Expense',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1914',
                'account_name': 'Staff Rent Prepaid',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Rent advance paid on behalf of staff members, to be recovered via payroll',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1916',
                'account_name': 'Software Prepaid Expenses',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Software licences and subscriptions paid in advance pending amortisation',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1922',
                'account_name': 'Motor Vehicle',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Company-owned motor vehicles recorded at cost',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1924',
                'account_name': 'Solar Equipment',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Solar panels, inverters, batteries, and related equipment recorded at cost',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1926',
                'account_name': 'Computer Equipment',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Computers, laptops, printers, and technology hardware recorded at cost',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1930',
                'account_name': 'Stationery Stock',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Physical inventory of stationery and consumables not yet expensed',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1940',
                'account_name': 'Investments',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Short-term and long-term investments in securities, treasury bills, or fixed deposits',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '1950',
                'account_name': 'Interbranch Transfer Clearing',
                'account_type': asset_type,
                'account_category': asset_other_cat,
                'description': 'Clearing account for funds in transit between branches; should net to zero once settled',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # SAVINGS & DEPOSITS — Additional (20xx)
            # ====================================================================
            {
                'gl_code': '2050',
                'account_name': 'Savings Deposits - Thrift',
                'account_type': liability_type,
                'account_category': savings_cat,
                'description': 'Thrift/cooperative savings deposits held on behalf of clients',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # ====================================================================
            # OTHER LIABILITIES — Additional (29xx)
            # ====================================================================
            {
                'gl_code': '2930',
                'account_name': 'Staff Welfare Deduction Payable',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Staff welfare contributions deducted from payroll and awaiting disbursement',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '2932',
                'account_name': 'Pension Deduction Payable',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Pension contributions deducted from staff salaries and awaiting remittance to pension fund',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '2950',
                'account_name': 'Overpayment Liability - Regular Savings',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Client overpayments on regular savings accounts pending refund or reallocation',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '2952',
                'account_name': 'Overpayment Liability - Loan Repayments',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Client overpayments on loan repayments pending refund or reallocation',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '2954',
                'account_name': 'Overpayment Liability - MED Clients',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Overpayments from MED loan clients pending refund or reallocation',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '2956',
                'account_name': 'Overpayment Liability - Special Savings',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Overpayments on special savings products pending refund or reallocation',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '2958',
                'account_name': 'Overdraft Facility',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Outstanding overdraft balance owed to bank or creditor',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '2960',
                'account_name': 'Fund Transfer Clearing',
                'account_type': liability_type,
                'account_category': liability_other_cat,
                'description': 'Clearing account for fund transfers in transit pending final confirmation; should net to zero once settled',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # INTEREST INCOME — Additional (40xx)
            # ====================================================================
            {
                'gl_code': '4030',
                'account_name': 'Interest Income - Asset Finance Loans',
                'account_type': income_type,
                'account_category': interest_income_cat,
                'description': 'Interest earned on asset finance loan products',
                'is_control_account': False,
                'allows_manual_entries': False,
            },
            {
                'gl_code': '4040',
                'account_name': 'Interest Income - MED Loans',
                'account_type': income_type,
                'account_category': interest_income_cat,
                'description': 'Interest earned on Micro-Enterprise Development (MED) loans',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # ====================================================================
            # FEE INCOME — Additional (41xx)
            # ====================================================================
            {
                'gl_code': '4180',
                'account_name': 'Default Fee Income',
                'account_type': income_type,
                'account_category': fee_income_cat,
                'description': 'Fees charged to clients who refuse or fail to pay scheduled fees',
                'is_control_account': False,
                'allows_manual_entries': False,
            },

            # ====================================================================
            # OTHER INCOME (42xx)
            # ====================================================================
            {
                'gl_code': '4210',
                'account_name': 'First Fruit Income',
                'account_type': income_type,
                'account_category': other_income_cat,
                'description': 'First fruit offerings received from staff and members as voluntary contributions',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '4220',
                'account_name': 'Donations & Gifts Received',
                'account_type': income_type,
                'account_category': other_income_cat,
                'description': 'Cash and in-kind donations and gifts received from external parties or well-wishers',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # OPERATING EXPENSES — Additional (51xx)
            # ====================================================================
            {
                'gl_code': '5150',
                'account_name': 'Tax & Levy',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Government taxes, waste disposal levies, and other statutory charges',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5160',
                'account_name': 'Monitoring & Inspection Fees',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Fees paid to external auditors, regulatory inspectors, and monitoring officers',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5170',
                'account_name': 'Electricity & Water',
                'account_type': expense_type,
                'account_category': operating_expense_cat,
                'description': 'Electricity and water utility bills for branch and office premises',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # STAFF COSTS (52xx)
            # ====================================================================
            {
                'gl_code': '5210',
                'account_name': 'Housing Allowance',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': 'Housing allowances paid to staff members as part of remuneration package',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5220',
                'account_name': 'Transfer Allowance',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': 'Allowances paid to staff on branch transfer or official relocation',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5230',
                'account_name': 'Medical Expense',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': 'Medical and healthcare expenses incurred on behalf of staff',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5240',
                'account_name': 'Seasonal Bonus',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': 'Seasonal, festive, and performance-related bonuses paid to staff',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5250',
                'account_name': 'Staff Welfare Expense',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': 'Disbursements from staff welfare fund for gifts, emergencies, and social activities',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5260',
                'account_name': 'Scholarship Award',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': 'Scholarship awards granted to staff members or their dependants',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5270',
                'account_name': 'Pension Expense',
                'account_type': expense_type,
                'account_category': staff_costs_cat,
                'description': "Employer's pension contributions for staff members",
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # MAINTENANCE (53xx)
            # ====================================================================
            {
                'gl_code': '5310',
                'account_name': 'Computer Equipment Maintenance',
                'account_type': expense_type,
                'account_category': maintenance_cat,
                'description': 'Repairs and servicing of computers, printers, and other technology hardware',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5320',
                'account_name': 'Building Maintenance',
                'account_type': expense_type,
                'account_category': maintenance_cat,
                'description': 'Repairs and maintenance of office buildings and physical structures',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5330',
                'account_name': 'Furniture & Fittings Maintenance',
                'account_type': expense_type,
                'account_category': maintenance_cat,
                'description': 'Repairs and upkeep of furniture and office fittings',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5340',
                'account_name': 'Generator Fueling & Maintenance',
                'account_type': expense_type,
                'account_category': maintenance_cat,
                'description': 'Diesel fuel, servicing costs, and repairs for generators',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5350',
                'account_name': 'Office Maintenance',
                'account_type': expense_type,
                'account_category': maintenance_cat,
                'description': 'General repairs and maintenance of office premises not covered by specific categories',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # ADMINISTRATIVE (54xx)
            # ====================================================================
            {
                'gl_code': '5410',
                'account_name': 'Audit & Compliance Expenses',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'External audit fees and regulatory compliance costs',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5420',
                'account_name': 'Consultancy Fees',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Fees paid to external consultants and professional advisors',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5430',
                'account_name': 'Legal Fees',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Legal and professional advisory fees for contracts, disputes, and compliance',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5440',
                'account_name': 'Board Meeting Expenses',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Costs associated with board of directors and management committee meetings',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5450',
                'account_name': 'Postage & Courier',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Postage, courier services, and document delivery costs',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5460',
                'account_name': 'Hotel & Accommodation Allowance',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Hotel and accommodation costs for staff on official duties or training',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5470',
                'account_name': 'Hospitalization Expenses',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'In-patient hospital and emergency medical care costs for staff',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5480',
                'account_name': 'Meal & Entertainment',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Meals, refreshments, and entertainment for staff and clients',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5490',
                'account_name': 'Internet Services',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Monthly internet and broadband data subscription costs',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5492',
                'account_name': 'Technology & Software Expense',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Software licences, tech platform fees, and IT-related operational expenses not capitalised',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5495',
                'account_name': 'Telephone Expense',
                'account_type': expense_type,
                'account_category': administrative_cat,
                'description': 'Staff and office telephone, airtime, and mobile communication expenses',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # OTHER EXPENSES (55xx)
            # ====================================================================
            {
                'gl_code': '5510',
                'account_name': 'CBN Charges & Bank Fees',
                'account_type': expense_type,
                'account_category': other_expenses_cat,
                'description': 'Central Bank of Nigeria charges, interbank transfer fees, and related bank costs',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5520',
                'account_name': 'Security Expense',
                'account_type': expense_type,
                'account_category': other_expenses_cat,
                'description': 'Security guard services, surveillance systems, and premises security costs',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5530',
                'account_name': 'Other Transport Expenses',
                'account_type': expense_type,
                'account_category': other_expenses_cat,
                'description': 'Transport costs to meetings, field visits, and other official travel not classified elsewhere',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5540',
                'account_name': 'Admin Fee Expenses',
                'account_type': expense_type,
                'account_category': other_expenses_cat,
                'description': 'Miscellaneous administrative service charges and processing fees',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5550',
                'account_name': 'Other Losses',
                'account_type': expense_type,
                'account_category': other_expenses_cat,
                'description': 'Sundry losses and write-offs not captured in any other expense category',
                'is_control_account': False,
                'allows_manual_entries': True,
            },

            # ====================================================================
            # LOAN LOSS PROVISIONS — PAR Aging Buckets (59xx)
            # Paired with Loan Loss Reserve accounts (16xx) on the Balance Sheet.
            # Debit these when recognising provision; credit the corresponding reserve.
            # ====================================================================
            {
                'gl_code': '5920',
                'account_name': 'Provision for Loan Losses - 0 to 30 Days',
                'account_type': expense_type,
                'account_category': provision_cat,
                'description': 'Provision expense for performing loans overdue 0-30 days (PAR 30 bucket)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5930',
                'account_name': 'Provision for Loan Losses - 31 to 60 Days',
                'account_type': expense_type,
                'account_category': provision_cat,
                'description': 'Provision expense for sub-standard loans overdue 31-60 days (PAR 60 bucket)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5940',
                'account_name': 'Provision for Loan Losses - 61 to 90 Days',
                'account_type': expense_type,
                'account_category': provision_cat,
                'description': 'Provision expense for doubtful loans overdue 61-90 days (PAR 90 bucket)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
            {
                'gl_code': '5950',
                'account_name': 'Provision for Loan Losses - 91 Days & Above',
                'account_type': expense_type,
                'account_category': provision_cat,
                'description': 'Provision expense for loss-classified loans overdue 91+ days (write-off category)',
                'is_control_account': False,
                'allows_manual_entries': True,
            },
        ]

        for account_data in accounts:
            account, created = ChartOfAccounts.objects.get_or_create(
                gl_code=account_data['gl_code'],
                defaults={
                    'account_name': account_data['account_name'],
                    'account_type': account_data['account_type'],
                    'account_category': account_data['account_category'],
                    'description': account_data['description'],
                    'is_control_account': account_data['is_control_account'],
                    'allows_manual_entries': account_data['allows_manual_entries'],
                    'currency': 'NGN',
                    'is_active': True,
                }
            )
            if created:
                self.stdout.write(f'  [+] Created: {account.gl_code} - {account.account_name}')
            else:
                self.stdout.write(f'  [*] Exists: {account.gl_code} - {account.account_name}')

        # Print summary
        self.stdout.write('\n--- Summary ---')
        self.stdout.write(f'Total Accounts: {ChartOfAccounts.objects.count()}')
        self.stdout.write(f'  Assets: {ChartOfAccounts.objects.filter(account_type__name=AccountType.ASSET).count()}')
        self.stdout.write(f'  Liabilities: {ChartOfAccounts.objects.filter(account_type__name=AccountType.LIABILITY).count()}')
        self.stdout.write(f'  Equity: {ChartOfAccounts.objects.filter(account_type__name=AccountType.EQUITY).count()}')
        self.stdout.write(f'  Income: {ChartOfAccounts.objects.filter(account_type__name=AccountType.INCOME).count()}')
        self.stdout.write(f'  Expenses: {ChartOfAccounts.objects.filter(account_type__name=AccountType.EXPENSE).count()}')
