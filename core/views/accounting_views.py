"""
Accounting Views
================

Views for accounting module including:
- Chart of Accounts management
- Journal Entry management
- Financial Reports (Trial Balance, P&L, Balance Sheet, etc.)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum, F, Case, When, DecimalField, Value
from django.db.models.functions import TruncDate
from django.db import transaction as db_transaction
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta, datetime

from core.models import (
    ChartOfAccounts, JournalEntry, JournalEntryLine,
    Transaction, Branch, AccountType, AccountCategory, Loan
)
from core.forms.accounting_forms import (
    DateRangeForm, TrialBalanceForm, ProfitLossForm, BalanceSheetForm,
    GeneralLedgerForm, JournalEntrySearchForm,
    JournalEntryForm, JournalEntryLineFormSet, JournalReversalForm,
    OpeningBalanceForm
)
from core.permissions import PermissionChecker
from core.utils.accounting_helpers import create_journal_entry
from core.utils.pdf_export import (
    generate_trial_balance_pdf, generate_profit_loss_pdf,
    generate_balance_sheet_pdf, generate_general_ledger_pdf,
    generate_cash_flow_pdf, generate_transaction_audit_pdf
)
from core.utils.excel_export import (
    export_trial_balance_excel, export_profit_loss_excel,
    export_balance_sheet_excel, export_general_ledger_excel,
    export_cash_flow_excel, export_transaction_audit_excel
)

import logging

logger = logging.getLogger(__name__)


# =============================================================================
# ACCOUNTING DASHBOARD
# =============================================================================

@login_required
def accounting_dashboard(request):
    """
    Accounting Module Dashboard

    Displays key metrics, recent activity, and quick links
    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to access the accounting module.')
        raise PermissionDenied

    # Get cash account balance
    cash_account = ChartOfAccounts.objects.filter(gl_code='1010').first()
    cash_balance = Decimal('0.00')
    if cash_account:
        cash_debits = JournalEntryLine.objects.filter(
            account=cash_account,
            journal_entry__status='posted'
        ).aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')

        cash_credits = JournalEntryLine.objects.filter(
            account=cash_account,
            journal_entry__status='posted'
        ).aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

        cash_balance = cash_debits - cash_credits

    # Journal entry stats
    total_journals = JournalEntry.objects.count()
    unposted_journals = JournalEntry.objects.filter(status__in=['draft', 'pending']).count()

    # Get entries posted today (using date range)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = timezone.now().replace(hour=23, minute=59, second=59, microsecond=999999)
    posted_today = JournalEntry.objects.filter(
        status='posted',
        posting_date__gte=today_start,
        posting_date__lte=today_end
    ).count()

    # Recent journal entries
    recent_journals = JournalEntry.objects.select_related('branch', 'created_by').order_by('-created_at')[:10]

    # Account summary by type
    account_types = AccountType.objects.all()
    accounts_by_type = []
    for acc_type in account_types:
        count = ChartOfAccounts.objects.filter(account_type=acc_type, is_active=True).count()
        accounts_by_type.append({
            'type': acc_type.get_name_display(),
            'count': count
        })

    # Transactions needing journal entries (audit check)
    transactions_without_journals = Transaction.objects.filter(
        status='completed'
    ).exclude(
        id__in=JournalEntry.objects.filter(transaction__isnull=False).values_list('transaction_id', flat=True)
    ).count()

    context = {
        'page_title': 'Accounting Dashboard',
        'cash_balance': cash_balance,
        'total_journals': total_journals,
        'unposted_journals': unposted_journals,
        'posted_today': posted_today,
        'recent_journals': recent_journals,
        'accounts_by_type': accounts_by_type,
        'transactions_without_journals': transactions_without_journals,
    }

    return render(request, 'accounting/accounting_dashboard.html', context)


# =============================================================================
# CHART OF ACCOUNTS VIEWS
# =============================================================================

@login_required
def chart_of_accounts_list(request):
    """
    Display hierarchical list of all GL accounts

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view Chart of Accounts.')
        raise PermissionDenied

    # Base queryset
    accounts = ChartOfAccounts.objects.select_related(
        'account_type', 'account_category', 'parent_account', 'branch'
    ).prefetch_related('journal_lines')

    # Filters
    q = request.GET.get('q', '').strip()
    if q:
        accounts = accounts.filter(
            Q(gl_code__icontains=q) | Q(account_name__icontains=q)
        )

    account_type_filter = request.GET.get('account_type')
    if account_type_filter:
        accounts = accounts.filter(account_type__name=account_type_filter)

    is_active = request.GET.get('is_active')
    if is_active == 'true':
        accounts = accounts.filter(is_active=True)
    elif is_active == 'false':
        accounts = accounts.filter(is_active=False)

    branch_filter = request.GET.get('branch')
    if branch_filter:
        accounts = accounts.filter(Q(branch_id=branch_filter) | Q(branch__isnull=True))

    # Calculate balances for each account
    accounts_with_balances = []
    for account in accounts.order_by('gl_code'):
        # Calculate balance from journal lines
        debit_total = account.journal_lines.aggregate(
            total=Sum('debit_amount'))['total'] or Decimal('0')
        credit_total = account.journal_lines.aggregate(
            total=Sum('credit_amount'))['total'] or Decimal('0')

        # Balance depends on account type normal balance
        if account.account_type.normal_balance == 'debit':
            balance = debit_total - credit_total
        else:
            balance = credit_total - debit_total

        accounts_with_balances.append({
            'account': account,
            'debit_total': debit_total,
            'credit_total': credit_total,
            'balance': balance
        })

    context = {
        'page_title': 'Chart of Accounts',
        'accounts': accounts_with_balances,
        'account_types': AccountType.TYPE_CHOICES,
        'branches': Branch.objects.filter(is_active=True),
        'total_accounts': len(accounts_with_balances),
        'q': q,
    }

    return render(request, 'accounting/coa_list.html', context)


@login_required
def chart_of_accounts_detail(request, account_id):
    """
    Display account detail with transaction history

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view account details.')
        raise PermissionDenied

    account = get_object_or_404(
        ChartOfAccounts.objects.select_related('account_type', 'account_category', 'parent_account', 'branch'),
        id=account_id
    )

    # Get recent journal lines
    journal_lines = account.journal_lines.select_related(
        'journal_entry', 'journal_entry__branch', 'journal_entry__created_by', 'client'
    ).order_by('-journal_entry__transaction_date', '-journal_entry__created_at')[:100]

    # Calculate balances
    debit_total = account.journal_lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
    credit_total = account.journal_lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

    if account.account_type.normal_balance == 'debit':
        balance = debit_total - credit_total
    else:
        balance = credit_total - debit_total

    # Get sub-accounts
    sub_accounts = ChartOfAccounts.objects.filter(parent_account=account)

    context = {
        'page_title': f'Account: {account.account_name}',
        'account': account,
        'debit_total': debit_total,
        'credit_total': credit_total,
        'balance': balance,
        'journal_lines': journal_lines,
        'sub_accounts': sub_accounts,
    }

    return render(request, 'accounting/coa_detail.html', context)


