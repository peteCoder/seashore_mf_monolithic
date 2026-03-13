"""
Client Group Views
==================

CRUD operations and member management for client groups
"""

import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.db import transaction
from django.utils import timezone

from core.models import ClientGroup, Client, GroupMembershipRequest
from core.services.notification_service import notify, notify_role
from core.forms.group_forms import (
    ClientGroupForm, ClientGroupSearchForm, AddMemberForm,
    BulkAddMembersForm, UpdateMemberRoleForm, ApproveGroupForm,
    ApproveMemberForm, BulkApproveMembersForm
)
from core.permissions import PermissionChecker


# =============================================================================
# GROUP LIST VIEW
# =============================================================================

@login_required
def group_list(request):
    """
    Display paginated list of client groups with search and filters

    Permissions: All authenticated users (filtered by branch access)
    """
    checker = PermissionChecker(request.user)

    # Base queryset filtered by permissions
    groups = checker.filter_groups(ClientGroup.objects.all())

    # Search form
    search_form = ClientGroupSearchForm(request.GET or None)

    # Apply filters
    if search_form.is_valid():
        search = search_form.cleaned_data.get('search')
        if search:
            groups = groups.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search)
            )

        branch = search_form.cleaned_data.get('branch')
        if branch:
            groups = groups.filter(branch=branch)

        group_type = search_form.cleaned_data.get('group_type')
        if group_type:
            groups = groups.filter(group_type=group_type)

        status = search_form.cleaned_data.get('status')
        if status:
            groups = groups.filter(status=status)

        loan_officer = search_form.cleaned_data.get('loan_officer')
        if loan_officer:
            groups = groups.filter(loan_officer=loan_officer)

    # Annotate with member count and pending requests
    groups = groups.annotate(
        pending_requests_count=Count(
            'membership_requests',
            filter=Q(membership_requests__status='pending')
        )
    ).order_by('-created_at')

    # Pagination
    paginator = Paginator(groups, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Client Groups',
        'groups': page_obj,
        'search_form': search_form,
        'total_count': groups.count(),
        'checker': checker,
    }

    return render(request, 'groups/list.html', context)


# =============================================================================
# GROUP DETAIL VIEW
# =============================================================================

@login_required
def group_detail(request, group_id):
    """
    Display comprehensive group information including members

    Permissions: All authenticated users (filtered by branch access)
    """
    checker = PermissionChecker(request.user)

    group = get_object_or_404(
        ClientGroup.objects.annotate(
            pending_requests_count=Count(
                'membership_requests',
                filter=Q(membership_requests__status='pending')
            )
        ),
        id=group_id
    )

    # Check permission
    if not checker.can_view_group(group):
        messages.error(request, 'You do not have permission to view this group.')
        raise PermissionDenied

    # Get active members
    active_members = group.members.filter(
        is_active=True,
        approval_status='approved'
    ).select_related('branch').order_by('group_role', 'first_name')

    # Get pending membership requests
    pending_requests = group.membership_requests.filter(
        status='pending'
    ).select_related('client', 'requested_by').order_by('-requested_at')

    # Get recent approved/rejected requests
    recent_requests = group.membership_requests.filter(
        status__in=['approved', 'rejected']
    ).select_related('client', 'reviewed_by').order_by('-reviewed_at')[:10]

    context = {
        'page_title': f'Group: {group.name}',
        'group': group,
        'active_members': active_members,
        'pending_requests': pending_requests,
        'recent_requests': recent_requests,
        'checker': checker,
    }

    return render(request, 'groups/detail.html', context)


# =============================================================================
# GROUP CREATE VIEW
# =============================================================================

