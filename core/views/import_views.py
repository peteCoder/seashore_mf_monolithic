"""
Bulk CSV Import Views
=====================

Provides CSV import for clients, loans, and savings accounts.
Each view:
  GET  — renders an upload form with a downloadable CSV template
  POST — parses the CSV, creates objects row by row, returns a results page

All imports are wrapped in per-row atomic transactions so one bad row
doesn't block the rest.
"""

import csv
import io
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.permissions import PermissionChecker


# =============================================================================
# CLIENT CSV IMPORT
# =============================================================================

CLIENT_CSV_HEADERS = [
    'first_name', 'last_name', 'phone', 'email',
    'date_of_birth',    # YYYY-MM-DD
    'gender',           # M / F / O
    'address',
    'id_type',          # nin / bvn / passport / drivers_licence / voters_card
    'id_number',
    'branch_code',      # Branch code/name (matched by name, case-insensitive)
    'monthly_income',   # numeric
    'occupation',
]


@login_required
def import_clients(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    if request.GET.get('template') == '1':
        return _csv_template_response('clients_import_template.csv', CLIENT_CSV_HEADERS)

    if request.method != 'POST':
        return render(request, 'imports/import_clients.html', {
            'page_title': 'Import Clients',
            'headers': CLIENT_CSV_HEADERS,
        })

    # ── Process uploaded CSV ──────────────────────────────────────────────────
    from core.models import Client, Branch, User

    csv_file = request.FILES.get('csv_file')
    results  = _parse_and_import(
        csv_file=csv_file,
        required_cols=['first_name', 'last_name', 'phone', 'branch_code'],
        row_handler=_import_client_row,
        handler_kwargs={
            'created_by': request.user,
            'checker': checker,
        },
    )

    return render(request, 'imports/import_result.html', {
        'page_title':  'Client Import Results',
        'back_url':    'core:import_clients',
        'back_label':  'Import More Clients',
        'list_url':    'core:client_list',
        'list_label':  'View Clients',
        **results,
    })


def _import_client_row(row, row_num, created_by, checker):
    from core.models import Client, Branch

    branch = Branch.objects.filter(name__iexact=row.get('branch_code', '').strip()).first()
    if not branch:
        return False, f"Branch '{row.get('branch_code')}' not found"

    # Manager can only import into their own branch
    if checker.is_manager() and branch != created_by.branch:
        return False, "Managers can only import clients into their own branch"

    phone = row.get('phone', '').strip()
    if Client.objects.filter(phone=phone).exists():
        return False, f"Phone {phone} already registered"

    dob = None
    if row.get('date_of_birth'):
        try:
            from datetime import datetime
            dob = datetime.strptime(row['date_of_birth'].strip(), '%Y-%m-%d').date()
        except ValueError:
            return False, "date_of_birth must be YYYY-MM-DD"

    income = Decimal('0.00')
    if row.get('monthly_income'):
        try:
            income = Decimal(str(row['monthly_income'].strip().replace(',', '')))
        except InvalidOperation:
            income = Decimal('0.00')

    with transaction.atomic():
        Client.objects.create(
            first_name=row.get('first_name', '').strip(),
            last_name=row.get('last_name', '').strip(),
            phone=phone,
            email=row.get('email', '').strip() or None,
            date_of_birth=dob,
            gender=row.get('gender', '').strip() or 'O',
            address=row.get('address', '').strip(),
            id_type=row.get('id_type', '').strip() or None,
            id_number=row.get('id_number', '').strip() or None,
            branch=branch,
            monthly_income=income,
            occupation=row.get('occupation', '').strip(),
            created_by=created_by,
            status='pending',
        )
    return True, None


# =============================================================================
# LOAN CSV IMPORT
# =============================================================================

LOAN_CSV_HEADERS = [
    'client_phone',       # matches existing client by phone
    'loan_product_name',  # matches LoanProduct.name (case-insensitive)
    'principal_amount',   # numeric
    'duration_months',    # integer
    'purpose',            # optional text
    'notes',              # optional text
]


@login_required
def import_loans(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    if request.GET.get('template') == '1':
        return _csv_template_response('loans_import_template.csv', LOAN_CSV_HEADERS)

    if request.method != 'POST':
        return render(request, 'imports/import_loans.html', {
            'page_title': 'Import Loan Applications',
            'headers': LOAN_CSV_HEADERS,
        })

    results = _parse_and_import(
        csv_file=request.FILES.get('csv_file'),
        required_cols=['client_phone', 'loan_product_name', 'principal_amount', 'duration_months'],
        row_handler=_import_loan_row,
        handler_kwargs={'created_by': request.user, 'checker': checker},
    )

    return render(request, 'imports/import_result.html', {
        'page_title': 'Loan Import Results',
        'back_url':   'core:import_loans',
        'back_label': 'Import More Loans',
        'list_url':   'core:loan_list',
        'list_label': 'View Loans',
        **results,
    })


def _import_loan_row(row, row_num, created_by, checker):
    from core.models import Client, Loan, LoanProduct

    phone  = row.get('client_phone', '').strip()
    client = Client.objects.filter(phone=phone).first()
    if not client:
        return False, f"No client with phone {phone}"

    if checker.is_manager() and client.branch != created_by.branch:
        return False, "Client belongs to a different branch"

    product_name = row.get('loan_product_name', '').strip()
    product = LoanProduct.objects.filter(name__iexact=product_name, is_active=True).first()
    if not product:
        return False, f"Loan product '{product_name}' not found or inactive"

    try:
        amount = Decimal(str(row.get('principal_amount', '').strip().replace(',', '')))
    except InvalidOperation:
        return False, "principal_amount must be a number"

    try:
        duration = int(row.get('duration_months', '').strip())
    except (ValueError, TypeError):
        return False, "duration_months must be an integer"

    with transaction.atomic():
        Loan.objects.create(
            client=client,
            loan_product=product,
            branch=client.branch,
            principal_amount=amount,
            duration_months=duration,
            purpose=row.get('purpose', '').strip(),
            notes=row.get('notes', '').strip(),
            created_by=created_by,
            status='pending_fees',
        )
    return True, None


# =============================================================================
# SAVINGS ACCOUNT CSV IMPORT
# =============================================================================

SAVINGS_CSV_HEADERS = [
    'client_phone',          # matches existing client by phone
    'savings_product_name',  # matches SavingsProduct.name (case-insensitive)
    'opening_balance',       # numeric (optional, defaults to 0)
    'notes',                 # optional
]


@login_required
def import_savings(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    if request.GET.get('template') == '1':
        return _csv_template_response('savings_import_template.csv', SAVINGS_CSV_HEADERS)

    if request.method != 'POST':
        return render(request, 'imports/import_savings.html', {
            'page_title': 'Import Savings Accounts',
            'headers': SAVINGS_CSV_HEADERS,
        })

    results = _parse_and_import(
        csv_file=request.FILES.get('csv_file'),
        required_cols=['client_phone', 'savings_product_name'],
        row_handler=_import_savings_row,
        handler_kwargs={'created_by': request.user, 'checker': checker},
    )

    return render(request, 'imports/import_result.html', {
        'page_title': 'Savings Import Results',
        'back_url':   'core:import_savings',
        'back_label': 'Import More Savings Accounts',
        'list_url':   'core:savings_account_list',
        'list_label': 'View Savings Accounts',
        **results,
    })


def _import_savings_row(row, row_num, created_by, checker):
    from core.models import Client, SavingsAccount, SavingsProduct
    from datetime import timedelta

    phone  = row.get('client_phone', '').strip()
    client = Client.objects.filter(phone=phone).first()
    if not client:
        return False, f"No client with phone {phone}"

    if checker.is_manager() and client.branch != created_by.branch:
        return False, "Client belongs to a different branch"

    product_name = row.get('savings_product_name', '').strip()
    product = SavingsProduct.objects.filter(name__iexact=product_name, is_active=True).first()
    if not product:
        return False, f"Savings product '{product_name}' not found or inactive"

    opening = Decimal('0.00')
    if row.get('opening_balance'):
        try:
            opening = Decimal(str(row['opening_balance'].strip().replace(',', '')))
        except InvalidOperation:
            opening = Decimal('0.00')

    today = timezone.now().date()
    maturity_date = None
    if product.product_type == 'fixed' and product.fixed_term_months:
        from dateutil.relativedelta import relativedelta
        maturity_date = today + relativedelta(months=product.fixed_term_months)

    with transaction.atomic():
        SavingsAccount.objects.create(
            client=client,
            savings_product=product,
            branch=client.branch,
            balance=opening,
            status='pending',
            maturity_date=maturity_date,
            created_by=created_by,
        )
    return True, None


# =============================================================================
# SHARED HELPERS
# =============================================================================

def _parse_and_import(csv_file, required_cols, row_handler, handler_kwargs):
    """
    Parse a CSV file and call row_handler for each data row.
    Returns a dict with: created, failed, errors (list of {row, reason}).
    """
    if not csv_file:
        return {'created': 0, 'failed': 0, 'errors': [{'row': '—', 'reason': 'No file uploaded.'}]}

    try:
        text    = csv_file.read().decode('utf-8-sig')   # utf-8-sig strips BOM
        reader  = csv.DictReader(io.StringIO(text))
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    except Exception as exc:
        return {'created': 0, 'failed': 0, 'errors': [{'row': '—', 'reason': f"Could not read CSV: {exc}"}]}

    missing = [c for c in required_cols if c not in headers]
    if missing:
        return {
            'created': 0, 'failed': 0,
            'errors': [{'row': '—', 'reason': f"Missing required columns: {', '.join(missing)}"}],
        }

    created = 0
    failed  = 0
    errors  = []

    for row_num, raw_row in enumerate(reader, start=2):
        # Normalise keys
        row = {k.strip().lower(): v for k, v in raw_row.items() if k}
        # Skip completely blank rows
        if not any(v.strip() for v in row.values()):
            continue

        try:
            ok, reason = row_handler(row, row_num, **handler_kwargs)
        except Exception as exc:
            ok, reason = False, str(exc)

        if ok:
            created += 1
        else:
            failed += 1
            errors.append({'row': row_num, 'reason': reason})

    return {'created': created, 'failed': failed, 'errors': errors}


def _csv_template_response(filename, headers):
    """Return a downloadable CSV file with just the header row."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    return response