@login_required
def chart_of_accounts_create(request):
    """
    Create new GL account

    Permissions: Director, Admin only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors and Administrators can create GL accounts.')
        raise PermissionDenied

    if request.method == 'POST':
        # Manual form processing since we're not using ModelForm
        gl_code = request.POST.get('gl_code')
        account_name = request.POST.get('account_name')
        account_type_id = request.POST.get('account_type')
        account_category_id = request.POST.get('account_category')
        parent_account_id = request.POST.get('parent_account')
        branch_id = request.POST.get('branch')
        description = request.POST.get('description', '')
        is_control_account = request.POST.get('is_control_account') == 'on'
        allows_manual_entries = request.POST.get('allows_manual_entries') == 'on'

        try:
            # Validate unique GL code
            if ChartOfAccounts.objects.filter(gl_code=gl_code).exists():
                messages.error(request, f'Account with GL Code {gl_code} already exists.')
            else:
                account = ChartOfAccounts.objects.create(
                    gl_code=gl_code,
                    account_name=account_name,
                    account_type_id=account_type_id,
                    account_category_id=account_category_id if account_category_id else None,
                    parent_account_id=parent_account_id if parent_account_id else None,
                    branch_id=branch_id if branch_id else None,
                    description=description,
                    is_control_account=is_control_account,
                    allows_manual_entries=allows_manual_entries,
                    currency='NGN',
                    is_active=True
                )

                messages.success(request, f'GL Account {account.gl_code} - {account.account_name} created successfully!')
                return redirect('core:coa_detail', account_id=account.id)
        except Exception as e:
            messages.error(request, f'Error creating account: {str(e)}')

    context = {
        'page_title': 'Create GL Account',
        'account_types': AccountType.objects.all(),
        'account_categories': AccountCategory.objects.select_related('account_type'),
        'parent_accounts': ChartOfAccounts.objects.filter(is_control_account=True, is_active=True),
        'branches': Branch.objects.filter(is_active=True),
    }

    return render(request, 'accounting/coa_form.html', context)


@login_required
def chart_of_accounts_edit(request, account_id):
    """
    Edit existing GL account

    Permissions: Director, Admin only
    Note: GL Code cannot be changed if transactions exist
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors and Administrators can edit GL accounts.')
        raise PermissionDenied

    account = get_object_or_404(ChartOfAccounts, id=account_id)

    # Check if account has transactions
    has_transactions = account.journal_lines.exists()

    if request.method == 'POST':
        account_name = request.POST.get('account_name')
        description = request.POST.get('description', '')
        is_control_account = request.POST.get('is_control_account') == 'on'
        allows_manual_entries = request.POST.get('allows_manual_entries') == 'on'

        try:
            account.account_name = account_name
            account.description = description
            account.is_control_account = is_control_account
            account.allows_manual_entries = allows_manual_entries

            # Only allow changing structural fields if no transactions
            if not has_transactions:
                gl_code = request.POST.get('gl_code')
                account_type_id = request.POST.get('account_type')
                account_category_id = request.POST.get('account_category')
                parent_account_id = request.POST.get('parent_account')
                branch_id = request.POST.get('branch')

                account.gl_code = gl_code
                account.account_type_id = account_type_id
                account.account_category_id = account_category_id if account_category_id else None
                account.parent_account_id = parent_account_id if parent_account_id else None
                account.branch_id = branch_id if branch_id else None

            account.save()

            messages.success(request, f'GL Account {account.gl_code} updated successfully!')
            return redirect('core:coa_detail', account_id=account.id)
        except Exception as e:
            messages.error(request, f'Error updating account: {str(e)}')

    context = {
        'page_title': f'Edit GL Account: {account.gl_code}',
        'account': account,
        'has_transactions': has_transactions,
        'account_types': AccountType.objects.all(),
        'account_categories': AccountCategory.objects.select_related('account_type'),
        'parent_accounts': ChartOfAccounts.objects.filter(is_control_account=True, is_active=True).exclude(id=account.id),
        'branches': Branch.objects.filter(is_active=True),
    }

    return render(request, 'accounting/coa_form.html', context)


@login_required
@db_transaction.atomic
def coa_post_opening_balance(request, account_id):
    """
    Post an opening (or correcting) balance to a GL account.
    Creates a balanced 2-line journal entry posted immediately.

    Permissions: Director, Admin only
    """
    checker = PermissionChecker(request.user)
    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors and Administrators can post opening balances.')
        raise PermissionDenied

    account = get_object_or_404(
        ChartOfAccounts.objects.select_related('account_type', 'branch'),
        id=account_id
    )

    # Current balance for display
    from django.db.models import Sum as _Sum
    debit_total  = account.journal_lines.aggregate(t=_Sum('debit_amount'))['t']  or Decimal('0')
    credit_total = account.journal_lines.aggregate(t=_Sum('credit_amount'))['t'] or Decimal('0')
    if account.account_type.normal_balance == 'debit':
        current_balance = debit_total - credit_total
    else:
        current_balance = credit_total - debit_total

    if request.method == 'POST':
        form = OpeningBalanceForm(request.POST, account=account)
        if form.is_valid():
            amount           = form.cleaned_data['amount']
            as_of_date       = form.cleaned_data['as_of_date']
            offsetting_acct  = form.cleaned_data['offsetting_account']
            branch           = form.cleaned_data['branch']
            description      = form.cleaned_data['description']

            # Build the 2-line balanced journal entry
            journal = JournalEntry(
                journal_number=JournalEntry.generate_journal_number(),
                entry_type='adjustment',
                status='posted',
                transaction_date=as_of_date,
                posting_date=as_of_date,
                branch=branch,
                description=description,
                reference_number='OPENING-BAL',
                created_by=request.user,
                posted_by=request.user,
            )
            journal.save()

            if account.account_type.normal_balance == 'debit':
                # Asset / Expense: DR this account, CR offsetting
                JournalEntryLine.objects.create(
                    journal_entry=journal, account=account,
                    debit_amount=amount, credit_amount=Decimal('0'),
                    description=description,
                )
                JournalEntryLine.objects.create(
                    journal_entry=journal, account=offsetting_acct,
                    debit_amount=Decimal('0'), credit_amount=amount,
                    description=description,
                )
            else:
                # Liability / Income / Equity: CR this account, DR offsetting
                JournalEntryLine.objects.create(
                    journal_entry=journal, account=account,
                    debit_amount=Decimal('0'), credit_amount=amount,
                    description=description,
                )
                JournalEntryLine.objects.create(
                    journal_entry=journal, account=offsetting_acct,
                    debit_amount=amount, credit_amount=Decimal('0'),
                    description=description,
                )

            messages.success(
                request,
                f'Opening balance of ₦{amount:,.2f} posted as {journal.journal_number}. '
                f'The account balance is now updated.'
            )
            return redirect('core:coa_detail', account_id=account.id)
    else:
        form = OpeningBalanceForm(account=account)

    context = {
        'page_title': f'Post Opening Balance — {account.gl_code}',
        'account': account,
        'current_balance': current_balance,
        'form': form,
    }
    return render(request, 'accounting/coa_opening_balance.html', context)