@login_required
def group_create(request):
    """
    Create new client group (awaiting approval)

    Permissions: Staff, Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_staff() or checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to create groups.')
        raise PermissionDenied

    if request.method == 'POST':
        form = ClientGroupForm(request.POST, user=request.user)

        if form.is_valid():
            group = form.save(commit=False)
            group.status = 'pending'  # New groups await approval
            group.approval_status = 'pending'
            group.created_by = request.user
            group.save()

            # Notify branch manager that a new group needs approval
            notify_role(
                roles='manager',
                branch=group.branch,
                notification_type='group_created',
                title='New Group Pending Approval',
                message=f'A new client group "{group.name}" ({group.code}) has been created by {request.user.get_full_name()} and is awaiting approval.',
                exclude_user=request.user,
            )

            messages.success(
                request,
                f'Group {group.name} ({group.code}) created successfully! Awaiting approval.'
            )
            return redirect('core:group_detail', group_id=group.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ClientGroupForm(user=request.user)

    context = {
        'page_title': 'Create Client Group',
        'form': form,
        'is_create': True,
        'locked_loan_officer': form.locked_loan_officer,
    }

    return render(request, 'groups/form.html', context)


# =============================================================================
# GROUP UPDATE VIEW
# =============================================================================

@login_required
def group_update(request, group_id):
    """
    Update existing client group

    Permissions: Manager (own branch), Director, Admin
    """
    checker = PermissionChecker(request.user)

    group = get_object_or_404(ClientGroup, id=group_id)

    # Check permission
    if not checker.can_edit_group(group):
        messages.error(request, 'You do not have permission to edit this group.')
        raise PermissionDenied

    if request.method == 'POST':
        form = ClientGroupForm(request.POST, instance=group, user=request.user)

        if form.is_valid():
            group = form.save()
            messages.success(request, f'Group {group.name} updated successfully!')
            return redirect('core:group_detail', group_id=group.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ClientGroupForm(instance=group, user=request.user)

    context = {
        'page_title': f'Edit Group: {group.name}',
        'form': form,
        'group': group,
        'is_create': False,
        'locked_loan_officer': form.locked_loan_officer,
    }

    return render(request, 'groups/form.html', context)


# =============================================================================
# GROUP APPROVE VIEW
# =============================================================================

@login_required
def group_approve(request, group_id):
    """
    Approve or reject a pending group

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to approve groups.')
        raise PermissionDenied

    group = get_object_or_404(ClientGroup, id=group_id)

    if group.status != 'pending':
        messages.warning(request, 'This group is not pending approval.')
        return redirect('core:group_detail', group_id=group.id)

    if request.method == 'POST':
        form = ApproveGroupForm(request.POST)

        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            if decision == 'approve':
                group.status = 'active'
                group.approval_status = 'approved'
                group.approved_by = request.user
                group.approval_date = timezone.now()
                group.is_active = True
                group.save()

                messages.success(request, f'Group {group.name} approved successfully!')

                # Notify the group creator
                if group.created_by and group.created_by != request.user:
                    notify(
                        user=group.created_by,
                        notification_type='group_created',
                        title='Group Approved',
                        message=f'Your client group "{group.name}" ({group.code}) has been approved by {request.user.get_full_name()}.',
                    )
            else:
                group.status = 'inactive'
                group.approval_status = 'rejected'
                group.approved_by = request.user
                group.approval_date = timezone.now()
                group.is_active = False
                group.save()

                messages.warning(request, f'Group {group.name} rejected.')

                # Notify the group creator
                if group.created_by and group.created_by != request.user:
                    notify(
                        user=group.created_by,
                        notification_type='group_created',
                        title='Group Rejected',
                        message=f'Your client group "{group.name}" ({group.code}) has been rejected by {request.user.get_full_name()}. Notes: {notes or "None"}',
                        is_urgent=True,
                    )

            return redirect('core:group_detail', group_id=group.id)
    else:
        form = ApproveGroupForm()

    context = {
        'page_title': f'Approve Group: {group.name}',
        'group': group,
        'form': form,
    }

    return render(request, 'groups/approve.html', context)


# =============================================================================
# ADD MEMBER VIEW (Single)
# =============================================================================

