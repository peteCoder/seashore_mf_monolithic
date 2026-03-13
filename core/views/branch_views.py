"""
Branch Views
============

All branch CRUD operations with role-based permissions
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q

from core.models import Branch
from core.forms.branch_forms import (
    BranchCreateForm,
    BranchUpdateForm,
    BranchSearchForm,
)
from core.permissions import PermissionChecker


# =============================================================================
# BRANCH LIST VIEW
# =============================================================================

@login_required
def branch_list(request):
    """
    Display paginated list of branches with search and filters

    Permissions:
    - Admin/Director: See all branches
    - Manager: See own branch only
    """
    checker = PermissionChecker(request.user)

    # Base queryset (role-filtered)
    branches = checker.filter_branches(Branch.objects.all())

    # Search form
    search_form = BranchSearchForm(request.GET or None)

    # Apply filters
    if search_form.is_valid():
        search = search_form.cleaned_data.get('search')
        if search:
            branches = branches.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(city__icontains=search) |
                Q(state__icontains=search)
            )

        status = search_form.cleaned_data.get('status')
        if status == 'active':
            branches = branches.filter(is_active=True)
        elif status == 'inactive':
            branches = branches.filter(is_active=False)

        state = search_form.cleaned_data.get('state')
        if state:
            branches = branches.filter(state__icontains=state)

    # Prefetch related data
    branches = branches.select_related('manager').order_by('-created_at')

    # Pagination (25 per page)
    paginator = Paginator(branches, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Context
    context = {
        'page_title': 'Branches',
        'branches': page_obj,
        'search_form': search_form,
        'checker': checker,
        'total_count': branches.count(),
    }

    return render(request, 'branches/list.html', context)


# =============================================================================
# BRANCH DETAIL VIEW
# =============================================================================

@login_required
def branch_detail(request, branch_id):
    """
    Display comprehensive branch information

    Shows:
    - Branch information
    - Manager details
    - Staff count
    - Client count
    - Active loans count
    - Portfolio summary
    """
    checker = PermissionChecker(request.user)

    # Get branch
    branch = get_object_or_404(
        Branch.objects.select_related('manager'),
        id=branch_id
    )

    # Permission check
    if not checker.can_view_branch(branch):
        messages.error(request, 'You do not have permission to view this branch.')
        raise PermissionDenied

    # Get branch statistics
    staff_count = branch.get_staff_count()
    client_count = branch.get_client_count()
    active_loans_count = branch.get_active_loans_count()
    portfolio_summary = branch.get_portfolio_summary()

    # Get recent staff
    recent_staff = branch.users.filter(is_active=True).order_by('-created_at')[:5]

    # Get recent clients
    recent_clients = branch.clients.filter(is_active=True, approval_status='approved').order_by('-created_at')[:10]

    # Context
    context = {
        'page_title': f'Branch: {branch.name}',
        'branch': branch,
        'staff_count': staff_count,
        'client_count': client_count,
        'active_loans_count': active_loans_count,
        'portfolio_summary': portfolio_summary,
        'recent_staff': recent_staff,
        'recent_clients': recent_clients,
        'checker': checker,
    }

    return render(request, 'branches/detail.html', context)


# =============================================================================
# BRANCH CREATE VIEW
# =============================================================================

@login_required
def branch_create(request):
    """
    Create new branch

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_manage_branches():
        messages.error(request, 'You do not have permission to create branches.')
        raise PermissionDenied

    if request.method == 'POST':
        form = BranchCreateForm(request.POST)

        if form.is_valid():
            branch = form.save(commit=False)
            branch.is_active = True  # New branches are active by default
            branch.save()

            messages.success(
                request,
                f'Branch {branch.name} ({branch.code}) created successfully!'
            )
            return redirect('core:branch_detail', branch_id=branch.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BranchCreateForm()

    context = {
        'page_title': 'Create New Branch',
        'form': form,
        'is_create': True,
    }

    return render(request, 'branches/form.html', context)


# =============================================================================
# BRANCH UPDATE VIEW
# =============================================================================

@login_required
def branch_update(request, branch_id):
    """
    Update existing branch

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_branches():
        messages.error(request, 'You do not have permission to edit branches.')
        raise PermissionDenied

    branch = get_object_or_404(Branch, id=branch_id)

    if request.method == 'POST':
        form = BranchUpdateForm(request.POST, instance=branch)

        if form.is_valid():
            branch = form.save()
            messages.success(request, f'Branch {branch.name} updated successfully!')
            return redirect('core:branch_detail', branch_id=branch.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = BranchUpdateForm(instance=branch)

    context = {
        'page_title': f'Edit Branch: {branch.name}',
        'form': form,
        'branch': branch,
        'is_create': False,
    }

    return render(request, 'branches/form.html', context)


# =============================================================================
# BRANCH ACTIVATE VIEW
# =============================================================================

@login_required
def branch_activate(request, branch_id):
    """
    Activate inactive branch

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_branches():
        messages.error(request, 'You do not have permission to activate branches.')
        raise PermissionDenied

    branch = get_object_or_404(Branch, id=branch_id)

    # Validation
    if branch.is_active:
        messages.warning(request, 'This branch is already active.')
        return redirect('core:branch_detail', branch_id=branch.id)

    if request.method == 'POST':
        branch.is_active = True
        branch.save()

        messages.success(request, f'Branch {branch.name} activated successfully!')
        return redirect('core:branch_detail', branch_id=branch.id)

    context = {
        'page_title': f'Activate Branch: {branch.name}',
        'branch': branch,
    }

    return render(request, 'branches/activate_confirm.html', context)


# =============================================================================
# BRANCH DEACTIVATE VIEW
# =============================================================================

@login_required
def branch_deactivate(request, branch_id):
    """
    Deactivate active branch

    Permissions: Admin, Director

    Checks:
    - Cannot deactivate if branch has active users
    - Cannot deactivate if branch has active clients with active loans
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_branches():
        messages.error(request, 'You do not have permission to deactivate branches.')
        raise PermissionDenied

    branch = get_object_or_404(Branch, id=branch_id)

    if not branch.is_active:
        messages.warning(request, 'This branch is already inactive.')
        return redirect('core:branch_detail', branch_id=branch.id)

    # Check for active users
    active_users = branch.users.filter(is_active=True).count()
    if active_users > 0:
        messages.error(
            request,
            f'Cannot deactivate branch with {active_users} active user(s). Please deactivate or reassign users first.'
        )
        return redirect('core:branch_detail', branch_id=branch.id)

    # Check for active clients with loans
    active_clients = branch.clients.filter(is_active=True).count()
    if active_clients > 0:
        messages.error(
            request,
            f'Cannot deactivate branch with {active_clients} active client(s). Please deactivate or reassign clients first.'
        )
        return redirect('core:branch_detail', branch_id=branch.id)

    if request.method == 'POST':
        reason = request.POST.get('reason', '')

        branch.is_active = False
        branch.save()

        messages.success(request, f'Branch {branch.name} deactivated successfully.')
        return redirect('core:branch_detail', branch_id=branch.id)

    context = {
        'page_title': f'Deactivate Branch: {branch.name}',
        'branch': branch,
    }

    return render(request, 'branches/deactivate_confirm.html', context)


# =============================================================================
# BRANCH DELETE VIEW
# =============================================================================

@login_required
def branch_delete(request, branch_id):
    """
    Soft delete branch (admin only)

    Permissions: Admin only

    Requirements:
    - No active users
    - No active clients
    - No active loans
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin():
        messages.error(request, 'Only administrators can delete branches.')
        raise PermissionDenied

    branch = get_object_or_404(Branch, id=branch_id)

    # Validation
    active_users = branch.users.filter(is_active=True).count()
    if active_users > 0:
        messages.error(request, f'Cannot delete branch with {active_users} active user(s).')
        return redirect('core:branch_detail', branch_id=branch.id)

    total_clients = branch.clients.count()
    if total_clients > 0:
        messages.error(request, f'Cannot delete branch with {total_clients} client(s).')
        return redirect('core:branch_detail', branch_id=branch.id)

    active_loans = branch.loans.filter(status__in=['active', 'disbursed', 'overdue']).count()
    if active_loans > 0:
        messages.error(request, f'Cannot delete branch with {active_loans} active loan(s).')
        return redirect('core:branch_detail', branch_id=branch.id)

    if request.method == 'POST':
        branch_name = branch.name
        branch.delete()  # Soft delete (sets deleted_at)

        messages.success(request, f'Branch {branch_name} deleted successfully.')
        return redirect('core:branch_list')

    context = {
        'page_title': f'Delete Branch: {branch.name}',
        'branch': branch,
    }

    return render(request, 'branches/delete_confirm.html', context)