# =============================================================================
# JOURNAL ENTRY VIEWS
# =============================================================================

@login_required
def journal_entry_list(request):
    """
    Display list of all journal entries with filters

    Permissions: Staff (own), Manager (branch), Director/Admin (all)
    """
    checker = PermissionChecker(request.user)

    # Base queryset
    journals = JournalEntry.objects.select_related(
        'branch', 'created_by', 'posted_by', 'transaction', 'loan', 'savings_account'
    ).prefetch_related('lines')

    # Permission-based filtering
    if checker.is_staff():
        journals = journals.filter(created_by=request.user)
    elif checker.is_manager():
        journals = journals.filter(branch=request.user.branch)

    # Search form
    search_form = JournalEntrySearchForm(request.GET or None)

    if search_form.is_valid():
        journal_number = search_form.cleaned_data.get('journal_number')
        if journal_number:
            journals = journals.filter(journal_number__icontains=journal_number)

        entry_type = search_form.cleaned_data.get('entry_type')
        if entry_type:
            journals = journals.filter(entry_type=entry_type)

        status = search_form.cleaned_data.get('status')
        if status:
            journals = journals.filter(status=status)

        date_from = search_form.cleaned_data.get('date_from')
        date_to = search_form.cleaned_data.get('date_to')
        if date_from and date_to:
            journals = journals.filter(transaction_date__range=[date_from, date_to])

        branch = search_form.cleaned_data.get('branch')
        if branch:
            journals = journals.filter(branch=branch)

    journals = journals.order_by('-transaction_date', '-created_at')

    # Summary statistics
    total_count = journals.count()
    unposted_count = journals.filter(status__in=['draft', 'pending']).count()

    # Pagination
    paginator = Paginator(journals, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Journal Entries',
        'journals': page_obj,
        'search_form': search_form,
        'total_count': total_count,
        'unposted_count': unposted_count,
    }

    return render(request, 'accounting/journal_entry_list.html', context)


@login_required
def journal_entry_detail(request, entry_id):
    """
    Display journal entry details with all lines

    Permissions: Staff (own), Manager (branch), Director/Admin (all)
    """
    checker = PermissionChecker(request.user)

    journal = get_object_or_404(
        JournalEntry.objects.select_related(
            'branch', 'created_by', 'posted_by', 'transaction', 'loan', 'savings_account'
        ).prefetch_related('lines__account', 'lines__client'),
        id=entry_id
    )

    # Permission check
    if checker.is_staff() and journal.created_by != request.user:
        messages.error(request, 'You can only view your own journal entries.')
        raise PermissionDenied
    elif checker.is_manager() and journal.branch != request.user.branch:
        messages.error(request, 'You can only view journal entries from your branch.')
        raise PermissionDenied

    # Calculate totals
    total_debits = journal.get_total_debits()
    total_credits = journal.get_total_credits()
    is_balanced = total_debits == total_credits

    # Managers can post journals in their own branch; directors/HR/admin can post any
    can_post = (
        checker.is_admin_or_director()
        or (checker.is_manager() and journal.branch == request.user.branch)
    )

    context = {
        'page_title': f'Journal Entry: {journal.journal_number}',
        'journal': journal,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'is_balanced': is_balanced,
        'can_post': can_post,
    }

    return render(request, 'accounting/journal_entry_detail.html', context)


@login_required
@db_transaction.atomic
def journal_entry_create(request):
    """
    Create manual journal entry with lines.
    Accepts optional ?transaction_id=<id> to pre-fill details and link the
    resulting journal entry back to the source transaction (fixing audit gaps).

    Permissions: Manager, Director, Admin with accounting permissions
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to create journal entries.')
        raise PermissionDenied

    # ── Resolve optional linked transaction ──────────────────────────────────
    source_transaction = None
    txn_id = request.POST.get('transaction_id') or request.GET.get('transaction_id')
    if txn_id:
        try:
            source_transaction = Transaction.objects.select_related('branch', 'client').get(pk=txn_id)
        except (Transaction.DoesNotExist, ValueError):
            messages.warning(request, 'Linked transaction not found — proceeding without it.')

    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        # Restrict branch choices for managers before validation
        if checker.is_manager() and request.user.branch:
            from core.models import Branch as BranchModel
            form.fields['branch'].queryset = BranchModel.objects.filter(id=request.user.branch.id)
            form.fields['branch'].empty_label = None
            form.fields['branch'].required = True
        formset = JournalEntryLineFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                # Validate balance
                total_debits = sum(
                    f.cleaned_data.get('debit_amount', Decimal('0'))
                    for f in formset
                    if f.cleaned_data and not f.cleaned_data.get('DELETE', False)
                )
                total_credits = sum(
                    f.cleaned_data.get('credit_amount', Decimal('0'))
                    for f in formset
                    if f.cleaned_data and not f.cleaned_data.get('DELETE', False)
                )

                if total_debits != total_credits:
                    messages.error(
                        request,
                        f'Journal entry not balanced! Debits: ₦{total_debits:,.2f} != Credits: ₦{total_credits:,.2f}'
                    )
                else:
                    # Create journal entry
                    journal = form.save(commit=False)
                    journal.created_by = request.user
                    journal.status = 'draft'
                    if source_transaction:
                        journal.transaction = source_transaction
                    journal.save()

                    # Save lines
                    formset.instance = journal
                    formset.save()

                    messages.success(
                        request,
                        f'Journal entry {journal.journal_number} created successfully! Status: Draft'
                    )
                    return redirect('core:journal_entry_detail', entry_id=journal.id)
            except ValidationError as e:
                messages.error(request, f'Validation error: {str(e)}')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-fill form fields from the linked transaction (GET request)
        initial = {}
        if source_transaction:
            initial = {
                'transaction_date': source_transaction.transaction_date,
                'branch': source_transaction.branch,
                'description': (
                    f"{source_transaction.get_transaction_type_display()} — "
                    f"{source_transaction.transaction_ref} — "
                    f"₦{source_transaction.amount:,.2f}"
                ),
                'reference_number': source_transaction.transaction_ref,
                'entry_type': 'correction',
            }
        if checker.is_manager() and request.user.branch:
            # Pre-fill manager's branch
            initial.setdefault('branch', request.user.branch)
        form = JournalEntryForm(initial=initial)
        # Restrict branch dropdown to manager's own branch
        if checker.is_manager() and request.user.branch:
            from core.models import Branch as BranchModel
            form.fields['branch'].queryset = BranchModel.objects.filter(id=request.user.branch.id)
            form.fields['branch'].empty_label = None
            form.fields['branch'].required = True
        formset = JournalEntryLineFormSet()

    context = {
        'page_title': 'Create Manual Journal Entry',
        'form': form,
        'formset': formset,
        'source_transaction': source_transaction,
    }

    return render(request, 'accounting/journal_entry_form.html', context)


@login_required
@db_transaction.atomic
def journal_entry_post(request, entry_id):
    """
    Post/approve a draft or pending journal entry

    Permissions: Director, Admin only
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_admin_or_director() or checker.is_manager()):
        messages.error(request, 'You do not have permission to post journal entries.')
        raise PermissionDenied

    journal = get_object_or_404(JournalEntry, id=entry_id)

    # Managers may only post journals belonging to their own branch
    if checker.is_manager() and journal.branch != request.user.branch:
        messages.error(request, 'You can only post journal entries from your branch.')
        raise PermissionDenied

    if journal.status == 'posted':
        messages.warning(request, 'This journal entry is already posted.')
        return redirect('core:journal_entry_detail', entry_id=journal.id)

    if journal.status == 'reversed':
        messages.error(request, 'Cannot post a reversed journal entry.')
        return redirect('core:journal_entry_detail', entry_id=journal.id)

    if request.method == 'POST':
        # Validate balance
        total_debits = journal.get_total_debits()
        total_credits = journal.get_total_credits()

        if total_debits != total_credits:
            messages.error(
                request,
                f'Cannot post unbalanced journal! Debits: ₦{total_debits:,.2f} != Credits: ₦{total_credits:,.2f}'
            )
            return redirect('core:journal_entry_detail', entry_id=journal.id)

        # Post the journal
        journal.status = 'posted'
        journal.posted_by = request.user
        journal.posted_at = timezone.now()
        journal.posting_date = timezone.now().date()
        journal.save(update_fields=['status', 'posted_by', 'posted_at', 'posting_date', 'updated_at'])

        messages.success(request, f'Journal entry {journal.journal_number} posted successfully!')
        return redirect('core:journal_entry_detail', entry_id=journal.id)

    context = {
        'page_title': f'Post Journal Entry: {journal.journal_number}',
        'journal': journal,
        'total_debits': journal.get_total_debits(),
        'total_credits': journal.get_total_credits(),
    }

    return render(request, 'accounting/journal_entry_post_confirm.html', context)


