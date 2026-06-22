"""
Group Savings Views
===================

Handles GroupSavingsAccount creation/approval and GroupSavingsPosting
submission/approval.

Entry points:
  - /group-savings/                   → list all group savings accounts
  - /group-savings/create/            → create account (optionally pre-filled with group)
  - /group-savings/<id>/              → account detail + posting history
  - /group-savings/<id>/approve/      → approve/reject account
  - /group-savings/<id>/post/         → submit a new posting for an account
  - /group-savings/postings/<id>/     → posting detail
  - /group-savings/postings/<id>/approve/ → approve/reject posting
"""

import datetime as _dt
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.models import (
    ClientGroup, Client, GroupSavingsAccount, GroupSavingsPosting, GroupSavingsPostingItem,
    SavingsProduct,
)
from core.forms.group_savings_forms import (
    GroupSavingsAccountForm, GroupSavingsPostingApproveForm,
)
from core.permissions import PermissionChecker
from core.services.notification_service import notify_role


# =============================================================================
# ACCOUNT LIST
# =============================================================================

@login_required
def group_savings_account_list(request):
    """All group savings accounts visible to this user."""
    checker = PermissionChecker(request.user)

    qs = checker.filter_group_savings_accounts(
        GroupSavingsAccount.objects.select_related('group', 'branch', 'savings_product', 'created_by')
    )

    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(account_number__icontains=search) |
            Q(group__name__icontains=search) |
            Q(group__code__icontains=search)
        )

    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    qs = qs.order_by('-created_at')

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    summary = {
        'total': qs.count(),
        'active': qs.filter(status='active').count(),
        'pending': qs.filter(status='pending').count(),
        'total_balance': qs.filter(status='active').aggregate(s=Sum('balance'))['s'] or Decimal('0.00'),
    }

    return render(request, 'groups/savings/account_list.html', {
        'page_title': 'Group Savings Accounts',
        'page_obj': page_obj,
        'search': search,
        'status_filter': status,
        'summary': summary,
        'checker': checker,
    })


# =============================================================================
# ACCOUNT DETAIL
# =============================================================================

@login_required
def group_savings_account_detail(request, account_id):
    """Account detail with posting history."""
    checker = PermissionChecker(request.user)

    account = get_object_or_404(
        GroupSavingsAccount.objects.select_related('group', 'branch', 'savings_product', 'created_by'),
        id=account_id,
    )

    if not checker.can_view_group_savings_account(account):
        raise PermissionDenied

    postings = account.postings.select_related('submitted_by', 'approved_by').order_by('-collection_date', '-created_at')

    paginator = Paginator(postings, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'groups/savings/account_detail.html', {
        'page_title': f'Group Savings — {account.account_number}',
        'account': account,
        'page_obj': page_obj,
        'checker': checker,
        'can_post': checker.can_post_group_savings(account),
        'can_approve': checker.can_approve_group_savings(),
    })


# =============================================================================
# ACCOUNT CREATE
# =============================================================================

@login_required
@db_transaction.atomic
def group_savings_account_create(request):
    """Create a new group savings account (starts as pending). Staff cannot do this manually."""
    checker = PermissionChecker(request.user)

    if not checker.can_create_group_savings_account():
        raise PermissionDenied

    group = None
    group_id = request.GET.get('group') or request.POST.get('group')
    if group_id:
        group = get_object_or_404(ClientGroup, id=group_id)
        if checker.is_manager() and group.branch != request.user.branch:
            raise PermissionDenied

    if request.method == 'POST':
        form = GroupSavingsAccountForm(request.POST, user=request.user, group=group)
        if form.is_valid():
            account = form.save(commit=False)
            account.branch = account.group.branch
            account.savings_product = SavingsProduct.objects.filter(
                product_type='group_savings', is_active=True
            ).first()
            account.status = 'pending'
            account.created_by = request.user
            account.save()

            notify_role(
                roles='manager',
                branch=account.branch,
                notification_type='savings_created',
                title='New Group Savings Account Pending Approval',
                message=(
                    f'{request.user.get_full_name()} created a group savings account '
                    f'({account.account_number}) for group "{account.group.name}". '
                    f'Awaiting your approval.'
                ),
                exclude_user=request.user,
            )
            messages.success(request, f'Group savings account {account.account_number} created. Awaiting approval.')
            return redirect('core:group_savings_account_detail', account_id=account.id)
    else:
        form = GroupSavingsAccountForm(user=request.user, group=group)

    return render(request, 'groups/savings/account_form.html', {
        'page_title': 'Create Group Savings Account',
        'form': form,
        'group': group,
        'checker': checker,
    })


