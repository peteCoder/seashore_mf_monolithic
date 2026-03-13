"""
User/Staff Management Views
============================

All user and staff management operations with role-based permissions
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
from django.utils import timezone

from core.models import User, Client, Branch
from core.forms.user_forms import (
    UserCreateForm,
    UserUpdateForm,
    UserProfileUpdateForm,
    AssignBranchForm,
    UserSearchForm,
)
from core.permissions import PermissionChecker


def _sync_branch_manager(user, old_branch=None, old_role=None):
    """
    Keep Branch.manager in sync with User.user_role and User.branch.

    Rules:
    - If the user IS a manager and HAS a branch → set that branch's manager to them.
    - If the user WAS a manager on a (now different) branch, or is no longer a
      manager, and they were still recorded as that branch's manager → clear it.

    Returns:
        User | None — the previous manager who was displaced (if any), so the
        caller can show a warning. The displaced manager's role is NOT changed
        automatically; the admin should review their assignment.
    """
    new_role   = user.user_role
    new_branch = user.branch

    # Clear manager from the old branch if role/branch changed
    if old_branch and old_role == 'manager':
        if new_branch != old_branch or new_role != 'manager':
            # Only clear if this user is still recorded as the old branch's manager
            if old_branch.manager_id == user.pk:
                old_branch.manager = None
                old_branch.save(update_fields=['manager'])

    # Set manager on the new branch — detect if a different manager is displaced
    displaced = None
    if new_role == 'manager' and new_branch:
        existing = new_branch.manager
        if existing and existing.pk != user.pk:
            displaced = existing          # someone else was manager here
        new_branch.manager = user
        new_branch.save(update_fields=['manager'])

    return displaced


# =============================================================================
# STAFF/USER LIST VIEW
# =============================================================================

@login_required
def user_list(request):
    """
    List all users/staff members with search and filter capabilities

    Permissions: Admin, Director only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to view staff list.')
        raise PermissionDenied

    # Get all users
    users = User.objects.select_related('branch').annotate(
        client_count=Count('assigned_clients', distinct=True)
    ).order_by('-date_joined')

    # Search and filter
    form = UserSearchForm(request.GET)
    if form.is_valid():
        search = form.cleaned_data.get('search')
        role = form.cleaned_data.get('role')
        branch = form.cleaned_data.get('branch')
        status = form.cleaned_data.get('status')

        if search:
            users = users.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search)
            )

        if role:
            users = users.filter(user_role=role)

        if branch:
            users = users.filter(branch=branch)

        if status == 'active':
            users = users.filter(is_active=True)
        elif status == 'inactive':
            users = users.filter(is_active=False)
        elif status == 'pending':
            users = users.filter(is_approved=False)

    # Pagination
    paginator = Paginator(users, 20)  # 20 users per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Staff Management',
        'page_obj': page_obj,
        'form': form,
        'total_users': users.count(),
    }

    return render(request, 'users/list.html', context)


# =============================================================================
# STAFF/USER CREATE VIEW
# =============================================================================

@login_required
def user_create(request):
    """
    Create a new staff/user account

    Permissions: Admin, Director only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to create staff accounts.')
        raise PermissionDenied

    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            displaced = _sync_branch_manager(user)
            if displaced:
                messages.warning(
                    request,
                    f'{displaced.get_full_name()} was previously the manager of '
                    f'{user.branch.name}. Their role is still set to "Manager" — '
                    f'please review their branch assignment.'
                )
            messages.success(
                request,
                f'Staff account for {user.get_full_name()} created successfully!'
            )
            return redirect('core:user_detail', user_id=user.id)
    else:
        form = UserCreateForm()

    context = {
        'page_title': 'Create Staff Account',
        'form': form,
    }

    return render(request, 'users/create.html', context)


# =============================================================================
# STAFF/USER DETAIL VIEW
# =============================================================================

@login_required
def user_detail(request, user_id):
    """
    View detailed information about a specific user/staff member
    Includes assigned clients table and performance metrics

    Permissions: Admin, Director only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to view staff details.')
        raise PermissionDenied

    user = get_object_or_404(User.objects.select_related('branch'), id=user_id)

    # Get assigned clients with pagination
    clients = Client.objects.filter(assigned_staff=user).select_related(
        'branch', 'group'
    ).order_by('-created_at')

    # Pagination for clients
    paginator = Paginator(clients, 10)  # 10 clients per page
    page_number = request.GET.get('page')
    clients_page = paginator.get_page(page_number)

    # Performance metrics
    total_clients = clients.count()
    active_clients = clients.filter(is_active=True).count()
    inactive_clients = total_clients - active_clients

    # Client registration stats
    clients_this_month = clients.filter(
        created_at__year=timezone.now().year,
        created_at__month=timezone.now().month
    ).count()

    # Loan stats (if user has assigned clients with loans)
    from core.models import Loan
    loans = Loan.objects.filter(client__assigned_staff=user)
    total_loans = loans.count()
    active_loans = loans.filter(status='active').count()
    total_disbursed = loans.filter(status__in=['active', 'completed']).aggregate(
        total=Sum('principal_amount')
    )['total'] or 0

    context = {
        'page_title': f'Staff Details: {user.get_full_name()}',
        'staff_user': user,
        'clients_page': clients_page,
        'metrics': {
            'total_clients': total_clients,
            'active_clients': active_clients,
            'inactive_clients': inactive_clients,
            'clients_this_month': clients_this_month,
            'total_loans': total_loans,
            'active_loans': active_loans,
            'total_disbursed': total_disbursed,
        }
    }

    return render(request, 'users/detail.html', context)