@login_required
@db_transaction.atomic
def journal_entry_reverse(request, entry_id):
    """
    Reverse a posted journal entry

    Permissions: Director, Admin only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors and Administrators can reverse journal entries.')
        raise PermissionDenied

    journal = get_object_or_404(JournalEntry, id=entry_id)

    if journal.status != 'posted':
        messages.error(request, 'Only posted journal entries can be reversed.')
        return redirect('core:journal_entry_detail', entry_id=journal.id)

    if journal.status == 'reversed':
        messages.warning(request, 'This journal entry has already been reversed.')
        return redirect('core:journal_entry_detail', entry_id=journal.id)

    if request.method == 'POST':
        form = JournalReversalForm(request.POST)

        if form.is_valid():
            reversal_reason = form.cleaned_data['reversal_reason']
            reversal_date = form.cleaned_data['reversal_date']

            # Create reversal entry with opposite signs
            lines = []
            for line in journal.lines.all():
                lines.append({
                    'account_code': line.account.gl_code,
                    'debit': line.credit_amount,  # Swap
                    'credit': line.debit_amount,  # Swap
                    'description': f'Reversal of {journal.journal_number}: {line.description}',
                    'client': line.client
                })

            # Create reversal journal
            reversal_journal = create_journal_entry(
                entry_type='reversal',
                transaction_date=reversal_date,
                branch=journal.branch,
                description=f'REVERSAL of {journal.journal_number}: {reversal_reason}',
                created_by=request.user,
                lines=lines,
                reference_number=f'REV-{journal.journal_number}',
                auto_post=True  # Auto-post reversals
            )

            # Update original journal status
            journal.status = 'reversed'
            journal.save(update_fields=['status', 'updated_at'])

            messages.success(
                request,
                f'Journal entry {journal.journal_number} reversed successfully! '
                f'Reversal entry: {reversal_journal.journal_number}'
            )
            return redirect('core:journal_entry_detail', entry_id=reversal_journal.id)
    else:
        form = JournalReversalForm()

    context = {
        'page_title': f'Reverse Journal Entry: {journal.journal_number}',
        'journal': journal,
        'form': form,
    }

    return render(request, 'accounting/journal_entry_reverse_form.html', context)


# =============================================================================
# FINANCIAL REPORTS VIEWS
# =============================================================================

@login_required
def report_trial_balance(request):
    """
    Generate Trial Balance Report

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view financial reports.')
        raise PermissionDenied

    form = TrialBalanceForm(request.GET or None)
    report_data = None

    if form.is_valid():
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        branch = form.cleaned_data.get('branch')
        account_type = form.cleaned_data.get('account_type')
        show_zero_balances = form.cleaned_data.get('show_zero_balances', False)

        # Get all accounts
        accounts = ChartOfAccounts.objects.filter(is_active=True).select_related('account_type')

        if account_type:
            accounts = accounts.filter(account_type__name=account_type)

        # Calculate balances for each account
        trial_balance = []
        total_debits = Decimal('0')
        total_credits = Decimal('0')

        for account in accounts.order_by('gl_code'):
            # Filter journal lines by date range and branch
            journal_lines = account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__range=[date_from, date_to]
            )

            if branch:
                journal_lines = journal_lines.filter(journal_entry__branch=branch)

            debit_sum = journal_lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            credit_sum = journal_lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

            # Calculate net balance
            if account.account_type.normal_balance == 'debit':
                net_debit = debit_sum - credit_sum if debit_sum > credit_sum else Decimal('0')
                net_credit = credit_sum - debit_sum if credit_sum > debit_sum else Decimal('0')
            else:
                net_credit = credit_sum - debit_sum if credit_sum > debit_sum else Decimal('0')
                net_debit = debit_sum - credit_sum if debit_sum > credit_sum else Decimal('0')

            # Skip zero balances if requested
            if not show_zero_balances and net_debit == 0 and net_credit == 0:
                continue

            trial_balance.append({
                'account': account,
                'debit': net_debit,
                'credit': net_credit
            })

            total_debits += net_debit
            total_credits += net_credit

        report_data = {
            'trial_balance': trial_balance,
            'total_debits': total_debits,
            'total_credits': total_credits,
            'is_balanced': total_debits == total_credits,
            'difference': total_debits - total_credits,
            'date_from': date_from,
            'date_to': date_to,
            'branch': branch,
            'show_zero_balances': show_zero_balances,
        }

        # Handle exports
        export_format = request.GET.get('export')
        if export_format == 'pdf':
            return generate_trial_balance_pdf(report_data, form.cleaned_data)
        elif export_format == 'excel':
            return export_trial_balance_excel(report_data, form.cleaned_data)

    context = {
        'page_title': 'Trial Balance',
        'form': form,
        'report_data': report_data,
    }

    return render(request, 'accounting/report_trial_balance.html', context)