# =============================================================================
# ACCOUNT APPROVE
# =============================================================================

@login_required
@db_transaction.atomic
def group_savings_account_approve(request, account_id):
    """Approve or reject a pending group savings account."""
    checker = PermissionChecker(request.user)
    if not checker.can_approve_group_savings():
        raise PermissionDenied

    account = get_object_or_404(GroupSavingsAccount, id=account_id)

    if checker.is_manager() and account.branch != request.user.branch:
        raise PermissionDenied

    if account.status != 'pending':
        messages.warning(request, 'This account is not pending approval.')
        return redirect('core:group_savings_account_detail', account_id=account.id)

    if request.method == 'POST':
        decision = request.POST.get('decision')
        notes = request.POST.get('notes', '')

        if decision == 'approve':
            account.status = 'active'
            account.approved_by = request.user
            account.approved_at = timezone.now()
            account.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
            messages.success(request, f'Group savings account {account.account_number} approved.')
        else:
            if not notes:
                messages.error(request, 'Please provide a reason for rejection.')
                return redirect('core:group_savings_account_approve', account_id=account.id)
            account.status = 'closed'
            account.save(update_fields=['status', 'updated_at'])
            messages.warning(request, f'Group savings account {account.account_number} rejected.')

        return redirect('core:group_savings_account_detail', account_id=account.id)

    return render(request, 'groups/savings/account_approve.html', {
        'page_title': f'Approve Account — {account.account_number}',
        'account': account,
        'checker': checker,
    })


# =============================================================================
# POST GROUP SAVINGS (submit a posting)
# =============================================================================

@login_required
@db_transaction.atomic
def group_savings_post(request, account_id):
    """
    Submit a group savings posting for one collection event.
    Staff enters per-member amounts; total is auto-calculated.
    """
    checker = PermissionChecker(request.user)

    account = get_object_or_404(
        GroupSavingsAccount.objects.select_related('group', 'branch'),
        id=account_id,
    )

    if account.status != 'active':
        messages.error(request, 'Can only post to an active group savings account.')
        return redirect('core:group_savings_account_detail', account_id=account.id)

    if not checker.can_post_group_savings(account):
        raise PermissionDenied

    members = account.group.members.filter(
        is_active=True, approval_status='approved'
    ).order_by('first_name', 'last_name')

    recent_postings = account.postings.select_related('submitted_by').order_by('-collection_date', '-created_at')[:10]

    if request.method == 'POST':
        items_data = []
        cumulative = Decimal('0.00')

        for member in members:
            key = f'amount_{member.id}'
            raw = request.POST.get(key, '').replace(',', '').strip()
            if raw:
                try:
                    amt = Decimal(raw)
                    if amt > 0:
                        items_data.append({'client': member, 'amount': amt})
                        cumulative += amt
                except InvalidOperation:
                    pass

        collection_date_raw = request.POST.get('collection_date', '').strip()
        notes = request.POST.get('notes', '').strip()

        errors = []
        if not items_data:
            errors.append('Enter at least one member amount.')
        if not collection_date_raw:
            errors.append('Collection date is required.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'groups/savings/posting_form.html', {
                'page_title': f'Post Group Savings — {account.group.name}',
                'account': account,
                'members': members,
                'checker': checker,
                'today': timezone.now().date().isoformat(),
                'recent_postings': recent_postings,
            })

        import datetime as _dt
        try:
            collection_date = _dt.date.fromisoformat(collection_date_raw)
        except ValueError:
            messages.error(request, 'Invalid collection date.')
            return render(request, 'groups/savings/posting_form.html', {
                'page_title': f'Post Group Savings — {account.group.name}',
                'account': account,
                'members': members,
                'checker': checker,
                'today': timezone.now().date().isoformat(),
                'recent_postings': recent_postings,
            })

        posting = GroupSavingsPosting.objects.create(
            group_savings_account=account,
            collection_date=collection_date,
            total_amount=cumulative,
            notes=notes,
            submitted_by=request.user,
            status='pending',
        )

        for item in items_data:
            GroupSavingsPostingItem.objects.create(
                posting=posting,
                client=item['client'],
                amount=item['amount'],
            )

        notify_role(
            roles='manager',
            branch=account.branch,
            notification_type='deposit_pending',
            title='Group Savings Posting Awaiting Approval',
            message=(
                f'{request.user.get_full_name()} submitted a group savings posting '
                f'of ₦{cumulative:,.2f} for group "{account.group.name}" '
                f'({posting.posting_ref}) — awaiting your approval.'
            ),
            exclude_user=request.user,
        )
        messages.success(
            request,
            f'Posting {posting.posting_ref} submitted (₦{cumulative:,.2f}, {len(items_data)} member(s)). '
            f'Awaiting manager approval.'
        )
        return redirect('core:group_savings_posting_detail', posting_id=posting.id)

    return render(request, 'groups/savings/posting_form.html', {
        'page_title': f'Post Group Savings — {account.group.name}',
        'account': account,
        'members': members,
        'checker': checker,
        'today': timezone.now().date().isoformat(),
        'recent_postings': recent_postings,
    })


