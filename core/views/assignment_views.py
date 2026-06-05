"""
Assignment Request Views
========================
Create, review, and execute client/group assignment requests.
"""

import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import AssignmentRequest, Client, ClientGroup, Loan, SavingsAccount, User
from core.forms.assignment_forms import AssignmentRequestForm, AssignmentReviewForm
from core.permissions import PermissionChecker
from core.services.notification_service import notify, notify_role


# =============================================================================
# ASSIGNMENT REQUEST LIST
# =============================================================================

@login_required
def assignment_list(request):
    checker = PermissionChecker(request.user)

    qs = AssignmentRequest.objects.select_related(
        'requested_by', 'reviewed_by', 'target_staff', 'target_branch', 'target_group', 'branch'
    )

    if checker.is_staff():
        qs = qs.filter(requested_by=request.user)
    elif checker.is_manager():
        qs = qs.filter(branch=request.user.branch)

    filter_by = request.GET.get('filter', 'pending')
    if filter_by == 'pending':
        qs = qs.filter(status='pending')
    elif filter_by in ('approved', 'rejected', 'cancelled'):
        qs = qs.filter(status=filter_by)

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    pending_count = AssignmentRequest.objects.filter(status='pending').count()

    return render(request, 'assignments/list.html', {
        'page_title': 'Assignment Requests',
        'requests': page_obj,
        'filter_by': filter_by,
        'checker': checker,
        'pending_count': pending_count,
    })


# =============================================================================
# CREATE ASSIGNMENT REQUEST
# =============================================================================

@login_required
def assignment_create(request):
    checker = PermissionChecker(request.user)

    clients_qs = Client.objects.filter(is_active=True, approval_status='approved')
    if checker.is_staff():
        clients_qs = clients_qs.filter(assigned_staff=request.user)
    elif checker.is_manager():
        clients_qs = clients_qs.filter(branch=request.user.branch)
    clients_qs = clients_qs.order_by('first_name', 'last_name').only('id', 'first_name', 'last_name', 'client_id')
    clients_json = json.dumps([
        {'id': str(c.id), 'name': c.get_full_name(), 'client_id': c.client_id}
        for c in clients_qs
    ])

    if request.method == 'POST':
        form = AssignmentRequestForm(request.POST)
        selected_ids = json.dumps(request.POST.getlist('clients'))
        if form.is_valid():
            data = form.build_assignment_data()
            description = form.build_description()
            atype = form.cleaned_data['assignment_type']
            clients = form.cleaned_data.get('clients')

            req = AssignmentRequest.objects.create(
                assignment_type=atype,
                status='pending',
                requested_by=request.user,
                branch=request.user.branch,
                assignment_data=data,
                description=description,
                reason=form.cleaned_data.get('reason', ''),
                target_staff=form.cleaned_data.get('target_staff'),
                target_branch=form.cleaned_data.get('target_branch'),
                target_group=form.cleaned_data.get('target_group'),
                affected_count=len(clients) if clients else 1,
            )

            notify_role(
                roles='manager',
                branch=request.user.branch,
                notification_type='assignment_request_pending',
                title='New Assignment Request',
                message=f'{request.user.get_full_name()} submitted an assignment request: "{description}".',
                is_urgent=False,
                exclude_user=request.user,
            )

            messages.success(
                request,
                f'Assignment request "{description}" submitted for approval.'
            )
            return redirect('core:assignment_detail', request_id=req.id)
    else:
        form = AssignmentRequestForm()
        selected_ids = '[]'

    return render(request, 'assignments/form.html', {
        'page_title': 'New Assignment Request',
        'form': form,
        'checker': checker,
        'clients_json': clients_json,
        'selected_ids': selected_ids,
    })


# =============================================================================
# ASSIGNMENT REQUEST DETAIL
# =============================================================================

