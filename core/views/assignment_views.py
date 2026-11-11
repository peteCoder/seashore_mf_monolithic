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

from core.models import AssignmentRequest, Branch, Client, ClientGroup, Loan, SavingsAccount, User
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

    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_assignment_affected_clients_excel
        return export_assignment_affected_clients_excel(req)

    affected_clients_qs = req.get_affected_clients().order_by('first_name', 'last_name')
    affected_clients = Paginator(affected_clients_qs, 50).get_page(request.GET.get('clients_page'))
    affected_staff = req.get_affected_staff().order_by('first_name', 'last_name') if req.assignment_type == 'bulk_staff_to_branch' else None

    return render(request, 'assignments/detail.html', {
        'page_title': f'Assignment Request — {req.get_assignment_type_display()}',
        'req': req,
        'affected_clients': affected_clients,
        'affected_staff': affected_staff,
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

    if request.method == 'GET' and request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_assignment_affected_clients_excel
        return export_assignment_affected_clients_excel(req)

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

    affected_clients_qs = req.get_affected_clients().order_by('first_name', 'last_name')
    affected_clients = Paginator(affected_clients_qs, 50).get_page(request.GET.get('clients_page'))

    return render(request, 'assignments/approve.html', {
        'page_title': f'Review Assignment — {req.get_assignment_type_display()}',
        'req': req,
        'form': form,
        'affected_clients': affected_clients,
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

    elif atype == 'bulk_staff_to_branch':
        staff_ids = data.get('staff_ids', [])
        branch_id = data.get('branch_id')
        if staff_ids and branch_id:
            User.objects.filter(id__in=staff_ids).update(branch_id=branch_id)

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


# =============================================================================
# BULK ASSIGNMENT (direct execution — no pending approval step)
# =============================================================================

@login_required
@transaction.atomic
def bulk_assign(request):
    """
    Direct bulk assignment: clients -> staff, clients -> branch, and
    staff -> branch. Unlike assignment_create / staff_portfolio_transfer,
    this executes immediately with no pending/approval step, because every
    role allowed here already sits at or above the approval authority for
    these moves.

    Permissions:
    - View the page: Manager, HR, Director, Admin (checker.can_view_bulk_assignment)
    - Clients -> Staff: Manager (own branch only) and HR/Director/Admin (any branch)
      — see checker.can_assign_staff()
    - Clients -> Branch / Staff -> Branch: HR, Director, Admin only
      — see checker.can_assign_branch_level(). Staff/loan-officer role can
      never reach this view at all (can_view_bulk_assignment excludes it).

    Every execution still creates an AssignmentRequest record (status=
    'approved', self-reviewed, executed immediately) so the move shows up
    in Assignment Request history with full human-readable detail, matching
    the standing requirement that every client/staff movement leaves a
    detailed record rather than a silent DB update.
    """
    checker = PermissionChecker(request.user)
    if not checker.can_view_bulk_assignment():
        raise PermissionDenied('Only managers and above can access bulk assignment.')

    can_branch_level = checker.can_assign_branch_level()
    can_assign_staff = checker.can_assign_staff()

    # `tab` drives which POST handler runs below and must stay exactly as
    # posted — downgrading it here (e.g. for a manager posting tab=
    # clients_to_branch) would silently reroute the request into a
    # different handler instead of the 403 each handler already raises for
    # that case. `display_tab` is the separate, sanitized value used only
    # to pick which tab panel the template shows by default on a GET.
    valid_tabs = ('clients_to_staff', 'clients_to_branch', 'staff_to_branch')
    tab = (request.POST.get('tab') or '').strip()
    if tab not in valid_tabs:
        tab = 'clients_to_staff'

    display_tab = (request.GET.get('tab') or tab).strip()
    if display_tab not in valid_tabs:
        display_tab = 'clients_to_staff'
    if display_tab in ('clients_to_branch', 'staff_to_branch') and not can_branch_level:
        display_tab = 'clients_to_staff'

    # ── Branch scoping ───────────────────────────────────────────────────
    if checker.is_manager():
        branches = Branch.objects.filter(id=request.user.branch_id)
        selected_branch = request.user.branch
    else:
        branches = Branch.objects.filter(is_active=True).order_by('name')
        branch_param = request.POST.get('branch') or request.GET.get('branch', '')
        selected_branch = branches.filter(id=branch_param).first() if branch_param else None

    # ── Clients -> Staff tab data ────────────────────────────────────────
    clients_qs = Client.objects.filter(is_active=True, approval_status='approved')
    assignable_staff_qs = User.objects.filter(user_role='staff', is_active=True)
    if selected_branch:
        clients_qs = clients_qs.filter(branch=selected_branch)
        assignable_staff_qs = assignable_staff_qs.filter(branch=selected_branch)
    clients_qs = clients_qs.select_related('branch', 'assigned_staff').order_by('first_name', 'last_name')
    assignable_staff_qs = assignable_staff_qs.order_by('first_name', 'last_name')

    # ── Staff -> Branch tab data (staff + managers can be relocated) ─────
    movable_staff_qs = User.objects.filter(
        user_role__in=['staff', 'manager'], is_active=True
    ).select_related('branch')
    if selected_branch:
        movable_staff_qs = movable_staff_qs.filter(branch=selected_branch)
    movable_staff_qs = movable_staff_qs.order_by('branch__name', 'first_name', 'last_name')

    errors = {}

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            errors['reason'] = 'Please provide a reason for this assignment.'

        if tab == 'clients_to_staff':
            if not can_assign_staff:
                raise PermissionDenied
            client_ids = request.POST.getlist('clients')
            target_staff_id = request.POST.get('target_staff', '').strip()

            if not client_ids:
                errors['clients'] = 'Please select at least one client.'
            if not target_staff_id:
                errors['target_staff'] = 'Please select a target staff member.'

            target_staff = None
            valid_client_ids = []
            if not errors:
                valid_qs = Client.objects.filter(id__in=client_ids, is_active=True)
                target_qs = User.objects.filter(id=target_staff_id, user_role='staff', is_active=True)
                # Manager is hard-restricted to their own branch regardless
                # of whatever ids were posted.
                if checker.is_manager():
                    valid_qs = valid_qs.filter(branch=request.user.branch)
                    target_qs = target_qs.filter(branch=request.user.branch)
                valid_client_ids = list(valid_qs.values_list('id', flat=True))
                target_staff = target_qs.first()

                if not valid_client_ids:
                    errors['clients'] = 'None of the selected clients are valid for this action.'
                if not target_staff:
                    errors['target_staff'] = 'Invalid target staff member.'

            if not errors:
                client_id_strs = [str(c) for c in valid_client_ids]
                description = f'Bulk-assign {len(client_id_strs)} client(s) to {target_staff.get_full_name()}'
                req = AssignmentRequest.objects.create(
                    assignment_type='bulk_clients_to_staff',
                    status='approved',
                    requested_by=request.user,
                    reviewed_by=request.user,
                    reviewed_at=timezone.now(),
                    branch=selected_branch or request.user.branch,
                    assignment_data={
                        'client_ids': client_id_strs,
                        'staff_id': str(target_staff.id),
                        'staff_name': target_staff.get_full_name(),
                    },
                    description=description,
                    reason=reason,
                    review_notes='Auto-approved — executed directly via the Bulk Assignment page.',
                    target_staff=target_staff,
                    affected_count=len(client_id_strs),
                )
                _execute_assignment(req)
                req.executed_at = timezone.now()
                req.execution_result = {'status': 'success'}
                req.save(update_fields=['executed_at', 'execution_result', 'updated_at'])
                messages.success(request, f'{description}.')
                return redirect('core:assignment_detail', request_id=req.id)

        elif tab == 'clients_to_branch':
            if not can_branch_level:
                raise PermissionDenied
            client_ids = request.POST.getlist('clients')
            target_branch_id = request.POST.get('target_branch', '').strip()

            if not client_ids:
                errors['clients'] = 'Please select at least one client.'
            if not target_branch_id:
                errors['target_branch'] = 'Please select a target branch.'

            target_branch = None
            valid_client_ids = []
            if not errors:
                valid_client_ids = list(
                    Client.objects.filter(id__in=client_ids, is_active=True).values_list('id', flat=True)
                )
                target_branch = Branch.objects.filter(id=target_branch_id, is_active=True).first()
                if not valid_client_ids:
                    errors['clients'] = 'None of the selected clients are valid.'
                if not target_branch:
                    errors['target_branch'] = 'Invalid target branch.'

            if not errors:
                client_id_strs = [str(c) for c in valid_client_ids]
                description = f'Bulk-move {len(client_id_strs)} client(s) to branch {target_branch.name}'
                req = AssignmentRequest.objects.create(
                    assignment_type='bulk_clients_to_branch',
                    status='approved',
                    requested_by=request.user,
                    reviewed_by=request.user,
                    reviewed_at=timezone.now(),
                    branch=selected_branch,
                    assignment_data={
                        'client_ids': client_id_strs,
                        'branch_id': str(target_branch.id),
                        'branch_name': target_branch.name,
                    },
                    description=description,
                    reason=reason,
                    review_notes='Auto-approved — executed directly via the Bulk Assignment page.',
                    target_branch=target_branch,
                    affected_count=len(client_id_strs),
                )
                _execute_assignment(req)
                req.executed_at = timezone.now()
                req.execution_result = {'status': 'success'}
                req.save(update_fields=['executed_at', 'execution_result', 'updated_at'])
                messages.success(request, f'{description}.')
                return redirect('core:assignment_detail', request_id=req.id)

        elif tab == 'staff_to_branch':
            if not can_branch_level:
                raise PermissionDenied
            staff_ids = request.POST.getlist('staff')
            target_branch_id = request.POST.get('target_branch', '').strip()

            if not staff_ids:
                errors['staff'] = 'Please select at least one staff member.'
            if not target_branch_id:
                errors['target_branch'] = 'Please select a target branch.'

            target_branch = None
            valid_staff_ids = []
            if not errors:
                valid_staff_ids = list(
                    User.objects.filter(id__in=staff_ids, user_role__in=['staff', 'manager'], is_active=True)
                    .values_list('id', flat=True)
                )
                target_branch = Branch.objects.filter(id=target_branch_id, is_active=True).first()
                if not valid_staff_ids:
                    errors['staff'] = 'None of the selected staff are valid.'
                if not target_branch:
                    errors['target_branch'] = 'Invalid target branch.'

            if not errors:
                staff_id_strs = [str(s) for s in valid_staff_ids]
                description = f'Bulk-move {len(staff_id_strs)} staff member(s) to branch {target_branch.name}'
                req = AssignmentRequest.objects.create(
                    assignment_type='bulk_staff_to_branch',
                    status='approved',
                    requested_by=request.user,
                    reviewed_by=request.user,
                    reviewed_at=timezone.now(),
                    branch=selected_branch,
                    assignment_data={
                        'staff_ids': staff_id_strs,
                        'branch_id': str(target_branch.id),
                        'branch_name': target_branch.name,
                    },
                    description=description,
                    reason=reason,
                    review_notes='Auto-approved — executed directly via the Bulk Assignment page.',
                    target_branch=target_branch,
                    affected_count=len(staff_id_strs),
                )
                _execute_assignment(req)
                req.executed_at = timezone.now()
                req.execution_result = {'status': 'success'}
                req.save(update_fields=['executed_at', 'execution_result', 'updated_at'])
                messages.success(request, f'{description}.')
                return redirect('core:assignment_detail', request_id=req.id)

    clients_json = json.dumps([
        {
            'id': str(c.id),
            'name': c.get_full_name(),
            'client_id': c.client_id,
            'meta': c.assigned_staff.get_full_name() if c.assigned_staff else 'Unassigned',
        }
        for c in clients_qs
    ])
    movable_staff_json = json.dumps([
        {
            'id': str(s.id),
            'name': s.get_full_name(),
            'client_id': s.get_user_role_display(),
            'meta': s.branch.name if s.branch else 'No branch',
        }
        for s in movable_staff_qs
    ])

    return render(request, 'assignments/bulk_assign.html', {
        'page_title': 'Bulk Assignment',
        'checker': checker,
        'tab': display_tab,
        'can_branch_level': can_branch_level,
        'can_assign_staff': can_assign_staff,
        'branches': branches,
        'selected_branch': selected_branch,
        'assignable_staff': assignable_staff_qs,
        'clients_json': clients_json,
        'movable_staff_json': movable_staff_json,
        'client_count': clients_qs.count(),
        'movable_staff_count': movable_staff_qs.count(),
        'errors': errors,
        'posted_reason': request.POST.get('reason', '') if request.method == 'POST' else '',
        'posted_target_staff': request.POST.get('target_staff', '') if request.method == 'POST' else '',
        'posted_target_branch': request.POST.get('target_branch', '') if request.method == 'POST' else '',
    })
