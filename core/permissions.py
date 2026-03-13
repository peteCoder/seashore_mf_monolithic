"""
Permission System – Role-based Access Control
==============================================

Roles (lowest → highest):   staff  →  manager  →  director / hr  →  admin

The 'hr' (Human Resources Manager) role has the same access level as
'director' across the entire application.

Every view that mutates state should:
    checker = PermissionChecker(request.user)
    if not checker.<method>(...):  raise PermissionDenied
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q


# =============================================================================
# CONSTANTS
# =============================================================================

class Roles:
    ADMIN    = 'admin'
    DIRECTOR = 'director'
    HR       = 'hr'
    MANAGER  = 'manager'
    STAFF    = 'staff'


class Permissions:
    """Single source of truth.  Views must never hard-code role lists.

    HR has the same access level as DIRECTOR everywhere.
    """

    # ── visibility ───────────────────────────────────────────────────
    VIEW_ALL_BRANCHES  = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]
    VIEW_OWN_BRANCH    = [Roles.MANAGER]
    VIEW_ASSIGNED_ONLY = [Roles.STAFF]

    # ── approvals ────────────────────────────────────────────────────
    CAN_APPROVE_CLIENTS      = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    CAN_APPROVE_LOANS        = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    CAN_APPROVE_TRANSACTIONS = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    CAN_APPROVE_USERS        = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]

    # ── management ───────────────────────────────────────────────────
    CAN_MANAGE_BRANCHES          = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]
    CAN_MANAGE_USERS             = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]
    CAN_MANAGE_PRODUCTS          = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]
    CAN_MANAGE_CHART_OF_ACCOUNTS = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]

    # ── financial ────────────────────────────────────────────────────
    CAN_DISBURSE_LOANS       = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    CAN_PROCESS_TRANSACTIONS = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER, Roles.STAFF]
    CAN_VIEW_REPORTS         = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    CAN_VIEW_FINANCIALS      = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR]

    # ── creation ─────────────────────────────────────────────────────
    CAN_CREATE_CLIENTS  = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER, Roles.STAFF]
    CAN_CREATE_LOANS    = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER, Roles.STAFF]
    CAN_RECORD_PAYMENTS = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER, Roles.STAFF]

    # ── client lifecycle  ────────────────────────────────────────────
    # Full-form edit.  Staff excluded deliberately.
    CAN_EDIT_CLIENT          = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    # Soft-delete.  Admin only, no exceptions.
    CAN_DELETE_CLIENT        = [Roles.ADMIN]
    # Approve / reject a pending client.
    CAN_APPROVE_REJECT_CLIENT = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    # Toggle active / inactive.
    CAN_TOGGLE_CLIENT_STATUS  = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]
    # Reassign loan officer.
    CAN_ASSIGN_CLIENT_STAFF   = [Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER]


# =============================================================================
# PERMISSION CHECKER
# =============================================================================

class PermissionChecker:

    def __init__(self, user):
        self.user   = user
        self.role   = user.user_role if user.is_authenticated else None
        self.branch = getattr(user, 'branch', None) if user.is_authenticated else None

    # ── role helpers ─────────────────────────────────────────────────
    def is_admin(self):             return self.role == Roles.ADMIN
    def is_director(self):          return self.role == Roles.DIRECTOR
    def is_hr(self):                return self.role == Roles.HR
    def is_manager(self):           return self.role == Roles.MANAGER
    def is_staff(self):             return self.role == Roles.STAFF
    # HR has director-level access everywhere — always include HR alongside DIRECTOR
    def is_admin_or_director(self): return self.role in (Roles.ADMIN, Roles.DIRECTOR, Roles.HR)

    # =========================================================================
    # VIEW / READ
    # =========================================================================

    def can_view_all_branches(self):
        return self.role in Permissions.VIEW_ALL_BRANCHES

    def can_view_branch(self, branch):
        if self.can_view_all_branches():
            return True
        return self.is_manager() and branch == self.branch

    def can_view_client(self, client):
        if self.can_view_all_branches():
            return True
        if self.is_manager():
            return client.branch == self.branch
        if self.is_staff():
            return client.assigned_staff == self.user
        return False

    def can_view_loan(self, loan):
        if self.can_view_client(loan.client):
            return True
        return (
            loan.created_by  == self.user
            or loan.approved_by  == self.user
            or loan.disbursed_by == self.user
        )

    def can_view_transaction(self, transaction):
        if transaction.client:
            return self.can_view_client(transaction.client)
        if self.can_view_all_branches():
            return True
        return transaction.branch == self.branch

    # =========================================================================
    # APPROVALS
    # =========================================================================

    def can_approve_clients(self):
        return self.role in Permissions.CAN_APPROVE_CLIENTS

    def can_approve_loans(self):
        return self.role in Permissions.CAN_APPROVE_LOANS

    def can_approve_loan_amount(self, amount):
        if not self.can_approve_loans():
            return False
        if self.is_admin_or_director():
            return True
        if self.is_manager() and getattr(self.user, 'can_approve_loans', False):
            max_amt = getattr(self.user, 'max_approval_amount', None)
            if max_amt:
                from decimal import Decimal
                return Decimal(str(amount)) <= max_amt
            return True
        return False

    def can_approve_transactions(self):
        return self.role in Permissions.CAN_APPROVE_TRANSACTIONS

    def can_approve_users(self):
        return self.role in Permissions.CAN_APPROVE_USERS

    # =========================================================================
    # MANAGEMENT
    # =========================================================================

    def can_manage_branches(self):          return self.role in Permissions.CAN_MANAGE_BRANCHES
    def can_manage_users(self):             return self.role in Permissions.CAN_MANAGE_USERS
    def can_manage_products(self):          return self.role in Permissions.CAN_MANAGE_PRODUCTS
    def can_manage_chart_of_accounts(self): return self.role in Permissions.CAN_MANAGE_CHART_OF_ACCOUNTS

    # =========================================================================
    # FINANCIAL
    # =========================================================================

    def can_disburse_loans(self):           return self.role in Permissions.CAN_DISBURSE_LOANS
    def can_disburse_loan(self):            return self.can_disburse_loans()          # alias
    def can_process_transactions(self):     return self.role in Permissions.CAN_PROCESS_TRANSACTIONS
    def can_process_transaction(self):      return self.can_process_transactions()   # alias
    def can_view_reports(self):             return self.role in Permissions.CAN_VIEW_REPORTS
    def can_view_financials(self):          return self.role in Permissions.CAN_VIEW_FINANCIALS

    # =========================================================================
    # CLIENT LIFECYCLE  ← core of this rewrite
    # =========================================================================

    def can_create_client(self):
        return self.role in Permissions.CAN_CREATE_CLIENTS

    # -----------------------------------------------------------------
    # EDIT  – admin / director / manager
    # -----------------------------------------------------------------
    def can_edit_client(self, client=None):
        if not self.user or not self.user.is_authenticated:
            return False
        if self.role not in Permissions.CAN_EDIT_CLIENT:
            return False
        if self.is_admin_or_director():
            return True
        # manager: own branch only (or True when no client passed – flag check)
        if self.is_manager():
            return (
                True if client is None
                else (client.branch_id == self.user.branch_id if self.user.branch_id else False)
            )
        return False

    # -----------------------------------------------------------------
    # DELETE  – admin only
    # -----------------------------------------------------------------
    def can_delete_client(self, client=None):
        return self.role in Permissions.CAN_DELETE_CLIENT

    # -----------------------------------------------------------------
    # APPROVE  – pending → approved
    # -----------------------------------------------------------------
    def can_approve_client(self, client=None):
        return self.role in Permissions.CAN_APPROVE_REJECT_CLIENT

    # -----------------------------------------------------------------
    # REJECT  – pending → rejected
    # -----------------------------------------------------------------
    def can_reject_client(self, client=None):
        return self.role in Permissions.CAN_APPROVE_REJECT_CLIENT

    # -----------------------------------------------------------------
    # ACTIVATE  – inactive → active
    # -----------------------------------------------------------------
    def can_activate_client(self, client=None):
        return self.role in Permissions.CAN_TOGGLE_CLIENT_STATUS

    # -----------------------------------------------------------------
    # DEACTIVATE  – active → inactive
    # -----------------------------------------------------------------
    def can_deactivate_client(self, client=None):
        return self.role in Permissions.CAN_TOGGLE_CLIENT_STATUS

    # -----------------------------------------------------------------
    # ASSIGN STAFF
    # -----------------------------------------------------------------
    def can_assign_staff(self):
        return self.role in Permissions.CAN_ASSIGN_CLIENT_STAFF

    # =========================================================================
    # LOAN
    # =========================================================================

    def can_create_loan(self):
        return self.role in Permissions.CAN_CREATE_LOANS

    def can_edit_loan(self, loan):
        if not self.user or not self.user.is_authenticated:
            return False
        if loan.status not in ('pending_fees', 'pending_approval', 'rejected'):
            return False
        if self.is_admin_or_director():
            return True
        if self.is_manager():
            return loan.branch_id == self.user.branch_id if self.user.branch_id else False
        if self.is_staff():
            return (
                hasattr(loan.client, 'assigned_staff_id')
                and loan.client.assigned_staff_id == self.user.id
            )
        return False

    def can_delete_loan(self, loan):
        if loan.status not in ('pending_approval', 'rejected'):
            return False
        return self.is_admin_or_director()

    def can_record_payment(self):
        return self.role in Permissions.CAN_RECORD_PAYMENTS

    # =========================================================================
    # SAVINGS
    # =========================================================================

    def can_create_savings_account(self):
        return self.role in (Roles.STAFF, Roles.MANAGER, Roles.DIRECTOR, Roles.HR, Roles.ADMIN)

    def can_edit_savings_account(self, account):
        if not self.user or not self.user.is_authenticated:
            return False
        if self.role in (Roles.ADMIN, Roles.DIRECTOR, Roles.HR):
            return True
        if self.is_manager():
            return account.branch_id == self.user.branch_id if self.user.branch_id else False
        if self.is_staff():
            return (
                hasattr(account.client, 'assigned_staff_id')
                and account.client.assigned_staff_id == self.user.id
            )
        return False

    def can_approve_accounts(self):
        return self.role in (Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER)

    def can_close_savings_account(self, account):
        if not self.user or not self.user.is_authenticated:
            return False
        if self.role in (Roles.ADMIN, Roles.DIRECTOR, Roles.HR):
            return True
        if self.is_manager():
            return account.branch_id == self.user.branch_id if self.user.branch_id else False
        return False

    def can_delete_savings_account(self, account):
        if not self.user or not self.user.is_authenticated:
            return False
        return self.role in (Roles.DIRECTOR, Roles.HR, Roles.ADMIN)

    def filter_savings_accounts(self, queryset):
        if not self.user or not self.user.is_authenticated:
            return queryset.none()
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() and self.branch:
            return queryset.filter(branch=self.branch)
        if self.is_staff():
            return queryset.filter(client__assigned_staff=self.user)
        return queryset.none()

    # =========================================================================
    # GROUPS
    # =========================================================================

    def can_manage_groups(self):
        return self.role in (Roles.ADMIN, Roles.DIRECTOR, Roles.HR, Roles.MANAGER)

    def can_view_group(self, group):
        if self.can_view_all_branches():
            return True
        if self.is_manager():
            return group.branch == self.branch
        if self.is_staff():
            return group.loan_officer == self.user
        return False

    def can_edit_group(self, group):
        if not self.user or not self.user.is_authenticated:
            return False
        if self.is_admin_or_director():
            return True
        if self.is_manager():
            return group.branch_id == self.user.branch_id if self.user.branch_id else False
        return False

    def can_delete_group(self, group):
        return self.is_admin()

    def can_add_group_members(self, group):
        if not self.user or not self.user.is_authenticated:
            return False
        if self.is_admin_or_director():
            return True
        if self.is_manager():
            return group.branch_id == self.user.branch_id if self.user.branch_id else False
        return False

    def can_remove_group_members(self, group):
        return self.can_add_group_members(group)

    def filter_groups(self, queryset):
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() and self.branch:
            return queryset.filter(branch=self.branch)
        if self.is_staff():
            return queryset.filter(loan_officer=self.user)
        return queryset.none()

    # =========================================================================
    # COLLECTIONS
    # =========================================================================

    def can_view_collection_session(self, session):
        if self.can_view_all_branches():
            return True
        if self.is_manager():
            return session.group.branch == self.user.branch
        return session.collected_by == self.user

    def can_approve_collections(self):
        return self.is_manager() or self.can_view_all_branches()

    def filter_client_groups(self, queryset):
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() or self.is_staff():
            return queryset.filter(branch=self.user.branch)
        return queryset.none()

    def can_view_client_group(self, group):
        if self.can_view_all_branches():
            return True
        if self.is_manager() or self.is_staff():
            return group.branch == self.user.branch
        return False

    def can_view_group(self, group):
        """Check if user can view a specific group (alias for can_view_client_group)"""
        return self.can_view_client_group(group)

    def can_edit_group(self, group):
        """Check if user can edit a specific group"""
        if self.is_admin_or_director():
            return True
        if self.is_manager() and group.branch == self.user.branch:
            return True
        if self.is_staff() and group.loan_officer == self.user:
            return True
        return False

    # =========================================================================
    # QUERYSET FILTERS
    # =========================================================================

    def filter_branches(self, queryset):
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() and self.branch:
            return queryset.filter(id=self.branch.id)
        return queryset.none()

    def filter_clients(self, queryset):
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() and self.branch:
            return queryset.filter(branch=self.branch)
        if self.is_staff():
            return queryset.filter(assigned_staff=self.user)
        return queryset.none()

    def filter_loans(self, queryset):
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() and self.branch:
            return queryset.filter(branch=self.branch)
        if self.is_staff():
            return queryset.filter(
                Q(client__assigned_staff=self.user) | Q(created_by=self.user)
            )
        return queryset.none()

    def filter_transactions(self, queryset):
        if self.can_view_all_branches():
            return queryset
        if self.is_manager() and self.branch:
            return queryset.filter(branch=self.branch)
        if self.is_staff():
            return queryset.filter(
                Q(client__assigned_staff=self.user) | Q(processed_by=self.user)
            )
        return queryset.none()


# =============================================================================
# DECORATORS
# =============================================================================

def login_required_with_role(allowed_roles=None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('core:login')
            if allowed_roles and request.user.user_role not in allowed_roles:
                messages.error(request, 'You do not have permission to access this page.')
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def permission_required(permission_check):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, 'Please log in to access this page.')
                return redirect('core:login')
            checker = PermissionChecker(request.user)
            if not getattr(checker, permission_check)():
                messages.error(request, 'You do not have permission to perform this action.')
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def branch_access_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please log in to access this page.')
            return redirect('core:login')
        from core.models import Branch
        branch_id = kwargs.get('branch_id') or kwargs.get('pk')
        if branch_id:
            try:
                branch = Branch.objects.get(id=branch_id)
                if not PermissionChecker(request.user).can_view_branch(branch):
                    messages.error(request, 'You do not have access to this branch.')
                    raise PermissionDenied
            except Branch.DoesNotExist:
                messages.error(request, 'Branch not found.')
                raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_user_branches(user):
    from core.models import Branch
    return PermissionChecker(user).filter_branches(Branch.objects.all())


def get_user_clients(user):
    from core.models import Client
    return PermissionChecker(user).filter_clients(Client.objects.all())


def can_user_edit_client(user, client):
    return PermissionChecker(user).can_edit_client(client)


def can_user_approve_loan(user, loan):
    checker = PermissionChecker(user)
    if not checker.can_approve_loans():
        return False
    return checker.can_approve_loan_amount(loan.principal_amount)