@login_required
def report_profit_loss(request):
    """
    Generate Profit & Loss Statement

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view financial reports.')
        raise PermissionDenied

    form = ProfitLossForm(request.GET or None)
    report_data = None

    if form.is_valid():
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        branch = form.cleaned_data.get('branch')

        # Get income accounts (4000-4999)
        income_accounts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.INCOME,
            is_active=True
        ).order_by('gl_code')

        # Get expense accounts (5000-5999)
        expense_accounts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.EXPENSE,
            is_active=True
        ).order_by('gl_code')

        # Calculate income
        income_items = []
        total_income = Decimal('0')

        for account in income_accounts:
            journal_lines = account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__range=[date_from, date_to]
            )

            if branch:
                journal_lines = journal_lines.filter(journal_entry__branch=branch)

            credit_sum = journal_lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')
            debit_sum = journal_lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            amount = credit_sum - debit_sum  # Income increases with credit

            if amount != 0:
                income_items.append({'account': account, 'amount': amount})
                total_income += amount

        # Calculate expenses
        expense_items = []
        total_expenses = Decimal('0')

        for account in expense_accounts:
            journal_lines = account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__range=[date_from, date_to]
            )

            if branch:
                journal_lines = journal_lines.filter(journal_entry__branch=branch)

            debit_sum = journal_lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            credit_sum = journal_lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')
            amount = debit_sum - credit_sum  # Expense increases with debit

            if amount != 0:
                expense_items.append({'account': account, 'amount': amount})
                total_expenses += amount

        # Calculate net profit/loss
        net_profit = total_income - total_expenses

        report_data = {
            'income_items': income_items,
            'expense_items': expense_items,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_profit': net_profit,
            'date_from': date_from,
            'date_to': date_to,
            'branch': branch,
        }

        # Handle exports
        export_format = request.GET.get('export')
        if export_format == 'pdf':
            return generate_profit_loss_pdf(report_data, form.cleaned_data)
        elif export_format == 'excel':
            return export_profit_loss_excel(report_data, form.cleaned_data)

    context = {
        'page_title': 'Profit & Loss Statement',
        'form': form,
        'report_data': report_data,
    }

    return render(request, 'accounting/report_profit_loss.html', context)


@login_required
def report_balance_sheet(request):
    """
    Generate Balance Sheet

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view financial reports.')
        raise PermissionDenied

    form = BalanceSheetForm(request.GET or None)
    report_data = None

    if form.is_valid():
        as_of_date = form.cleaned_data['as_of_date']
        branch = form.cleaned_data.get('branch')

        # Helper function to calculate account balance
        def calc_balance(account, as_of):
            lines = account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__lte=as_of
            )

            if branch:
                lines = lines.filter(journal_entry__branch=branch)

            debit_sum = lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
            credit_sum = lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

            if account.account_type.normal_balance == 'debit':
                return debit_sum - credit_sum
            else:
                return credit_sum - debit_sum

        # Get assets
        asset_accounts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.ASSET,
            is_active=True
        ).order_by('gl_code')

        assets = []
        total_assets = Decimal('0')
        for account in asset_accounts:
            balance = calc_balance(account, as_of_date)
            if balance != 0:
                assets.append({'account': account, 'balance': balance})
                total_assets += balance

        # Get liabilities
        liability_accounts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.LIABILITY,
            is_active=True
        ).order_by('gl_code')

        liabilities = []
        total_liabilities = Decimal('0')
        for account in liability_accounts:
            balance = calc_balance(account, as_of_date)
            if balance != 0:
                liabilities.append({'account': account, 'balance': balance})
                total_liabilities += balance

        # Get equity
        equity_accounts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.EQUITY,
            is_active=True
        ).order_by('gl_code')

        equity = []
        total_equity = Decimal('0')
        for account in equity_accounts:
            balance = calc_balance(account, as_of_date)
            if balance != 0:
                equity.append({'account': account, 'balance': balance})
                total_equity += balance

        # Include net income in equity so balance sheet balances before
        # income/expense accounts are formally closed to retained earnings.
        income_accts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.INCOME, is_active=True
        )
        expense_accts = ChartOfAccounts.objects.filter(
            account_type__name=AccountType.EXPENSE, is_active=True
        )
        net_income = (
            sum(calc_balance(a, as_of_date) for a in income_accts)
            - sum(calc_balance(a, as_of_date) for a in expense_accts)
        )
        if net_income:
            equity.append({
                'account': None,
                'account_name': 'Net Income (Current Period)',
                'balance': net_income,
            })
            total_equity += net_income

        total_liabilities_equity = total_liabilities + total_equity

        report_data = {
            'assets': assets,
            'liabilities': liabilities,
            'equity': equity,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'total_liabilities_equity': total_liabilities_equity,
            'is_balanced': abs(total_assets - total_liabilities_equity) < Decimal('0.01'),
            'as_of_date': as_of_date,
            'branch': branch,
        }

        # Handle exports
        export_format = request.GET.get('export')
        if export_format == 'pdf':
            return generate_balance_sheet_pdf(report_data, form.cleaned_data)
        elif export_format == 'excel':
            return export_balance_sheet_excel(report_data, form.cleaned_data)

    context = {
        'page_title': 'Balance Sheet',
        'form': form,
        'report_data': report_data,
    }

    return render(request, 'accounting/report_balance_sheet.html', context)


