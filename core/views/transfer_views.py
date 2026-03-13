"""
Inter-Branch Transfer Views
============================
Status flow: pending → approved (in transit) → completed (or cancelled/rejected).

Source journal (on approve, posted at from_branch):
    Dr 1950 Interbranch Transfer Clearing   [amount]
    Cr 1010 Cash In Hand                    [amount]

Destination journal (on complete, posted at to_branch):
    Dr 1010 Cash In Hand                    [amount]
    Cr 1950 Interbranch Transfer Clearing   [amount]
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import InterBranchTransfer, Branch
from core.forms.transfer_forms import TransferCreateForm, TransferApproveForm, TransferCompleteForm
from core.permissions import PermissionChecker
from core.utils.accounting_helpers import create_journal_entry
from core.services.notification_service import notify, notify_role


@login_required
def transfer_list(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    qs = InterBranchTransfer.objects.select_related(
        'from_branch', 'to_branch', 'requested_by', 'approved_by', 'completed_by',
    )
    if checker.is_manager():
        qs = qs.filter(
            Q(from_branch=request.user.branch) | Q(to_branch=request.user.branch)
        )

    status_filter     = request.GET.get('status', '')
    from_branch_filter = request.GET.get('from_branch', '')
    to_branch_filter   = request.GET.get('to_branch', '')

    if status_filter:
        qs = qs.filter(status=status_filter)
    if from_branch_filter:
        qs = qs.filter(from_branch_id=from_branch_filter)
    if to_branch_filter:
        qs = qs.filter(to_branch_id=to_branch_filter)

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 25)
    page_obj  = paginator.get_page(request.GET.get('page'))

    branches = Branch.objects.filter(is_active=True)

    return render(request, 'transfers/list.html', {
        'page_title':        'Inter-Branch Transfers',
        'transfers':         page_obj,
        'status_filter':     status_filter,
        'from_branch_filter': from_branch_filter,
        'to_branch_filter':  to_branch_filter,
        'branches':          branches,
        'checker':           checker,
    })


@login_required
def transfer_create(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    if request.method == 'POST':
        form = TransferCreateForm(request.POST, user=request.user)
        if form.is_valid():
            transfer = form.save(commit=False)
            transfer.requested_by = request.user
            transfer.status       = 'pending'
            transfer.save()
            messages.success(
                request,
                f'Transfer {transfer.transfer_ref} submitted for approval.'
            )
            notify_role(
                roles=['director', 'admin'],
                notification_type='transfer_requested',
                title='Transfer Request Pending Approval',
                message=(
                    f'{request.user.get_full_name()} has requested a transfer of '
                    f'₦{transfer.amount:,.2f} from {transfer.from_branch.name} '
                    f'to {transfer.to_branch.name} (Ref: {transfer.transfer_ref}).'
                ),
                is_urgent=True,
            )
            return redirect('core:transfer_detail', transfer_id=transfer.id)
    else:
        form = TransferCreateForm(user=request.user)

    return render(request, 'transfers/create.html', {
        'page_title': 'Request Inter-Branch Transfer',
        'form':       form,
        'checker':    checker,
    })


@login_required
def transfer_detail(request, transfer_id):
    transfer = get_object_or_404(
        InterBranchTransfer.objects.select_related(
            'from_branch', 'to_branch',
            'requested_by', 'approved_by', 'completed_by', 'rejected_by',
            'source_journal', 'destination_journal',
        ),
        id=transfer_id,
    )
    checker = PermissionChecker(request.user)
    if checker.is_manager():
        if (transfer.from_branch != request.user.branch
                and transfer.to_branch != request.user.branch):
            raise PermissionDenied
    elif not checker.is_admin_or_director():
        raise PermissionDenied

    return render(request, 'transfers/detail.html', {
        'page_title': f'Transfer — {transfer.transfer_ref}',
        'transfer':   transfer,
        'checker':    checker,
    })


@login_required
@transaction.atomic
def transfer_approve(request, transfer_id):
    """Director/Admin: approve or reject a pending transfer."""
    transfer = get_object_or_404(
        InterBranchTransfer.objects.select_related('from_branch', 'to_branch', 'requested_by'),
        id=transfer_id,
    )
    checker = PermissionChecker(request.user)
    if not checker.is_admin_or_director():
        raise PermissionDenied('Only directors and administrators can approve transfers.')

    if transfer.status != 'pending':
        messages.error(
            request,
            f'Transfer is "{transfer.get_status_display()}" and cannot be actioned.'
        )
        return redirect('core:transfer_detail', transfer_id=transfer.id)

    if request.method == 'POST':
        form = TransferApproveForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']

            if decision == 'approve':
                try:
                    source_journal = create_journal_entry(
                        entry_type='interbranch_transfer',
                        transaction_date=timezone.now().date(),
                        branch=transfer.from_branch,
                        description=(
                            f'Interbranch Transfer Out: {transfer.transfer_ref} '
                            f'→ {transfer.to_branch.name}'
                        ),
                        created_by=request.user,
                        lines=[
                            {
                                'account_code': '1950',
                                'debit':  float(transfer.amount),
                                'credit': 0,
                                'description': f'Transfer clearing out — {transfer.transfer_ref}',
                            },
                            {
                                'account_code': '1010',
                                'debit':  0,
                                'credit': float(transfer.amount),
                                'description': f'Cash out for transfer — {transfer.transfer_ref}',
                            },
                        ],
                        reference_number=transfer.transfer_ref,
                        auto_post=True,
                    )
                except (ValidationError, Exception) as exc:
                    messages.error(request, f'Journal entry failed: {exc}')
                    return redirect('core:transfer_detail', transfer_id=transfer.id)

                transfer.status         = 'approved'
                transfer.approved_by    = request.user
                transfer.approved_at    = timezone.now()
                transfer.source_journal = source_journal
                transfer.save(update_fields=[
                    'status', 'approved_by', 'approved_at', 'source_journal', 'updated_at',
                ])
                messages.success(
                    request,
                    f'Transfer {transfer.transfer_ref} approved. '
                    f'Source journal {source_journal.journal_number} posted.'
                )
                notify(
                    user=transfer.requested_by,
                    notification_type='transfer_approved',
                    title='Transfer Approved',
                    message=(
                        f'Your transfer request {transfer.transfer_ref} '
                        f'(₦{transfer.amount:,.2f} from {transfer.from_branch.name} '
                        f'to {transfer.to_branch.name}) has been approved and is now in transit.'
                    ),
                )

            else:  # reject
                rejection_reason = form.cleaned_data.get('rejection_reason', '')
                transfer.status           = 'rejected'
                transfer.rejected_by      = request.user
                transfer.rejected_at      = timezone.now()
                transfer.rejection_reason = rejection_reason
                transfer.save(update_fields=[
                    'status', 'rejected_by', 'rejected_at', 'rejection_reason', 'updated_at',
                ])
                messages.warning(request, f'Transfer {transfer.transfer_ref} rejected.')
                notify(
                    user=transfer.requested_by,
                    notification_type='transfer_rejected',
                    title='Transfer Rejected',
                    message=(
                        f'Your transfer request {transfer.transfer_ref} '
                        f'(₦{transfer.amount:,.2f} from {transfer.from_branch.name} '
                        f'to {transfer.to_branch.name}) was rejected. '
                        f'Reason: {rejection_reason or "No reason given"}.'
                    ),
                    is_urgent=True,
                )

            return redirect('core:transfer_detail', transfer_id=transfer.id)
    else:
        form = TransferApproveForm()

    return render(request, 'transfers/approve.html', {
        'page_title': f'Review Transfer — {transfer.transfer_ref}',
        'transfer':   transfer,
        'form':       form,
        'checker':    checker,
    })


@login_required
@transaction.atomic
def transfer_complete(request, transfer_id):
    """
    Director/Admin OR destination branch manager: confirm cash receipt.
    Posts destination journal: Dr 1010 / Cr 1950 at to_branch.
    """
    transfer = get_object_or_404(
        InterBranchTransfer.objects.select_related('from_branch', 'to_branch'),
        id=transfer_id,
    )
    checker = PermissionChecker(request.user)

    # Allowed: director/admin, OR manager of the destination branch
    is_dest_manager = (
        checker.is_manager()
        and hasattr(request.user, 'branch')
        and request.user.branch == transfer.to_branch
    )
    if not (checker.is_admin_or_director() or is_dest_manager):
        raise PermissionDenied(
            'Only the destination branch manager or a director/admin can complete a transfer.'
        )

    if transfer.status != 'approved':
        messages.error(request, 'Only approved transfers can be completed.')
        return redirect('core:transfer_detail', transfer_id=transfer.id)

    if request.method == 'POST':
        form = TransferCompleteForm(request.POST)
        if form.is_valid():
            notes = form.cleaned_data.get('notes', '')
            try:
                dest_journal = create_journal_entry(
                    entry_type='interbranch_transfer',
                    transaction_date=timezone.now().date(),
                    branch=transfer.to_branch,
                    description=(
                        f'Interbranch Transfer In: {transfer.transfer_ref} '
                        f'← {transfer.from_branch.name}'
                    ),
                    created_by=request.user,
                    lines=[
                        {
                            'account_code': '1010',
                            'debit':  float(transfer.amount),
                            'credit': 0,
                            'description': f'Cash received for transfer — {transfer.transfer_ref}',
                        },
                        {
                            'account_code': '1950',
                            'debit':  0,
                            'credit': float(transfer.amount),
                            'description': f'Transfer clearing in — {transfer.transfer_ref}',
                        },
                    ],
                    reference_number=transfer.transfer_ref,
                    auto_post=True,
                )
            except (ValidationError, Exception) as exc:
                messages.error(request, f'Journal entry failed: {exc}')
                return redirect('core:transfer_detail', transfer_id=transfer.id)

            transfer.status              = 'completed'
            transfer.completed_by        = request.user
            transfer.completed_at        = timezone.now()
            transfer.destination_journal = dest_journal
            if notes:
                transfer.notes = (transfer.notes + '\n' + notes).strip() if transfer.notes else notes
            transfer.save(update_fields=[
                'status', 'completed_by', 'completed_at',
                'destination_journal', 'notes', 'updated_at',
            ])
            messages.success(
                request,
                f'Transfer {transfer.transfer_ref} completed. '
                f'Destination journal {dest_journal.journal_number} posted.'
            )
            notify(
                user=transfer.requested_by,
                notification_type='transfer_completed',
                title='Transfer Completed',
                message=(
                    f'Transfer {transfer.transfer_ref} of ₦{transfer.amount:,.2f} '
                    f'has been received at {transfer.to_branch.name} and is now complete.'
                ),
            )
            return redirect('core:transfer_detail', transfer_id=transfer.id)
    else:
        form = TransferCompleteForm()

    return render(request, 'transfers/complete.html', {
        'page_title': f'Confirm Transfer Receipt — {transfer.transfer_ref}',
        'transfer':   transfer,
        'form':       form,
        'checker':    checker,
    })
