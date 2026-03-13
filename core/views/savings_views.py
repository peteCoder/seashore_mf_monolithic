"""
Savings Views
=============

Views for savings account management and transaction posting
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.utils import timezone
from decimal import Decimal

from core.models import (
    SavingsAccount, SavingsProduct, SavingsDepositPosting,
    SavingsWithdrawalPosting, Client, Branch, Transaction
)
from core.services.notification_service import notify, notify_role
from core.forms.savings_forms import (
    SavingsAccountForm, SavingsAccountSearchForm, SavingsAccountApprovalForm,
    SavingsDepositPostingForm, BulkSavingsDepositPostingForm,
    SavingsWithdrawalPostingForm, BulkSavingsWithdrawalPostingForm,
    ApproveSavingsTransactionForm
)
from core.permissions import PermissionChecker


# =============================================================================
# SAVINGS ACCOUNT VIEWS
# =============================================================================

@login_required
def savings_account_list(request):
    """
    List all savings accounts with filtering

    Permissions:
    - Staff see their assigned clients' accounts
    - Managers see accounts in their branch
    - Directors/Admins see all accounts
    """
    checker = PermissionChecker(request.user)

    # Base queryset
    accounts = SavingsAccount.objects.select_related(
        'client', 'branch', 'savings_product'
    ).filter(deleted_at__isnull=True)

    # Permission filtering
    accounts = checker.filter_savings_accounts(accounts)

    # Search and filters
    form = SavingsAccountSearchForm(request.GET)
    if form.is_valid():
        search = form.cleaned_data.get('search')
        if search:
            accounts = accounts.filter(
                Q(account_number__icontains=search) |
                Q(client__first_name__icontains=search) |
                Q(client__last_name__icontains=search) |
                Q(client__client_id__icontains=search)
            )

        status = form.cleaned_data.get('status')
        if status:
            accounts = accounts.filter(status=status)

        savings_product = form.cleaned_data.get('savings_product')
        if savings_product:
            accounts = accounts.filter(savings_product=savings_product)

        branch = form.cleaned_data.get('branch')
        if branch:
            accounts = accounts.filter(branch=branch)

        date_from = form.cleaned_data.get('date_from')
        if date_from:
            accounts = accounts.filter(date_opened__gte=date_from)

        date_to = form.cleaned_data.get('date_to')
        if date_to:
            accounts = accounts.filter(date_opened__lte=date_to)

    accounts = accounts.order_by('-created_at')

    # Pagination
    paginator = Paginator(accounts, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Summary
    summary = {
        'total_accounts': accounts.count(),
        'active_accounts': accounts.filter(status='active').count(),
        'pending_accounts': accounts.filter(status='pending').count(),
        'total_balance': accounts.aggregate(Sum('balance'))['balance__sum'] or Decimal('0.00'),
    }

    context = {
        'page_title': 'Savings Accounts',
        'accounts': page_obj,
        'form': form,
        'summary': summary,
        'checker': checker,
    }

    return render(request, 'savings/account_list.html', context)


@login_required
def savings_account_detail(request, account_id):
    """
    Display savings account details with tabs

    Permissions:
    - Must have access to this account (staff/manager/admin based)
    """
    account = get_object_or_404(
        SavingsAccount.objects.select_related('client', 'branch', 'savings_product'),
        id=account_id
    )

    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_edit_savings_account(account):
        raise PermissionDenied("You don't have permission to view this account")

    # Get recent transactions
    transactions = Transaction.objects.filter(
        savings_account=account
    ).select_related('processed_by').order_by('-transaction_date')[:20]

    # Get pending postings
    deposit_postings = account.deposit_postings.filter(status='pending').order_by('-submitted_at')[:10]
    withdrawal_postings = account.withdrawal_postings.filter(status='pending').order_by('-submitted_at')[:10]

    context = {
        'page_title': f'Account {account.account_number}',
        'account': account,
        'transactions': transactions,
        'deposit_postings': deposit_postings,
        'withdrawal_postings': withdrawal_postings,
        'checker': checker,
    }

    return render(request, 'savings/account_detail.html', context)


@login_required
@transaction.atomic
def savings_account_create(request):
    """
    Create a new savings account

    Permissions:
    - All staff can create accounts
    """
    checker = PermissionChecker(request.user)

    if not checker.can_create_savings_account():
        raise PermissionDenied("You don't have permission to create savings accounts")

    if request.method == 'POST':
        form = SavingsAccountForm(request.POST, user=request.user)

        if form.is_valid():
            account = form.save(commit=False)
            account.status = 'pending'
            account.save()

            # Notify branch manager that a new savings account needs approval
            notify_role(
                roles='manager',
                branch=account.branch,
                notification_type='savings_created',
                title='New Savings Account Pending Approval',
                message=f'A new savings account {account.account_number} for {account.client.get_full_name()} has been created and is awaiting approval.',
                related_savings=account,
                related_client=account.client,
                exclude_user=request.user,
            )

            messages.success(
                request,
                f'Savings account {account.account_number} created successfully. '
                f'Awaiting approval from manager.'
            )
            return redirect('core:savings_account_detail', account_id=account.id)
    else:
        form = SavingsAccountForm(user=request.user)

    context = {
        'page_title': 'Create Savings Account',
        'form': form,
        'checker': checker,
    }

    return render(request, 'savings/account_form.html', context)


@login_required
@transaction.atomic
def savings_account_approve(request, account_id):
    """
    Approve or reject a savings account

    Permissions:
    - Manager/Director/Admin only
    - Managers can only approve accounts in their branch
    """
    account = get_object_or_404(SavingsAccount, id=account_id)
    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_approve_accounts():
        raise PermissionDenied("You don't have permission to approve accounts")

    if checker.is_manager():
        if account.branch != request.user.branch:
            raise PermissionDenied("You can only approve accounts in your branch")

    if account.status != 'pending':
        messages.error(request, f"Cannot approve account with status: {account.get_status_display()}")
        return redirect('core:savings_account_detail', account_id=account.id)

    if request.method == 'POST':
        form = SavingsAccountApprovalForm(request.POST, account=account)

        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            if decision == 'approve':
                account.status = 'active'
                account.approved_by = request.user
                account.approved_at = timezone.now()
                account.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

                messages.success(
                    request,
                    f'Savings account {account.account_number} approved successfully.'
                )
                staff = account.client.assigned_staff
                if staff:
                    notify(
                        user=staff,
                        notification_type='savings_approved',
                        title='Savings Account Approved',
                        message=f'Savings account {account.account_number} for {account.client.get_full_name()} has been approved.',
                        related_savings=account,
                        related_client=account.client,
                    )
                notify_role(
                    roles='manager',
                    branch=account.branch,
                    notification_type='savings_approved',
                    title='Savings Account Approved',
                    message=f'Savings account {account.account_number} for {account.client.get_full_name()} has been approved by {request.user.get_full_name()}.',
                    related_savings=account,
                    related_client=account.client,
                    exclude_user=request.user,
                )
            else:
                account.status = 'rejected'
                account.rejection_reason = notes
                account.save(update_fields=['status', 'rejection_reason', 'updated_at'])

                messages.warning(
                    request,
                    f'Savings account {account.account_number} rejected.'
                )
                notify_role(
                    roles='manager',
                    branch=account.branch,
                    notification_type='transaction_rejected',
                    title='Savings Account Rejected',
                    message=f'Savings account {account.account_number} for {account.client.get_full_name()} was rejected by {request.user.get_full_name()}. Reason: {notes or "No reason given"}',
                    related_savings=account,
                    related_client=account.client,
                    is_urgent=True,
                    exclude_user=request.user,
                )

            return redirect('core:savings_account_detail', account_id=account.id)
    else:
        form = SavingsAccountApprovalForm(account=account)

    context = {
        'page_title': f'Approve Account - {account.account_number}',
        'account': account,
        'form': form,
        'checker': checker,
    }

    return render(request, 'savings/account_approve.html', context)


# =============================================================================
# DEPOSIT POSTING VIEWS
# =============================================================================

@login_required
@transaction.atomic
def savings_deposit_post(request, account_id=None):
    """
    Post a single deposit

    Permissions:
    - All staff can post deposits (filtered to accessible accounts)
    """
    checker = PermissionChecker(request.user)

    # If account_id provided, pre-fill the form
    account = None
    if account_id:
        account = get_object_or_404(SavingsAccount, id=account_id)

        # Permission check
        if not checker.can_edit_savings_account(account):
            raise PermissionDenied("You don't have permission to post deposits for this account")

    if request.method == 'POST':
        form = SavingsDepositPostingForm(request.POST, user=request.user)

        if form.is_valid():
            posting = form.save(commit=False)
            posting.submitted_by = request.user
            posting.status = 'pending'

            # If posting from account detail page, set the account
            if account:
                posting.savings_account = account

            posting.save()

            # Notify branch manager that a deposit needs approval
            notify_role(
                roles='manager',
                branch=posting.savings_account.branch,
                notification_type='deposit_pending',
                title='Deposit Pending Approval',
                message=f'A deposit of ₦{posting.amount:,.2f} for savings account {posting.savings_account.account_number} ({posting.savings_account.client.get_full_name()}) has been submitted and is awaiting approval.',
                related_savings=posting.savings_account,
                related_client=posting.savings_account.client,
                exclude_user=request.user,
            )

            messages.success(
                request,
                f'Deposit posting {posting.posting_ref} submitted successfully. '
                f'Awaiting approval from manager/director.'
            )
            return redirect('core:savings_transaction_list')
    else:
        initial = {}
        if account:
            initial['savings_account'] = account.id
        form = SavingsDepositPostingForm(initial=initial, user=request.user)

    context = {
        'page_title': 'Post Savings Deposit',
        'form': form,
        'account': account,
        'checker': checker,
        'today': timezone.now().date().isoformat(),
    }

    return render(request, 'savings/deposit_post.html', context)


@login_required
@transaction.atomic
def savings_deposit_post_bulk(request):
    """
    Post multiple deposits at once

    Permissions:
    - All staff can post deposits
    """
    checker = PermissionChecker(request.user)

    # Get active accounts for this user
    base_queryset = SavingsAccount.objects.filter(
        status__in=['active', 'pending']
    ).select_related('client', 'branch', 'savings_product')

    if checker.is_staff():
        accounts = base_queryset.filter(client__assigned_staff=request.user)
    elif checker.is_manager():
        accounts = base_queryset.filter(branch=request.user.branch)
    else:
        accounts = base_queryset

    accounts = accounts.order_by('client__first_name', 'client__last_name')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        payment_date = request.POST.get('payment_date')
        payment_reference = request.POST.get('payment_reference', '')

        created_postings = []
        errors = []

        # Process each selected account
        for key, value in request.POST.items():
            if key.startswith('account_'):
                account_id = value
                amount_key = f'amount_{account_id}'
                amount = request.POST.get(amount_key)

                if amount:
                    amount = amount.replace(',', '')
                if amount and float(amount) > 0:
                    try:
                        account = SavingsAccount.objects.get(id=account_id)

                        # Validate amount
                        amount_decimal = Decimal(amount)

                        # Create posting
                        posting = SavingsDepositPosting.objects.create(
                            savings_account=account,
                            amount=amount_decimal,
                            payment_method=payment_method,
                            payment_reference=payment_reference,
                            payment_date=payment_date,
                            submitted_by=request.user,
                            status='pending'
                        )
                        created_postings.append(posting)

                    except SavingsAccount.DoesNotExist:
                        errors.append(f"Account {account_id} not found")
                    except Exception as e:
                        errors.append(f"Error processing account {account_id}: {str(e)}")

        if created_postings:
            messages.success(
                request,
                f'Successfully posted {len(created_postings)} deposit(s). '
                f'Awaiting approval from manager/director.'
            )
            # Notify branch managers (one notification per branch)
            branches_to_notify = {p.savings_account.branch for p in created_postings if p.savings_account.branch}
            for branch in branches_to_notify:
                notify_role(
                    roles='manager',
                    branch=branch,
                    notification_type='deposit_pending',
                    title='Bulk Deposits Pending Approval',
                    message=f'{len(created_postings)} deposit posting(s) submitted by {request.user.get_full_name()} are awaiting approval.',
                    exclude_user=request.user,
                )

        if errors:
            for error in errors:
                messages.warning(request, error)

        if created_postings or errors:
            return redirect('core:savings_transaction_list')

        messages.error(request, "No deposits were selected or amounts entered.")

    context = {
        'page_title': 'Bulk Post Savings Deposits',
        'accounts': accounts,
        'checker': checker,
        'today': timezone.now().date().isoformat(),
    }

    return render(request, 'savings/deposit_post_bulk.html', context)


# =============================================================================
# WITHDRAWAL POSTING VIEWS
# =============================================================================

@login_required
@transaction.atomic
def savings_withdrawal_post(request, account_id=None):
    """
    Post a single withdrawal

    Permissions:
    - All staff can post withdrawals (filtered to accessible accounts)
    """
    checker = PermissionChecker(request.user)

    # If account_id provided, pre-fill the form
    account = None
    if account_id:
        account = get_object_or_404(SavingsAccount, id=account_id)

        # Permission check
        if not checker.can_edit_savings_account(account):
            raise PermissionDenied("You don't have permission to post withdrawals for this account")

    if request.method == 'POST':
        form = SavingsWithdrawalPostingForm(request.POST, user=request.user)

        if form.is_valid():
            posting = form.save(commit=False)
            posting.submitted_by = request.user
            posting.status = 'pending'

            # If posting from account detail page, set the account
            if account:
                posting.savings_account = account

            posting.save()

            # Notify branch manager that a withdrawal needs approval
            notify_role(
                roles='manager',
                branch=posting.savings_account.branch,
                notification_type='withdrawal_pending',
                title='Withdrawal Pending Approval',
                message=f'A withdrawal of ₦{posting.amount:,.2f} from savings account {posting.savings_account.account_number} ({posting.savings_account.client.get_full_name()}) has been submitted and is awaiting approval.',
                related_savings=posting.savings_account,
                related_client=posting.savings_account.client,
                exclude_user=request.user,
            )

            messages.success(
                request,
                f'Withdrawal posting {posting.posting_ref} submitted successfully. '
                f'Awaiting approval from manager/director.'
            )
            return redirect('core:savings_transaction_list')
    else:
        initial = {}
        if account:
            initial['savings_account'] = account.id
        form = SavingsWithdrawalPostingForm(initial=initial, user=request.user)

    context = {
        'page_title': 'Post Savings Withdrawal',
        'form': form,
        'account': account,
        'checker': checker,
        'today': timezone.now().date().isoformat(),
    }

    return render(request, 'savings/withdrawal_post.html', context)


@login_required
@transaction.atomic
def savings_withdrawal_post_bulk(request):
    """
    Post multiple withdrawals at once

    Permissions:
    - All staff can post withdrawals
    """
    checker = PermissionChecker(request.user)

    # Get active accounts for this user
    base_queryset = SavingsAccount.objects.filter(
        status='active'
    ).select_related('client', 'branch', 'savings_product')

    if checker.is_staff():
        accounts = base_queryset.filter(client__assigned_staff=request.user)
    elif checker.is_manager():
        accounts = base_queryset.filter(branch=request.user.branch)
    else:
        accounts = base_queryset

    accounts = accounts.order_by('client__first_name', 'client__last_name')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        withdrawal_date = request.POST.get('withdrawal_date')
        payment_reference = request.POST.get('payment_reference', '')

        created_postings = []
        errors = []

        # Process each selected account
        for key, value in request.POST.items():
            if key.startswith('account_'):
                account_id = value
                amount_key = f'amount_{account_id}'
                amount = request.POST.get(amount_key)

                if amount and float(amount) > 0:
                    try:
                        account = SavingsAccount.objects.get(id=account_id)

                        # Validate amount
                        amount_decimal = Decimal(amount)

                        # Basic validation
                        can_withdraw, message = account.can_withdraw(amount_decimal)
                        if not can_withdraw:
                            errors.append(f"{account.account_number}: {message}")
                            continue

                        # Create posting
                        posting = SavingsWithdrawalPosting.objects.create(
                            savings_account=account,
                            amount=amount_decimal,
                            payment_method=payment_method,
                            payment_reference=payment_reference,
                            withdrawal_date=withdrawal_date,
                            submitted_by=request.user,
                            status='pending'
                        )
                        created_postings.append(posting)

                    except SavingsAccount.DoesNotExist:
                        errors.append(f"Account {account_id} not found")
                    except Exception as e:
                        errors.append(f"Error processing account {account_id}: {str(e)}")

        if created_postings:
            messages.success(
                request,
                f'Successfully posted {len(created_postings)} withdrawal(s). '
                f'Awaiting approval from manager/director.'
            )
            # Notify branch managers (one notification per branch)
            branches_to_notify = {p.savings_account.branch for p in created_postings if p.savings_account.branch}
            for branch in branches_to_notify:
                notify_role(
                    roles='manager',
                    branch=branch,
                    notification_type='withdrawal_pending',
                    title='Bulk Withdrawals Pending Approval',
                    message=f'{len(created_postings)} withdrawal posting(s) submitted by {request.user.get_full_name()} are awaiting approval.',
                    exclude_user=request.user,
                )

        if errors:
            for error in errors:
                messages.warning(request, error)

        if created_postings or errors:
            return redirect('core:savings_transaction_list')

        messages.error(request, "No withdrawals were selected or amounts entered.")

    context = {
        'page_title': 'Bulk Post Savings Withdrawals',
        'accounts': accounts,
        'checker': checker,
        'today': timezone.now().date().isoformat(),
    }

    return render(request, 'savings/withdrawal_post_bulk.html', context)


# =============================================================================
# TRANSACTION APPROVAL VIEWS
# =============================================================================

@login_required
def savings_transaction_list(request):
    """
    List all transaction postings (deposits and withdrawals)

    Permissions:
    - Staff see their own postings
    - Managers see postings in their branch
    - Directors/Admins see all postings
    """
    checker = PermissionChecker(request.user)

    # Get transaction type filter
    transaction_type = request.GET.get('type', 'all')  # all, deposit, withdrawal
    status_filter = request.GET.get('status', '')  # pending, approved, rejected

    # Get deposit postings
    deposit_postings = SavingsDepositPosting.objects.select_related(
        'savings_account', 'client', 'branch', 'submitted_by', 'reviewed_by'
    )

    # Get withdrawal postings
    withdrawal_postings = SavingsWithdrawalPosting.objects.select_related(
        'savings_account', 'client', 'branch', 'submitted_by', 'reviewed_by'
    )

    # Permission filtering
    if checker.is_staff():
        deposit_postings = deposit_postings.filter(
            Q(submitted_by=request.user) |
            Q(savings_account__client__assigned_staff=request.user)
        )
        withdrawal_postings = withdrawal_postings.filter(
            Q(submitted_by=request.user) |
            Q(savings_account__client__assigned_staff=request.user)
        )
    elif checker.is_manager():
        deposit_postings = deposit_postings.filter(branch=request.user.branch)
        withdrawal_postings = withdrawal_postings.filter(branch=request.user.branch)

    # Status filtering
    if status_filter == 'pending_deposits':
        deposit_postings = deposit_postings.filter(status='pending')
        withdrawal_postings = withdrawal_postings.none()
    elif status_filter == 'pending_withdrawals':
        withdrawal_postings = withdrawal_postings.filter(status='pending')
        deposit_postings = deposit_postings.none()
    elif status_filter in ('approved', 'rejected', 'pending'):
        deposit_postings = deposit_postings.filter(status=status_filter)
        withdrawal_postings = withdrawal_postings.filter(status=status_filter)

    # Combine postings based on type filter
    if transaction_type == 'deposit':
        # Only deposits
        postings = list(deposit_postings)
    elif transaction_type == 'withdrawal':
        # Only withdrawals
        postings = list(withdrawal_postings)
    else:
        # All postings
        postings = list(deposit_postings) + list(withdrawal_postings)

    # Sort by submitted_at
    postings.sort(key=lambda x: x.submitted_at, reverse=True)

    # Pagination
    paginator = Paginator(postings, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Summary
    all_deposits = SavingsDepositPosting.objects.all()
    all_withdrawals = SavingsWithdrawalPosting.objects.all()

    if checker.is_staff():
        all_deposits = all_deposits.filter(
            Q(submitted_by=request.user) |
            Q(savings_account__client__assigned_staff=request.user)
        )
        all_withdrawals = all_withdrawals.filter(
            Q(submitted_by=request.user) |
            Q(savings_account__client__assigned_staff=request.user)
        )
    elif checker.is_manager():
        all_deposits = all_deposits.filter(branch=request.user.branch)
        all_withdrawals = all_withdrawals.filter(branch=request.user.branch)

    total_deposits_count = all_deposits.count()
    total_withdrawals_count = all_withdrawals.count()
    approved_deposit_amount = all_deposits.filter(status='approved').aggregate(
        Sum('amount')
    )['amount__sum'] or Decimal('0.00')
    approved_withdrawal_amount = all_withdrawals.filter(status='approved').aggregate(
        Sum('amount')
    )['amount__sum'] or Decimal('0.00')

    summary = {
        'total_deposits': total_deposits_count,
        'total_withdrawals': total_withdrawals_count,
        'total_count': total_deposits_count + total_withdrawals_count,
        'pending_deposits': all_deposits.filter(status='pending').count(),
        'pending_withdrawals': all_withdrawals.filter(status='pending').count(),
        'pending_deposit_amount': all_deposits.filter(status='pending').aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0.00'),
        'pending_withdrawal_amount': all_withdrawals.filter(status='pending').aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0.00'),
        'approved_deposit_amount': approved_deposit_amount,
        'approved_withdrawal_amount': approved_withdrawal_amount,
        'approved_amount': approved_deposit_amount + approved_withdrawal_amount,
    }

    context = {
        'page_title': 'Savings Transaction Postings',
        'postings': page_obj,
        'transaction_type': transaction_type,
        'status_filter': status_filter,
        'summary': summary,
        'checker': checker,
    }

    return render(request, 'savings/transaction_list.html', context)


@login_required
@transaction.atomic
def savings_transaction_approve(request, posting_type, posting_id):
    """
    Approve or reject a single transaction posting

    Parameters:
    - posting_type: 'deposit' or 'withdrawal'

    Permissions:
    - Manager/Director/Admin only
    - Managers can only approve postings in their branch
    """
    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_approve_accounts():
        raise PermissionDenied("You don't have permission to approve transactions")

    # Get the posting based on type
    if posting_type == 'deposit':
        posting = get_object_or_404(SavingsDepositPosting, id=posting_id)
    elif posting_type == 'withdrawal':
        posting = get_object_or_404(SavingsWithdrawalPosting, id=posting_id)
    else:
        raise ValueError("Invalid posting type")

    # Branch check for managers
    if checker.is_manager():
        if posting.branch != request.user.branch:
            raise PermissionDenied("You can only approve postings in your branch")

    if posting.status != 'pending':
        messages.error(request, f"Cannot approve posting with status: {posting.get_status_display()}")
        return redirect('core:savings_transaction_list')

    if request.method == 'POST':
        form = ApproveSavingsTransactionForm(request.POST, posting=posting)

        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            try:
                if decision == 'approve':
                    posting.approve(approved_by=request.user)
                    messages.success(
                        request,
                        f'{posting_type.capitalize()} posting {posting.posting_ref} approved successfully. '
                        f'Account balance updated.'
                    )
                    notify(
                        user=posting.submitted_by,
                        notification_type='transaction_approved',
                        title=f'{posting_type.capitalize()} Approved',
                        message=f'{posting_type.capitalize()} of ₦{posting.amount:,.2f} for account {posting.savings_account.account_number} has been approved.',
                        related_savings=posting.savings_account,
                        related_client=posting.savings_account.client,
                    )
                    notify_role(
                        roles='manager',
                        branch=posting.savings_account.branch,
                        notification_type='transaction_approved',
                        title=f'{posting_type.capitalize()} Approved',
                        message=f'{posting_type.capitalize()} of ₦{posting.amount:,.2f} for account {posting.savings_account.account_number} ({posting.savings_account.client.get_full_name()}) approved by {request.user.get_full_name()}.',
                        related_savings=posting.savings_account,
                        related_client=posting.savings_account.client,
                        exclude_user=request.user,
                    )
                else:
                    posting.reject(rejected_by=request.user, reason=notes)
                    messages.warning(
                        request,
                        f'{posting_type.capitalize()} posting {posting.posting_ref} rejected.'
                    )
                    notify(
                        user=posting.submitted_by,
                        notification_type='transaction_rejected',
                        title=f'{posting_type.capitalize()} Rejected',
                        message=f'{posting_type.capitalize()} posting {posting.posting_ref} for account {posting.savings_account.account_number} was rejected. Reason: {notes or "No reason given"}',
                        related_savings=posting.savings_account,
                        related_client=posting.savings_account.client,
                        is_urgent=True,
                    )
                    notify_role(
                        roles='manager',
                        branch=posting.savings_account.branch,
                        notification_type='transaction_rejected',
                        title=f'{posting_type.capitalize()} Rejected',
                        message=f'{posting_type.capitalize()} posting {posting.posting_ref} for account {posting.savings_account.account_number} ({posting.savings_account.client.get_full_name()}) rejected by {request.user.get_full_name()}. Reason: {notes or "No reason given"}',
                        related_savings=posting.savings_account,
                        related_client=posting.savings_account.client,
                        is_urgent=True,
                        exclude_user=request.user,
                    )

                return redirect('core:savings_transaction_list')

            except ValidationError as e:
                messages.error(request, str(e))
    else:
        form = ApproveSavingsTransactionForm(posting=posting)

    # Calculate impact preview
    if posting_type == 'deposit':
        balance_after = posting.savings_account.balance + posting.amount
    else:
        balance_after = posting.savings_account.balance - posting.amount

    context = {
        'page_title': f'Approve {posting_type.capitalize()} - {posting.posting_ref}',
        'posting': posting,
        'posting_type': posting_type,
        'form': form,
        'balance_after': balance_after,
        'checker': checker,
    }

    return render(request, 'savings/transaction_approve.html', context)


@login_required
@transaction.atomic
def savings_transaction_approve_bulk(request):
    """
    Approve multiple transaction postings at once

    Permissions:
    - Manager/Director/Admin only
    """
    checker = PermissionChecker(request.user)

    if not checker.can_approve_accounts():
        raise PermissionDenied("You don't have permission to approve transactions")

    if request.method == 'POST':
        action = request.POST.get('action')  # approve or reject
        notes = request.POST.get('notes', '')

        approved_count = 0
        rejected_count = 0
        error_count = 0

        # Process deposits
        for key, value in request.POST.items():
            if key.startswith('deposit_'):
                posting_id = value
                try:
                    posting = SavingsDepositPosting.objects.get(id=posting_id, status='pending')

                    # Branch check for managers
                    if checker.is_manager() and posting.branch != request.user.branch:
                        error_count += 1
                        continue

                    if action == 'approve':
                        posting.approve(approved_by=request.user)
                        approved_count += 1
                    else:
                        posting.reject(rejected_by=request.user, reason=notes)
                        rejected_count += 1

                except SavingsDepositPosting.DoesNotExist:
                    error_count += 1
                except ValidationError:
                    error_count += 1

        # Process withdrawals
        for key, value in request.POST.items():
            if key.startswith('withdrawal_'):
                posting_id = value
                try:
                    posting = SavingsWithdrawalPosting.objects.get(id=posting_id, status='pending')

                    # Branch check for managers
                    if checker.is_manager() and posting.branch != request.user.branch:
                        error_count += 1
                        continue

                    if action == 'approve':
                        posting.approve(approved_by=request.user)
                        approved_count += 1
                    else:
                        posting.reject(rejected_by=request.user, reason=notes)
                        rejected_count += 1

                except SavingsWithdrawalPosting.DoesNotExist:
                    error_count += 1
                except ValidationError:
                    error_count += 1

        # Messages
        if approved_count > 0:
            messages.success(request, f'Successfully approved {approved_count} posting(s).')

        if rejected_count > 0:
            messages.warning(request, f'Rejected {rejected_count} posting(s).')

        if error_count > 0:
            messages.error(request, f'Failed to process {error_count} posting(s).')

        return redirect('core:savings_transaction_list')

    return redirect('core:savings_transaction_list')