@login_required
def report_general_ledger(request):
    """
    Generate General Ledger for specific account

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view financial reports.')
        raise PermissionDenied

    form = GeneralLedgerForm(request.GET or None)
    report_data = None

    if form.is_valid():
        account = form.cleaned_data['account']
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']
        branch = form.cleaned_data.get('branch')
        show_running_balance = form.cleaned_data.get('show_running_balance', True)

        # Get journal lines for this account
        lines = account.journal_lines.filter(
            journal_entry__status='posted',
            journal_entry__transaction_date__range=[date_from, date_to]
        ).select_related(
            'journal_entry', 'journal_entry__branch', 'client'
        ).order_by('journal_entry__transaction_date', 'journal_entry__created_at')

        if branch:
            lines = lines.filter(journal_entry__branch=branch)

        # Calculate opening balance
        opening_lines = account.journal_lines.filter(
            journal_entry__status='posted',
            journal_entry__transaction_date__lt=date_from
        )

        if branch:
            opening_lines = opening_lines.filter(journal_entry__branch=branch)

        opening_debit = opening_lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0')
        opening_credit = opening_lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0')

        if account.account_type.normal_balance == 'debit':
            opening_balance = opening_debit - opening_credit
        else:
            opening_balance = opening_credit - opening_debit

        # Process lines with running balance
        transactions = []
        running_balance = opening_balance

        for line in lines:
            if account.account_type.normal_balance == 'debit':
                running_balance += line.debit_amount - line.credit_amount
            else:
                running_balance += line.credit_amount - line.debit_amount

            transactions.append({
                'line': line,
                'running_balance': running_balance,
            })

        report_data = {
            'account': account,
            'opening_balance': opening_balance,
            'transactions': transactions,
            'closing_balance': running_balance,
            'date_from': date_from,
            'date_to': date_to,
            'branch': branch,
        }

        # Handle exports
        export_format = request.GET.get('export')
        if export_format == 'pdf':
            return generate_general_ledger_pdf(report_data, form.cleaned_data)
        elif export_format == 'excel':
            return export_general_ledger_excel(report_data, form.cleaned_data)

    context = {
        'page_title': 'General Ledger',
        'form': form,
        'report_data': report_data,
    }

    return render(request, 'accounting/report_general_ledger.html', context)


@login_required
def report_cash_flow(request):
    """
    Generate Cash Flow Statement (simplified)

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view financial reports.')
        raise PermissionDenied

    form = DateRangeForm(request.GET or None)
    report_data = None

    if form.is_valid():
        date_from = form.cleaned_data['date_from']
        date_to = form.cleaned_data['date_to']

        # Get cash account (1010)
        try:
            cash_account = ChartOfAccounts.objects.get(gl_code='1010', is_active=True)

            # Get all cash movements
            cash_lines = cash_account.journal_lines.filter(
                journal_entry__status='posted',
                journal_entry__transaction_date__range=[date_from, date_to]
            ).select_related('journal_entry').order_by('journal_entry__transaction_date')

            # Categorize by transaction type
            operating_activities = []
            investing_activities = []
            financing_activities = []

            operating_total = Decimal('0')
            investing_total = Decimal('0')
            financing_total = Decimal('0')

            for line in cash_lines:
                amount = line.debit_amount - line.credit_amount
                entry_type = line.journal_entry.entry_type

                if entry_type in ['loan_repayment', 'savings_deposit', 'savings_withdrawal', 'fee_collection']:
                    operating_activities.append({'line': line, 'amount': amount})
                    operating_total += amount
                elif entry_type in ['loan_disbursement']:
                    investing_activities.append({'line': line, 'amount': amount})
                    investing_total += amount
                else:
                    financing_activities.append({'line': line, 'amount': amount})
                    financing_total += amount

            net_cash_flow = operating_total + investing_total + financing_total

            report_data = {
                'operating_activities': operating_activities,
                'investing_activities': investing_activities,
                'financing_activities': financing_activities,
                'operating_total': operating_total,
                'investing_total': investing_total,
                'financing_total': financing_total,
                'net_cash_flow': net_cash_flow,
                'date_from': date_from,
                'date_to': date_to,
            }

            # Handle exports
            export_format = request.GET.get('export')
            if export_format == 'pdf':
                return generate_cash_flow_pdf(report_data, form.cleaned_data)
            elif export_format == 'excel':
                return export_cash_flow_excel(report_data, form.cleaned_data)

        except ChartOfAccounts.DoesNotExist:
            messages.error(request, 'Cash account (1010) not found. Please initialize Chart of Accounts.')

    context = {
        'page_title': 'Cash Flow Statement',
        'form': form,
        'report_data': report_data,
    }

    return render(request, 'accounting/report_cash_flow.html', context)


@login_required
def report_transaction_audit(request):
    """
    Transaction Audit Report - shows all transactions with journal entry links

    Permissions: Director, Admin only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors and Administrators can view audit reports.')
        raise PermissionDenied

    # Get all completed transactions
    transactions = Transaction.objects.filter(
        status='completed'
    ).select_related(
        'client', 'branch', 'processed_by', 'loan', 'savings_account'
    ).prefetch_related('journal_entries').order_by('-transaction_date')

    # Apply filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if date_from and date_to:
        transactions = transactions.filter(transaction_date__range=[date_from, date_to])

    transaction_type = request.GET.get('transaction_type')
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    # Identify transactions without journal entries (AUDIT ALERT)
    audit_data = []
    missing_journal_count = 0

    for txn in transactions[:200]:  # Limit for performance
        journal_entries = txn.journal_entries.all()
        has_journal = journal_entries.exists()

        if not has_journal:
            missing_journal_count += 1

        audit_data.append({
            'transaction': txn,
            'has_journal': has_journal,
            'journal_entries': journal_entries
        })

    report_data = {
        'audit_data': audit_data,
        'missing_journal_count': missing_journal_count,
        'total_transactions': transactions.count(),
        'date_from': date_from,
        'date_to': date_to,
    }

    # Handle exports
    export_format = request.GET.get('export')
    if export_format == 'pdf':
        return generate_transaction_audit_pdf(report_data, request.GET)
    elif export_format == 'excel':
        return export_transaction_audit_excel(report_data, request.GET)

    context = {
        'page_title': 'Transaction Audit Log',
        'audit_data': audit_data,
        'missing_journal_count': missing_journal_count,
        'total_transactions': transactions.count(),
    }

    return render(request, 'accounting/report_transaction_audit.html', context)


# =============================================================================
# PAR AGING REPORT
# =============================================================================

@login_required
def report_par_aging(request):
    """
    Portfolio at Risk (PAR) Aging Report

    Buckets all active/overdue loans by days past due:
      - Current (0 days)
      - PAR 1–30
      - PAR 31–60
      - PAR 61–90
      - PAR 90+

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to view this report.')
        raise PermissionDenied

    today = timezone.now().date()

    # Branch filter
    branch_id = request.GET.get('branch')
    loans_qs = (
        Loan.objects.filter(status__in=['active', 'overdue'])
        .select_related('client', 'branch', 'loan_product')
        .exclude(outstanding_balance__lte=Decimal('0.01'))
    )
    if branch_id:
        loans_qs = loans_qs.filter(branch_id=branch_id)

    loans = list(loans_qs)

    buckets = {
        'current': [],
        'par_1_30': [],
        'par_31_60': [],
        'par_61_90': [],
        'par_90plus': [],
    }

    for loan in loans:
        if loan.status == 'active':
            # Check whether technically overdue (grace not yet expired)
            if loan.next_repayment_date:
                grace_days = (
                    loan.loan_product.grace_period_days
                    if loan.loan_product_id and loan.loan_product
                    else 0
                )
                overdue_from = loan.next_repayment_date + timedelta(days=grace_days)
                if overdue_from < today:
                    days = (today - overdue_from).days
                else:
                    days = 0
            else:
                days = 0
        else:
            days = loan.days_overdue

        if days == 0:
            buckets['current'].append((loan, days))
        elif days <= 30:
            buckets['par_1_30'].append((loan, days))
        elif days <= 60:
            buckets['par_31_60'].append((loan, days))
        elif days <= 90:
            buckets['par_61_90'].append((loan, days))
        else:
            buckets['par_90plus'].append((loan, days))

    def _bucket_summary(items):
        count = len(items)
        balance = sum(loan.outstanding_balance for loan, _ in items)
        return {'count': count, 'balance': balance, 'items': items}

    summary = {k: _bucket_summary(v) for k, v in buckets.items()}
    total_balance = sum(s['balance'] for s in summary.values())
    total_count = sum(s['count'] for s in summary.values())

    # Add percentage to each bucket
    for s in summary.values():
        s['pct'] = (
            round(float(s['balance']) / float(total_balance) * 100, 1)
            if total_balance else 0
        )

    # PAR ratio = (PAR 1+ balance) / total * 100
    par_balance = total_balance - summary['current']['balance']
    par_ratio = round(float(par_balance) / float(total_balance) * 100, 1) if total_balance else 0

    branches = Branch.objects.filter(is_active=True).order_by('name')

    context = {
        'page_title': 'Portfolio at Risk (PAR) Aging Report',
        'today': today,
        'summary': summary,
        'total_balance': total_balance,
        'total_count': total_count,
        'par_balance': par_balance,
        'par_ratio': par_ratio,
        'branches': branches,
        'selected_branch': branch_id,
    }

    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_par_aging_excel
        return export_par_aging_excel(context)

    return render(request, 'accounting/report_par_aging.html', context)