# =============================================================================
# USER EDIT VIEW
# =============================================================================

@login_required
def user_edit(request, user_id):
    """
    Edit user information

    Permissions: Admin, Director only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to edit users.')
        raise PermissionDenied

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        # Capture current role and branch before any changes
        old_role   = user.user_role
        old_branch = user.branch

        form = UserUpdateForm(request.POST, request.FILES, instance=user)

        if form.is_valid():
            form.save()
            displaced = _sync_branch_manager(user, old_branch=old_branch, old_role=old_role)
            if displaced:
                messages.warning(
                    request,
                    f'{displaced.get_full_name()} was previously the manager of '
                    f'{user.branch.name}. Their role is still set to "Manager" — '
                    f'please review their branch assignment.'
                )
            messages.success(request, f'User {user.get_full_name()} updated successfully!')
            return redirect('core:user_detail', user_id=user.id)
    else:
        form = UserUpdateForm(instance=user)

    context = {
        'page_title': f'Edit User: {user.get_full_name()}',
        'form': form,
        'staff_user': user,
    }

    return render(request, 'users/form.html', context)


# =============================================================================
# USER DELETE VIEW
# =============================================================================

@login_required
def user_delete(request, user_id):
    """
    Delete a user
    Cannot delete if user has assigned clients unless they are reassigned

    Permissions: Admin, Director only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to delete users.')
        raise PermissionDenied

    user = get_object_or_404(User, id=user_id)

    # Check if user has assigned clients
    assigned_clients_count = Client.objects.filter(assigned_staff=user).count()

    if assigned_clients_count > 0:
        messages.error(
            request,
            f'Cannot delete user {user.get_full_name()}. '
            f'They have {assigned_clients_count} client(s) assigned to them. '
            f'Please reassign these clients first.'
        )
        return redirect('core:user_detail', user_id=user.id)

    if request.method == 'POST':
        user_name = user.get_full_name()
        user.delete()
        messages.success(request, f'User {user_name} deleted successfully!')
        return redirect('core:user_list')

    context = {
        'page_title': f'Delete User: {user.get_full_name()}',
        'staff_user': user,
    }

    return render(request, 'users/delete_confirm.html', context)


# =============================================================================
# ASSIGN USER TO BRANCH VIEW
# =============================================================================

@login_required
def user_assign_branch(request, user_id):
    """
    Assign or reassign a user to a branch

    Permissions: Admin, Director only
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to assign users to branches.')
        raise PermissionDenied

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = AssignBranchForm(request.POST)

        if form.is_valid():
            branch = form.cleaned_data['branch']
            notes = form.cleaned_data.get('notes', '')

            old_branch = user.branch
            user.branch = branch
            user.save()

            messages.success(
                request,
                f'{user.get_full_name()} successfully assigned to {branch.name} branch!'
            )

            return redirect('core:user_detail', user_id=user.id)
    else:
        form = AssignBranchForm(initial={'branch': user.branch})

    context = {
        'page_title': f'Assign Branch: {user.get_full_name()}',
        'form': form,
        'staff_user': user,
    }

    return render(request, 'users/assign_branch.html', context)


# =============================================================================
# USER PROFILE VIEW (Current User)
# =============================================================================

@login_required
def user_profile(request):
    """
    View current user's own profile

    Permissions: All authenticated users
    """
    user = request.user

    # Get assigned clients count if user is staff
    assigned_clients_count = 0
    if user.user_role == 'staff':
        assigned_clients_count = Client.objects.filter(assigned_staff=user).count()

    context = {
        'page_title': 'My Profile',
        'profile_user': user,
        'assigned_clients_count': assigned_clients_count,
    }

    return render(request, 'users/profile.html', context)


# =============================================================================
# USER PROFILE EDIT VIEW (Current User)
# =============================================================================

@login_required
def user_profile_edit(request):
    """
    Edit current user's own profile
    Users can only edit non-sensitive information

    Permissions: All authenticated users
    """
    user = request.user

    if request.method == 'POST':
        form = UserProfileUpdateForm(request.POST, request.FILES, instance=user)

        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('core:user_profile')
    else:
        form = UserProfileUpdateForm(instance=user)

    context = {
        'page_title': 'Edit My Profile',
        'form': form,
        'profile_user': user,
    }

    return render(request, 'users/profile_edit.html', context)