# =============================================================================
# POSTING DETAIL
# =============================================================================

@login_required
def group_savings_posting_detail(request, posting_id):
    """Read-only detail of a single group savings posting."""
    checker = PermissionChecker(request.user)

    posting = get_object_or_404(
        GroupSavingsPosting.objects.select_related(
            'group_savings_account__group',
            'group_savings_account__branch',
            'submitted_by', 'approved_by', 'rejected_by',
        ),
        id=posting_id,
    )
    account = posting.group_savings_account

    if not checker.can_view_group_savings_account(account):
        raise PermissionDenied

    items = posting.items.select_related('client').order_by('created_at')

    return render(request, 'groups/savings/posting_detail.html', {
        'page_title': f'Posting {posting.posting_ref}',
        'posting': posting,
        'account': account,
        'items': items,
        'checker': checker,
    })


# =============================================================================
# POSTING APPROVE
# =============================================================================

@login_required
@db_transaction.atomic
def group_savings_posting_approve(request, posting_id):
    """Approve or reject a pending group savings posting."""
    checker = PermissionChecker(request.user)
    if not checker.can_approve_group_savings():
        raise PermissionDenied

    posting = get_object_or_404(
        GroupSavingsPosting.objects.select_related(
            'group_savings_account__group',
            'group_savings_account__branch',
            'submitted_by',
        ).select_for_update(),
        id=posting_id,
    )
    account = posting.group_savings_account

    if checker.is_manager() and account.branch != request.user.branch:
        raise PermissionDenied

    if posting.status != 'pending':
        messages.warning(request, 'This posting has already been processed.')
        return redirect('core:group_savings_posting_detail', posting_id=posting.id)

    if request.method == 'POST':
        form = GroupSavingsPostingApproveForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')
            raw_date = form.cleaned_data.get('transaction_date')
            txn_date = raw_date or posting.collection_date

            if decision == 'approve':
                try:
                    txn = account.deposit(
                        amount=posting.total_amount,
                        processed_by=request.user,
                        description=f'Group savings posting {posting.posting_ref} — {account.group.name}',
                        transaction_date=txn_date,
                    )
                    posting.status = 'approved'
                    posting.approved_by = request.user
                    posting.approved_at = timezone.now()
                    posting.transaction = txn
                    posting.save(update_fields=['status', 'approved_by', 'approved_at', 'transaction', 'updated_at'])

                    messages.success(
                        request,
                        f'Posting {posting.posting_ref} approved. '
                        f'₦{posting.total_amount:,.2f} credited to {account.account_number}.'
                    )
                except (ValidationError, ValueError) as exc:
                    messages.error(request, str(exc))
                    return redirect('core:group_savings_posting_approve', posting_id=posting.id)

            else:
                posting.status = 'rejected'
                posting.rejected_by = request.user
                posting.rejected_at = timezone.now()
                posting.rejection_reason = notes
                posting.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason', 'updated_at'])
                messages.warning(request, f'Posting {posting.posting_ref} rejected.')

            return redirect('core:group_savings_posting_detail', posting_id=posting.id)
    else:
        form = GroupSavingsPostingApproveForm(initial={'transaction_date': posting.collection_date})

    items = posting.items.select_related('client').order_by('created_at')

    return render(request, 'groups/savings/posting_approve.html', {
        'page_title': f'Approve Posting — {posting.posting_ref}',
        'posting': posting,
        'account': account,
        'items': items,
        'form': form,
        'checker': checker,
    })