# =============================================================================
# LOAN OFFICER PERFORMANCE REPORT
# =============================================================================

@login_required
def report_loan_officer_performance(request):
    """
    Loan Officer Performance Report

    For each staff member: loans disbursed, total disbursement amount,
    repayments collected, total collected, active client count, overdue loan count.

    Permissions: Manager, Director, Admin
    """
    from core.models import User, SavingsAccount
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    today      = timezone.now().date()
    date_from  = request.GET.get('date_from')
    date_to    = request.GET.get('date_to')
    branch_id  = request.GET.get('branch')

    # Default: current month
    if not date_from:
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        date_to = today.isoformat()

    try:
        df = datetime.strptime(date_from, '%Y-%m-%d').date()
        dt = datetime.strptime(date_to,   '%Y-%m-%d').date()
    except (ValueError, TypeError):
        df = today.replace(day=1)
        dt = today

    # Which staff users to include
    staff_qs = User.objects.filter(user_role='staff', is_active=True).select_related('branch')
    if branch_id:
        staff_qs = staff_qs.filter(branch_id=branch_id)
    elif checker.is_manager():
        staff_qs = staff_qs.filter(branch=request.user.branch)

    officers = []
    for officer in staff_qs:
        # Disbursements in period (loans assigned to this officer's clients)
        disbursed_loans = Loan.objects.filter(
            client__assigned_staff=officer,
            disbursement_date__date__gte=df,
            disbursement_date__date__lte=dt,
            status__in=['active', 'overdue', 'completed', 'disbursed'],
        )
        disbursed_count  = disbursed_loans.count()
        disbursed_amount = disbursed_loans.aggregate(
            t=Sum('principal_amount')
        )['t'] or Decimal('0.00')

        # Repayments collected in period
        from core.models import Transaction
        repayments = Transaction.objects.filter(
            processed_by=officer,
            transaction_type='loan_repayment',
            status='completed',
            transaction_date__date__gte=df,
            transaction_date__date__lte=dt,
        )
        repayment_count  = repayments.count()
        repayment_amount = repayments.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        # Active portfolio
        active_loans = Loan.objects.filter(
            client__assigned_staff=officer,
            status__in=['active', 'disbursed'],
        )
        overdue_loans = Loan.objects.filter(
            client__assigned_staff=officer,
            status='overdue',
        )
        active_clients = officer.assigned_clients.filter(is_active=True).count()

        officers.append({
            'officer':          officer,
            'disbursed_count':  disbursed_count,
            'disbursed_amount': disbursed_amount,
            'repayment_count':  repayment_count,
            'repayment_amount': repayment_amount,
            'active_loans':     active_loans.count(),
            'overdue_loans':    overdue_loans.count(),
            'active_clients':   active_clients,
        })

    # Sort by disbursement amount descending
    officers.sort(key=lambda x: x['disbursed_amount'], reverse=True)

    # Pre-calculate column totals for the footer row
    totals = {
        'disbursed_count':  sum(r['disbursed_count']  for r in officers),
        'disbursed_amount': sum(r['disbursed_amount'] for r in officers),
        'repayment_count':  sum(r['repayment_count']  for r in officers),
        'repayment_amount': sum(r['repayment_amount'] for r in officers),
        'active_clients':   sum(r['active_clients']   for r in officers),
        'active_loans':     sum(r['active_loans']     for r in officers),
        'overdue_loans':    sum(r['overdue_loans']    for r in officers),
    }

    branches = Branch.objects.filter(is_active=True).order_by('name')

    context = {
        'page_title':      'Loan Officer Performance Report',
        'officers':        officers,
        'totals':          totals,
        'date_from':       date_from,
        'date_to':         date_to,
        'selected_branch': branch_id,
        'branches':        branches,
        'today':           today,
    }

    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_loan_officer_performance_excel
        return export_loan_officer_performance_excel(context)

    return render(request, 'accounting/report_loan_officer_performance.html', context)


# =============================================================================
# SAVINGS MATURITY REPORT
# =============================================================================