@login_required
def assignment_detail(request, request_id):
    req = get_object_or_404(
        AssignmentRequest.objects.select_related(
            'requested_by', 'reviewed_by', 'target_staff', 'target_branch', 'target_group', 'branch'
        ),
        id=request_id,
    )
    checker = PermissionChecker(request.user)

    # Only requester or manager+ can view
    if not (req.requested_by == request.user or checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    return render(request, 'assignments/detail.html', {
        'page_title': f'Assignment Request — {req.get_assignment_type_display()}',
        'req': req,
        'checker': checker,
    })


# =============================================================================
# APPROVE ASSIGNMENT REQUEST
# =============================================================================

@login_required
@transaction.atomic
def assignment_approve(request, request_id):
    req = get_object_or_404(
        AssignmentRequest.objects.select_related(
            'requested_by', 'target_staff', 'target_branch', 'target_group', 'branch'
        ),
        id=request_id,
    )
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can approve assignment requests.')

    if checker.is_manager() and req.branch and req.branch != request.user.branch:
        raise PermissionDenied('You can only approve requests from your branch.')

    if req.status != 'pending':
        messages.error(request, 'This request is no longer pending.')
        return redirect('core:assignment_list')

    if request.method == 'POST':
        form = AssignmentReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            review_notes = form.cleaned_data.get('review_notes', '')

            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.review_notes = review_notes

            if decision == 'approve':
                req.status = 'approved'
                req.save()
                try:
                    _execute_assignment(req)
                    req.executed_at = timezone.now()
                    req.execution_result = {'status': 'success'}
                    req.save(update_fields=['executed_at', 'execution_result', 'updated_at'])
                    messages.success(
                        request,
                        f'Assignment approved and executed: {req.description}'
                    )
                except Exception as exc:
                    req.execution_result = {'status': 'error', 'message': str(exc)}
                    req.save(update_fields=['execution_result', 'updated_at'])
                    messages.error(request, f'Assignment approved but execution failed: {exc}')

                notify(
                    user=req.requested_by,
                    notification_type='assignment_request_approved',
                    title='Assignment Request Approved',
                    message=f'Your assignment request "{req.description}" has been approved and executed.',
                )
                notify_role(
                    roles='manager',
                    branch=req.branch,
                    notification_type='assignment_request_approved',
                    title='Assignment Request Approved',
                    message=f'Assignment request "{req.description}" by {req.requested_by.get_full_name()} has been approved and executed by {request.user.get_full_name()}.',
                    exclude_user=request.user,
                )
            else:
                req.status = 'rejected'
                req.save()
                messages.warning(request, 'Assignment request rejected.')
                notify(
                    user=req.requested_by,
                    notification_type='assignment_request_rejected',
                    title='Assignment Request Rejected',
                    message=(
                        f'Your assignment request "{req.description}" was rejected. '
                        f'Reason: {review_notes or "No reason given"}'
                    ),
                    is_urgent=True,
                )
                notify_role(
                    roles='manager',
                    branch=req.branch,
                    notification_type='assignment_request_rejected',
                    title='Assignment Request Rejected',
                    message=f'Assignment request "{req.description}" by {req.requested_by.get_full_name()} was rejected by {request.user.get_full_name()}. Reason: {review_notes or "No reason given"}',
                    is_urgent=True,
                    exclude_user=request.user,
                )

            return redirect('core:assignment_list')
    else:
        form = AssignmentReviewForm()

    return render(request, 'assignments/approve.html', {
        'page_title': f'Review Assignment — {req.get_assignment_type_display()}',
        'req': req,
        'form': form,
        'checker': checker,
    })


# =============================================================================
# REJECT ASSIGNMENT REQUEST
# =============================================================================

@login_required
@transaction.atomic
def assignment_reject(request, request_id):
    """Redirect to the approval view — rejection is handled there."""
    return assignment_approve(request, request_id)


# =============================================================================
# CANCEL ASSIGNMENT REQUEST (requester only)
# =============================================================================

@login_required
@require_POST
def assignment_cancel(request, request_id):
    req = get_object_or_404(AssignmentRequest, id=request_id, requested_by=request.user)

    if req.status != 'pending':
        messages.error(request, 'Only pending requests can be cancelled.')
        return redirect('core:assignment_detail', request_id=req.id)

    req.status = 'cancelled'
    req.save(update_fields=['status', 'updated_at'])
    messages.success(request, 'Assignment request cancelled.')
    return redirect('core:assignment_list')


# =============================================================================
# PRIVATE: Execute an assignment
# =============================================================================

def _execute_assignment(req):
    """Apply the assignment changes from req.assignment_data to the relevant model(s)."""
    atype = req.assignment_type
    data = req.assignment_data or {}

    if atype == 'client_to_staff':
        client_id = data.get('client_id')
        staff_id = data.get('staff_id')
        if client_id and staff_id:
            Client.objects.filter(id=client_id).update(assigned_staff_id=staff_id)

    elif atype == 'client_to_branch':
        client_id = data.get('client_id')
        branch_id = data.get('branch_id')
        if client_id and branch_id:
            Client.objects.filter(id=client_id).update(branch_id=branch_id)
            SavingsAccount.objects.filter(client_id=client_id).update(branch_id=branch_id)
            Loan.objects.filter(client_id=client_id).update(branch_id=branch_id)

    elif atype == 'client_to_group':
        client_id = data.get('client_id')
        group_id = data.get('group_id')
        if client_id and group_id:
            Client.objects.filter(id=client_id).update(group_id=group_id)

    elif atype == 'unassign_client_from_staff':
        client_id = data.get('client_id')
        if client_id:
            Client.objects.filter(id=client_id).update(assigned_staff=None)

    elif atype == 'unassign_client_from_group':
        client_id = data.get('client_id')
        if client_id:
            Client.objects.filter(id=client_id).update(group=None)

    elif atype == 'group_to_branch':
        group_id = data.get('group_id')
        branch_id = data.get('branch_id')
        if group_id and branch_id:
            ClientGroup.objects.filter(id=group_id).update(branch_id=branch_id)

    elif atype == 'bulk_clients_to_staff':
        client_ids = data.get('client_ids', [])
        staff_id = data.get('staff_id')
        if client_ids and staff_id:
            Client.objects.filter(id__in=client_ids).update(assigned_staff_id=staff_id)

    elif atype == 'bulk_clients_to_branch':
        client_ids = data.get('client_ids', [])
        branch_id = data.get('branch_id')
        if client_ids and branch_id:
            Client.objects.filter(id__in=client_ids).update(branch_id=branch_id)
            SavingsAccount.objects.filter(client_id__in=client_ids).update(branch_id=branch_id)
            Loan.objects.filter(client_id__in=client_ids).update(branch_id=branch_id)

    elif atype == 'bulk_clients_to_group':
        client_ids = data.get('client_ids', [])
        group_id = data.get('group_id')
        if client_ids and group_id:
            Client.objects.filter(id__in=client_ids).update(group_id=group_id)

    else:
        raise ValueError(f'Unknown assignment type: {atype}')


# =============================================================================
# STAFF PORTFOLIO TRANSFER
# =============================================================================

@login_required
def staff_portfolio_transfer(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can perform staff portfolio transfers.')

    staff_qs = User.objects.filter(user_role='staff', is_active=True).select_related('branch').order_by('first_name', 'last_name')
    if checker.is_manager():
        staff_qs = staff_qs.filter(branch=request.user.branch)

    # Resolve source staff from GET param (initial load) or POST (re-render on error)
    from_staff_id = request.POST.get('from_staff') or request.GET.get('from_staff')
    from_staff = None
    clients_qs = Client.objects.none()

    if from_staff_id:
        try:
            from_staff = staff_qs.get(id=from_staff_id)
            clients_qs = (
                Client.objects.filter(assigned_staff=from_staff, is_active=True)
                .order_by('first_name', 'last_name')
            )
        except (User.DoesNotExist, ValueError):
            from_staff = None

    clients_json = json.dumps([
        {'id': str(c.id), 'name': c.get_full_name(), 'client_id': c.client_id}
        for c in clients_qs
    ])
    target_staff_qs = staff_qs.exclude(id=from_staff.id) if from_staff else staff_qs

    errors = {}

    if request.method == 'POST':
        client_ids = request.POST.getlist('clients')
        target_staff_id = request.POST.get('target_staff', '').strip()
        reason = request.POST.get('reason', '').strip()

        if not from_staff:
            errors['from_staff'] = 'Please select a source staff member.'
        if not target_staff_id:
            errors['target_staff'] = 'Please select a target staff member.'
        if not client_ids:
            errors['clients'] = 'Please select at least one client to transfer.'
        if not reason:
            errors['reason'] = 'Please provide a reason for the transfer.'

        if not errors:
            try:
                target_staff = staff_qs.get(id=target_staff_id)
            except (User.DoesNotExist, ValueError):
                errors['target_staff'] = 'Invalid target staff selected.'

        if not errors:
            # Only transfer clients that genuinely belong to the source staff
            valid_clients = list(
                Client.objects.filter(id__in=client_ids, assigned_staff=from_staff, is_active=True)
                .values_list('id', flat=True)
            )
            if not valid_clients:
                errors['clients'] = 'None of the selected clients belong to the chosen source staff.'

        if not errors:
            client_id_strs = [str(c) for c in valid_clients]
            description = (
                f'Transfer {len(client_id_strs)} client(s) from '
                f'{from_staff.get_full_name()} to {target_staff.get_full_name()}'
            )
            req = AssignmentRequest.objects.create(
                assignment_type='bulk_clients_to_staff',
                status='pending',
                requested_by=request.user,
                branch=request.user.branch,
                assignment_data={'client_ids': client_id_strs, 'staff_id': str(target_staff.id)},
                description=description,
                reason=reason,
                target_staff=target_staff,
                affected_count=len(client_id_strs),
            )

            notify_role(
                roles='manager',
                branch=request.user.branch,
                notification_type='assignment_request_pending',
                title='New Portfolio Transfer Request',
                message=f'{request.user.get_full_name()} submitted a portfolio transfer request: "{description}".',
                is_urgent=False,
                exclude_user=request.user,
            )

            messages.success(request, f'Portfolio transfer request submitted: {description}.')
            return redirect('core:assignment_detail', request_id=req.id)

    return render(request, 'assignments/staff_portfolio_transfer.html', {
        'page_title': 'Staff Portfolio Transfer',
        'checker': checker,
        'staff_list': staff_qs,
        'from_staff': from_staff,
        'target_staff_list': target_staff_qs,
        'clients_json': clients_json,
        'selected_ids': '[]',
        'client_count': clients_qs.count(),
        'errors': errors,
        'posted_reason': request.POST.get('reason', '') if request.method == 'POST' else '',
        'posted_target': request.POST.get('target_staff', '') if request.method == 'POST' else '',
    })