@login_required
def group_add_member(request, group_id):
    """
    Add a single member to a group (awaiting approval)

    Permissions: Staff, Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    group = get_object_or_404(ClientGroup, id=group_id)

    # Check permission
    if not checker.can_edit_group(group):
        messages.error(request, 'You do not have permission to add members to this group.')
        raise PermissionDenied

    if request.method == 'POST':
        form = AddMemberForm(request.POST, group=group)

        if form.is_valid():
            client = form.cleaned_data['client']
            group_role = form.cleaned_data['group_role']

            # Check if client can be added
            can_add, reason = group.can_add_member(client)
            if not can_add:
                messages.error(request, reason)
                return redirect('core:group_detail', group_id=group.id)

            # Create membership request
            try:
                membership_request = GroupMembershipRequest.objects.create(
                    group=group,
                    client=client,
                    requested_role=group_role,
                    status='pending',
                    requested_by=request.user
                )

                notify_role(
                    roles='manager',
                    branch=group.branch,
                    notification_type='group_member_added',
                    title='New Group Member Pending Approval',
                    message=(
                        f'{request.user.get_full_name()} added {client.full_name} '
                        f'to group "{group.name}" ({group.code}). '
                        f'Membership is awaiting your approval.'
                    ),
                    exclude_user=request.user,
                )

                messages.success(
                    request,
                    f'{client.full_name} has been added to {group.name}. Awaiting approval.'
                )
                return redirect('core:group_detail', group_id=group.id)
            except Exception as e:
                messages.error(request, f'Error adding member: {str(e)}')
    else:
        form = AddMemberForm(group=group)

    context = {
        'page_title': f'Add Member to {group.name}',
        'group': group,
        'form': form,
    }

    return render(request, 'groups/add_member.html', context)


# =============================================================================
# BULK ADD MEMBERS VIEW
# =============================================================================

@login_required
def group_add_members_bulk(request, group_id):
    """
    Add multiple members to a group at once (awaiting approval)

    Permissions: Staff, Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    group = get_object_or_404(ClientGroup, id=group_id)

    # Check permission
    if not checker.can_edit_group(group):
        messages.error(request, 'You do not have permission to add members to this group.')
        raise PermissionDenied

    if request.method == 'POST':
        form = BulkAddMembersForm(request.POST, group=group)

        if form.is_valid():
            clients = form.cleaned_data['clients']
            default_role = form.cleaned_data['default_role']

            added_count = 0
            skipped = []

            with transaction.atomic():
                for client in clients:
                    # Check if client can be added
                    can_add, reason = group.can_add_member(client)
                    if not can_add:
                        skipped.append(f"{client.full_name}: {reason}")
                        continue

                    # Create membership request
                    try:
                        GroupMembershipRequest.objects.create(
                            group=group,
                            client=client,
                            requested_role=default_role,
                            status='pending',
                            requested_by=request.user
                        )
                        added_count += 1
                    except Exception as e:
                        skipped.append(f"{client.full_name}: {str(e)}")

            if added_count > 0:
                messages.success(
                    request,
                    f'{added_count} member(s) added to {group.name}. Awaiting approval.'
                )
                notify_role(
                    roles='manager',
                    branch=group.branch,
                    notification_type='group_member_added',
                    title='New Group Members Pending Approval',
                    message=(
                        f'{request.user.get_full_name()} added {added_count} member(s) '
                        f'to group "{group.name}" ({group.code}). '
                        f'Membership requests are awaiting your approval.'
                    ),
                    exclude_user=request.user,
                )
            if skipped:
                messages.warning(
                    request,
                    f'Some members could not be added: {", ".join(skipped[:5])}'
                )

            return redirect('core:group_detail', group_id=group.id)
    else:
        form = BulkAddMembersForm(group=group)

    # Serialize available clients as JSON for the JS picker
    clients_qs = form.fields['clients'].queryset
    clients_json = json.dumps([
        {
            'id': str(c.id),
            'name': c.full_name,
            'client_id': c.client_id,
        }
        for c in clients_qs
    ])

    # Restore previously selected IDs when form is re-displayed with errors
    selected_ids = json.dumps(
        [str(pk) for pk in request.POST.getlist('clients')]
        if request.method == 'POST' else []
    )

    context = {
        'page_title': f'Add Multiple Members to {group.name}',
        'group': group,
        'form': form,
        'clients_json': clients_json,
        'selected_ids': selected_ids,
    }

    return render(request, 'groups/add_members_bulk.html', context)


# =============================================================================
# APPROVE MEMBER VIEW (Single)
# =============================================================================