@login_required
def report_savings_maturity(request):
    """
    Savings Maturity Report

    Lists active fixed-deposit savings accounts maturing within a chosen window,
    grouped by time band: overdue, this month, next month, later.

    Permissions: Manager, Director, Admin
    """
    from core.models import SavingsAccount
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    today      = timezone.now().date()
    branch_id  = request.GET.get('branch')
    months_out = int(request.GET.get('months', 3))   # how far ahead to look

    cutoff = today + timedelta(days=months_out * 30)

    qs = (
        SavingsAccount.objects
        .filter(
            status='active',
            savings_product__product_type='fixed',
            maturity_date__isnull=False,
            maturity_date__lte=cutoff,
        )
        .select_related('client', 'branch', 'savings_product')
        .order_by('maturity_date')
    )

    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    elif checker.is_manager():
        qs = qs.filter(branch=request.user.branch)

    # Annotate with days_remaining and band
    overdue    = []
    this_month = []
    next_month = []
    later      = []

    this_month_end = today.replace(day=1) + timedelta(days=32)
    this_month_end = this_month_end.replace(day=1) - timedelta(days=1)
    next_month_end = (this_month_end + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    accounts = []
    for acct in qs:
        days_left = (acct.maturity_date - today).days
        row = {
            'account':   acct,
            'days_left': days_left,
        }
        accounts.append(row)
        if days_left < 0:
            overdue.append(row)
        elif acct.maturity_date <= this_month_end:
            this_month.append(row)
        elif acct.maturity_date <= next_month_end:
            next_month.append(row)
        else:
            later.append(row)

    total_balance = sum(a['account'].balance for a in accounts)

    branches = Branch.objects.filter(is_active=True).order_by('name')

    context = {
        'page_title':      'Savings Maturity Report',
        'overdue':         overdue,
        'this_month':      this_month,
        'next_month':      next_month,
        'later':           later,
        'total_balance':   total_balance,
        'total_count':     len(accounts),
        'selected_branch': branch_id,
        'months_out':      months_out,
        'branches':        branches,
        'today':           today,
    }

    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_savings_maturity_excel
        return export_savings_maturity_excel(context)

    return render(request, 'accounting/report_savings_maturity.html', context)


# =============================================================================
# SYSTEM AUDIT LOG
# =============================================================================

@login_required
def audit_log(request):
    """
    Unified Audit Dashboard

    Tab 1 — Financial Audit: Posted journal entries (who posted, what type, when, amount)
    Tab 2 — Activity Audit: Model-level changes tracked by django-auditlog
             (client approvals, loan status changes, user edits, etc.)

    Permissions: Director and Admin only.
    """
    from auditlog.models import LogEntry

    checker = PermissionChecker(request.user)
    if not checker.is_admin_or_director():
        messages.error(request, 'Only Directors and Administrators can view the audit log.')
        raise PermissionDenied

    tab = request.GET.get('tab', 'financial')

    # ── Shared filters ──────────────────────────────────────────────────────
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')
    user_filter = request.GET.get('user', '')

    # ── Tab 1: Financial (Journal Entries) ──────────────────────────────────
    entry_type_filter = request.GET.get('entry_type', '')
    journal_entries = (
        JournalEntry.objects.filter(status='posted')
        .select_related('created_by', 'posted_by', 'branch', 'loan', 'savings_account')
        .order_by('-posted_at')
    )
    if date_from_str:
        try:
            journal_entries = journal_entries.filter(posting_date__gte=date_from_str)
        except Exception:
            pass
    if date_to_str:
        try:
            journal_entries = journal_entries.filter(posting_date__lte=date_to_str)
        except Exception:
            pass
    if entry_type_filter:
        journal_entries = journal_entries.filter(entry_type=entry_type_filter)
    if user_filter:
        journal_entries = journal_entries.filter(
            Q(created_by__username__icontains=user_filter) |
            Q(created_by__first_name__icontains=user_filter) |
            Q(created_by__last_name__icontains=user_filter)
        )

    journal_paginator = Paginator(journal_entries, 50)
    journal_page = journal_paginator.get_page(request.GET.get('page'))
    entry_type_choices = JournalEntry._meta.get_field('entry_type').choices

    # ── Tab 2: Activity Audit (LogEntry) ────────────────────────────────────
    model_filter = request.GET.get('model', '')
    action_filter = request.GET.get('action', '')

    activity_logs = (
        LogEntry.objects.all()
        .select_related('actor', 'content_type')
        .order_by('-timestamp')
    )
    if date_from_str:
        try:
            activity_logs = activity_logs.filter(timestamp__date__gte=date_from_str)
        except Exception:
            pass
    if date_to_str:
        try:
            activity_logs = activity_logs.filter(timestamp__date__lte=date_to_str)
        except Exception:
            pass
    if user_filter:
        activity_logs = activity_logs.filter(
            Q(actor__username__icontains=user_filter) |
            Q(actor__first_name__icontains=user_filter) |
            Q(actor__last_name__icontains=user_filter)
        )
    if model_filter:
        activity_logs = activity_logs.filter(content_type__model=model_filter.lower())
    if action_filter:
        try:
            activity_logs = activity_logs.filter(action=int(action_filter))
        except ValueError:
            pass

    activity_paginator = Paginator(activity_logs, 50)
    activity_page = activity_paginator.get_page(request.GET.get('page'))

    # Distinct model names for the filter dropdown (only registered models)
    registered_models = [
        'loan', 'client', 'savingsaccount', 'loanpenalty',
        'loanrestructurerequest', 'assignmentrequest', 'collateral',
        'user', 'branch', 'loanproduct', 'savingsproduct',
    ]
    model_labels = {
        'loan': 'Loan', 'client': 'Client', 'savingsaccount': 'Savings Account',
        'loanpenalty': 'Loan Penalty', 'loanrestructurerequest': 'Loan Restructure',
        'assignmentrequest': 'Assignment Request', 'collateral': 'Collateral',
        'user': 'User/Staff', 'branch': 'Branch',
        'loanproduct': 'Loan Product', 'savingsproduct': 'Savings Product',
    }
    action_labels = {
        '0': 'Create', '1': 'Update', '2': 'Delete',
    }

    context = {
        'page_title': 'Audit Dashboard',
        'tab': tab,
        # Financial
        'journal_page': journal_page,
        'journal_total': journal_entries.count(),
        'entry_type_filter': entry_type_filter,
        'entry_type_choices': entry_type_choices,
        # Activity
        'activity_page': activity_page,
        'activity_total': activity_logs.count(),
        'model_filter': model_filter,
        'action_filter': action_filter,
        'registered_models': registered_models,
        'model_labels': model_labels,
        'action_labels': action_labels,
        # Shared
        'date_from': date_from_str,
        'date_to': date_to_str,
        'user_filter': user_filter,
    }

    return render(request, 'accounting/audit_log.html', context)


# =============================================================================
# SUBSIDIARY LEDGER — per client
# =============================================================================

@login_required
def subsidiary_ledger(request, client_id):
    """
    GL-based subsidiary ledger for a specific client.

    Shows all *posted* JournalEntryLine records where ``line.client = client``,
    ordered chronologically.  Supports date-range and GL-account filters.

    Useful for auditing which journal entries touched a client's accounts,
    unlike the client_statement (which shows Transaction objects).

    Permissions: Any staff who can view the client.
    """
    from core.models import Client

    checker = PermissionChecker(request.user)
    client = get_object_or_404(
        Client.objects.select_related('branch', 'assigned_staff'),
        id=client_id,
    )
    if not checker.can_view_client(client):
        raise PermissionDenied

    today = timezone.now().date()

    date_from_str = request.GET.get('date_from', '')
    date_to_str   = request.GET.get('date_to', '')
    account_filter = request.GET.get('account', '')

    # Defaults: last 12 months
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        except ValueError:
            date_from = today.replace(year=today.year - 1)
    else:
        date_from = today.replace(year=today.year - 1)

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
        except ValueError:
            date_to = today
    else:
        date_to = today

    lines_qs = (
        JournalEntryLine.objects
        .filter(
            client=client,
            journal_entry__status='posted',
            journal_entry__transaction_date__range=[date_from, date_to],
        )
        .select_related(
            'account',
            'journal_entry',
            'journal_entry__branch',
            'journal_entry__created_by',
        )
        .order_by('journal_entry__transaction_date', 'id')
    )

    if account_filter:
        lines_qs = lines_qs.filter(account__gl_code=account_filter)

    # Per-account summary
    account_summary = (
        JournalEntryLine.objects
        .filter(
            client=client,
            journal_entry__status='posted',
            journal_entry__transaction_date__range=[date_from, date_to],
        )
        .values('account__gl_code', 'account__account_name')
        .annotate(
            total_debit=Sum('debit_amount'),
            total_credit=Sum('credit_amount'),
        )
        .order_by('account__gl_code')
    )

    totals = lines_qs.aggregate(
        total_debit=Sum('debit_amount'),
        total_credit=Sum('credit_amount'),
    )

    # GL accounts that have lines for this client (for the filter dropdown)
    gl_accounts = (
        JournalEntryLine.objects
        .filter(
            client=client,
            journal_entry__status='posted',
        )
        .values('account__gl_code', 'account__account_name')
        .distinct()
        .order_by('account__gl_code')
    )

    paginator = Paginator(lines_qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page'))

    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_subsidiary_ledger_excel
        return export_subsidiary_ledger_excel(
            client, lines_qs, date_from, date_to, account_summary, totals,
        )

    context = {
        'page_title':      f'Subsidiary Ledger — {client.get_full_name()}',
        'client':          client,
        'page_obj':        page_obj,
        'account_summary': account_summary,
        'totals':          totals,
        'gl_accounts':     gl_accounts,
        'date_from':       date_from,
        'date_to':         date_to,
        'account_filter':  account_filter,
    }
    return render(request, 'accounting/subsidiary_ledger.html', context)