@login_required
def group_approve_member(request, request_id):
    """
    Approve or reject a single pending member request

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to approve members.')
        raise PermissionDenied

    membership_request = get_object_or_404(
        GroupMembershipRequest.objects.select_related('group', 'client'),
        id=request_id
    )

    if membership_request.status != 'pending':
        messages.warning(request, 'This membership request is not pending.')
        return redirect('core:group_detail', group_id=membership_request.group.id)

    if request.method == 'POST':
        form = ApproveMemberForm(request.POST)

        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            try:
                with transaction.atomic():
                    if decision == 'approve':
                        membership_request.approve(request.user)
                        messages.success(
                            request,
                            f'{membership_request.client.full_name} approved for {membership_request.group.name}!'
                        )
                        if membership_request.client.assigned_staff:
                            notify(
                                user=membership_request.client.assigned_staff,
                                notification_type='group_assigned',
                                title='Client Added to Group',
                                message=f'{membership_request.client.full_name} has been approved as a member of group {membership_request.group.name}.',
                                related_client=membership_request.client,
                            )
                    else:
                        membership_request.reject(request.user, notes)
                        messages.warning(
                            request,
                            f'{membership_request.client.full_name} membership rejected.'
                        )
            except ValidationError as e:
                messages.error(request, str(e))

            return redirect('core:group_detail', group_id=membership_request.group.id)
    else:
        form = ApproveMemberForm()

    context = {
        'page_title': 'Approve Member Request',
        'membership_request': membership_request,
        'form': form,
    }

    return render(request, 'groups/approve_member.html', context)


# =============================================================================
# BULK APPROVE MEMBERS VIEW
# =============================================================================

@login_required
def group_approve_members_bulk(request, group_id):
    """
    Bulk approve or reject pending member requests

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        messages.error(request, 'You do not have permission to approve members.')
        raise PermissionDenied

    group = get_object_or_404(ClientGroup, id=group_id)

    # Get all pending requests for this group
    pending_requests = group.membership_requests.filter(
        status='pending'
    ).select_related('client')

    if not pending_requests.exists():
        messages.warning(request, 'No pending member requests for this group.')
        return redirect('core:group_detail', group_id=group.id)

    if request.method == 'POST':
        form = BulkApproveMembersForm(request.POST)

        if form.is_valid():
            action = form.cleaned_data['action']
            member_ids = form.cleaned_data['member_ids'].split(',')
            notes = form.cleaned_data.get('notes', '')

            # Filter to only selected requests
            requests_to_process = pending_requests.filter(id__in=member_ids)

            processed_count = 0
            errors = []

            with transaction.atomic():
                for membership_request in requests_to_process:
                    try:
                        if action == 'approve':
                            membership_request.approve(request.user)
                        else:
                            membership_request.reject(request.user, notes)
                        processed_count += 1
                    except Exception as e:
                        errors.append(f"{membership_request.client.full_name}: {str(e)}")

            if processed_count > 0:
                messages.success(
                    request,
                    f'{processed_count} member request(s) {action}d successfully!'
                )
            if errors:
                messages.error(
                    request,
                    f'Some requests failed: {", ".join(errors[:5])}'
                )

            return redirect('core:group_detail', group_id=group.id)
    else:
        form = BulkApproveMembersForm()

    context = {
        'page_title': f'Approve Members for {group.name}',
        'group': group,
        'pending_requests': pending_requests,
        'form': form,
    }

    return render(request, 'groups/approve_members_bulk.html', context)


# =============================================================================
# REMOVE MEMBER VIEW
# =============================================================================

@login_required
def group_remove_member(request, group_id, client_id):
    """
    Remove a member from a group

    Permissions: Manager (own branch), Director, Admin
    """
    checker = PermissionChecker(request.user)

    group = get_object_or_404(ClientGroup, id=group_id)
    client = get_object_or_404(Client, id=client_id)

    # Check permission
    if not checker.can_edit_group(group):
        messages.error(request, 'You do not have permission to remove members from this group.')
        raise PermissionDenied

    # Verify client is in this group
    if client.group_id != group.id:
        messages.error(request, 'This client is not a member of this group.')
        return redirect('core:group_detail', group_id=group.id)

    if request.method == 'POST':
        with transaction.atomic():
            # Remove client from group
            client.group = None
            client.group_role = 'member'
            client.save(update_fields=['group', 'group_role', 'updated_at'])

            # Update group statistics
            group.update_statistics()

            messages.success(
                request,
                f'{client.full_name} removed from {group.name}.'
            )

        return redirect('core:group_detail', group_id=group.id)

    context = {
        'page_title': 'Remove Member',
        'group': group,
        'client': client,
    }

    return render(request, 'groups/remove_member_confirm.html', context)


# =============================================================================
# UPDATE MEMBER ROLE VIEW
# =============================================================================

@login_required
def group_update_member_role(request, group_id, client_id):
    """
    Update a member's role within a group

    Permissions: Manager (own branch), Director, Admin
    """
    checker = PermissionChecker(request.user)

    group = get_object_or_404(ClientGroup, id=group_id)
    client = get_object_or_404(Client, id=client_id)

    # Check permission
    if not checker.can_edit_group(group):
        messages.error(request, 'You do not have permission to update member roles.')
        raise PermissionDenied

    # Verify client is in this group
    if client.group_id != group.id:
        messages.error(request, 'This client is not a member of this group.')
        return redirect('core:group_detail', group_id=group.id)

    if request.method == 'POST':
        form = UpdateMemberRoleForm(request.POST, instance=client)

        if form.is_valid():
            client = form.save()
            messages.success(
                request,
                f'{client.full_name}\'s role updated to {client.get_group_role_display()}.'
            )
            return redirect('core:group_detail', group_id=group.id)
    else:
        form = UpdateMemberRoleForm(instance=client)

    context = {
        'page_title': 'Update Member Role',
        'group': group,
        'client': client,
        'form': form,
    }

    return render(request, 'groups/update_member_role.html', context)
