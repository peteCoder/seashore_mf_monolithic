"""
Client Views
============

All client CRUD operations with role-based permissions
"""

import datetime
from datetime import date as date_type

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from decimal import Decimal

from core.models import Client, Loan, Transaction, CLIENT_REGISTRATION_FEE, CLIENT_REGISTRATION_FEE_BREAKDOWN, SavingsProduct, SavingsAccount
from core.utils.accounting_helpers import post_fee_collection_journal
from core.services.notification_service import notify, notify_role
from core.forms.client_forms import (
    ClientCreateForm,
    ClientUpdateForm,
    ClientSearchForm,
    ClientApprovalForm,
    AssignStaffForm,
    RegistrationFeePaymentForm,
)
from core.permissions import PermissionChecker


# Maps each form field name to its tab index (0-based) in the 5-tab client form
_CLIENT_FIELD_TAB = {
    # Tab 0 — Personal Info
    'first_name': 0, 'last_name': 0, 'nickname': 0, 'email': 0, 'phone': 0,
    'alternate_phone': 0, 'date_of_birth': 0, 'gender': 0, 'marital_status': 0,
    'number_of_dependents': 0, 'education_level': 0,
    # Tab 1 — Contact & Address
    'address': 1, 'city': 1, 'state': 1, 'postal_code': 1, 'country': 1,
    'landmark': 1, 'location': 1, 'residential_status': 1, 'union_location': 1,
    # Tab 2 — Identification & Documents
    'id_type': 2, 'id_number': 2, 'bvn': 2, 'profile_picture': 2,
    'id_card_front': 2, 'id_card_back': 2, 'signature': 2,
    # Tab 3 — Employment & Business
    'occupation': 3, 'employer': 3, 'monthly_income': 3, 'years_in_business': 3,
    'business_name': 3, 'business_type': 3, 'business_type_2': 3,
    'business_landmark': 3, 'business_location': 3, 'business_address': 3,
    # Tab 4 — Banking & Emergency Contact
    'account_number': 4, 'bank_name': 4, 'emergency_contact_name': 4,
    'emergency_contact_phone': 4, 'emergency_contact_relationship': 4,
    'emergency_contact_address': 4, 'branch': 4, 'group': 4,
    'group_role': 4, 'origin_channel': 4,
}


# =============================================================================
# CLIENT LIST VIEW
# =============================================================================

@login_required
def client_list(request):
    """
    Display paginated list of clients with search and filters

    Permissions: All authenticated users (role-filtered)
    - Admin/Director: See all clients
    - Manager: See branch clients only
    - Staff: See assigned clients only
    """
    checker = PermissionChecker(request.user)

    # Base queryset (role-filtered)
    clients = checker.filter_clients(Client.objects.all())

    # Search form
    search_form = ClientSearchForm(request.GET or None)

    # Apply filters
    if search_form.is_valid():
        search = search_form.cleaned_data.get('search')
        if search:
            clients = clients.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search) |
                Q(client_id__icontains=search)
            )

        branch = search_form.cleaned_data.get('branch')
        if branch:
            clients = clients.filter(branch=branch)

        status = search_form.cleaned_data.get('status')
        if status == 'active':
            clients = clients.filter(is_active=True)
        elif status == 'inactive':
            clients = clients.filter(is_active=False)

        approval_status = search_form.cleaned_data.get('approval_status')
        if approval_status:
            clients = clients.filter(approval_status=approval_status)

        date_from = search_form.cleaned_data.get('date_from')
        if date_from:
            clients = clients.filter(registration_date__gte=date_from)

        date_to = search_form.cleaned_data.get('date_to')
        if date_to:
            clients = clients.filter(registration_date__lte=date_to)

    # Prefetch related data for performance
    clients = clients.select_related('branch', 'group', 'assigned_staff').order_by('-created_at')

    # Excel export (respects all active filters)
    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_client_list_excel
        return export_client_list_excel(clients)

    # Pagination (25 per page)
    paginator = Paginator(clients, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Context
    context = {
        'page_title': 'Clients',
        'clients': page_obj,
        'search_form': search_form,
        'checker': checker,
        'total_count': clients.count(),
    }

    return render(request, 'clients/list.html', context)


# =============================================================================
# CLIENT DETAIL VIEW
# =============================================================================

@login_required
def client_detail(request, client_id):
    """
    Display comprehensive client information with related data

    Shows:
    - All client information
    - Active loans with repayment status
    - Savings accounts with balances
    - Recent transactions
    - Group membership
    - Assigned staff
    - Action buttons based on permissions
    """
    checker = PermissionChecker(request.user)

    # Get client with related data
    client = get_object_or_404(
        Client.objects.select_related('branch', 'group', 'assigned_staff', 'original_officer', 'approved_by'),
        id=client_id
    )

    # Permission check
    if not checker.can_view_client(client):
        messages.error(request, 'You do not have permission to view this client.')
        raise PermissionDenied

    # Excel export of ALL client transactions (no 15-row cap)
    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_client_transactions_excel
        all_transactions = client.transactions.all().order_by('transaction_date').select_related('processed_by', 'loan', 'savings_account')
        return export_client_transactions_excel(client, all_transactions)

    # Get related data
    loans = client.loans.all().order_by('-created_at')[:10]
    savings_accounts = client.savings_accounts.all().select_related('savings_product')
    # Fetch 15 most recent then reverse so newest appears at the bottom
    recent_transactions = list(client.transactions.all().order_by('-transaction_date').select_related('processed_by', 'loan', 'savings_account')[:15])
    recent_transactions.reverse()

    # Calculate financial summary
    total_loans = client.loans.filter(status__in=['active', 'disbursed', 'overdue']).aggregate(
        total=Sum('principal_amount'),
        outstanding=Sum('outstanding_balance')
    )

    total_savings = savings_accounts.filter(status='active').aggregate(
        total=Sum('balance')
    )

    # The loan a top-of-page "Call Client" button (in the main action bar,
    # not buried in the Loans tab) would place a reminder call about —
    # whichever outstanding loan is due/overdue soonest. None if the client
    # has no loan with an outstanding balance, in which case that button
    # doesn't render at all (nothing to remind them about).
    primary_call_loan = (
        client.loans
        .filter(status__in=['active', 'overdue', 'disbursed'], outstanding_balance__gt=0)
        .order_by('next_repayment_date')
        .first()
    )

    # For a deceased client, the detail page shows what still needs
    # resolving instead of blocking the "mark deceased" action on it —
    # loans need a write-off or insurance claim, savings need a withdrawal
    # (still allowed while frozen — see savings_views.py) then closure.
    unresolved_loans = None
    accounts_needing_resolution = None
    if client.is_deceased:
        unresolved_loans = client.loans.filter(
            status__in=['active', 'disbursed', 'overdue'], outstanding_balance__gt=0
        ).select_related('loan_product')
        accounts_needing_resolution = savings_accounts.filter(status='active', balance__gt=0)

    # Context
    context = {
        'page_title': f'Client: {client.get_full_name()}',
        'client': client,
        'loans': loans,
        'savings_accounts': savings_accounts,
        'recent_transactions': recent_transactions,
        'total_loans': total_loans['total'] or Decimal('0.00'),
        'total_outstanding': total_loans['outstanding'] or Decimal('0.00'),
        'total_savings': total_savings['total'] or Decimal('0.00'),
        'primary_call_loan': primary_call_loan,
        'unresolved_loans': unresolved_loans,
        'accounts_needing_resolution': accounts_needing_resolution,
        'checker': checker,
        'today': date_type.today(),
    }

    return render(request, 'clients/detail.html', context)


# =============================================================================
# CLIENT CREATE VIEW
# =============================================================================

@login_required
def client_create(request):
    """
    Create new client with multi-tab form

    5 Tabs:
    1. Personal Information
    2. Contact & Address
    3. Identification & Documents
    4. Employment & Business
    5. Banking & Emergency Contact

    Permissions: Staff, Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_create_client():
        messages.error(request, 'You do not have permission to create clients.')
        raise PermissionDenied

    if request.method == 'POST':
        form = ClientCreateForm(request.POST, request.FILES, user=request.user)

        if form.is_valid():
            client = form.save(commit=False)

            # Set defaults
            client.approval_status = 'draft'
            client.is_active = False

            # Whoever creates the client becomes the assigned staff until reassigned
            client.assigned_staff = request.user
            client.original_officer = request.user

            client.save()

            # Notify branch manager of new client registration
            branch = client.branch or request.user.branch
            notify_role(
                roles='manager',
                branch=branch,
                notification_type='client_registered',
                title='New Client Registration',
                message=f'A new client {client.get_full_name()} ({client.client_id}) has been registered and is pending approval.',
                related_client=client,
                exclude_user=request.user,
            )

            messages.success(
                request,
                f'Client {client.get_full_name()} created successfully! Client ID: {client.client_id}'
            )
            return redirect('core:client_detail', client_id=client.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ClientCreateForm(user=request.user)

    error_tab = min((_CLIENT_FIELD_TAB.get(f, 0) for f in form.errors), default=0)

    context = {
        'page_title': 'Register New Client',
        'form': form,
        'is_create': True,
        'error_tab': error_tab,
    }

    return render(request, 'clients/form.html', context)


# =============================================================================
# CLIENT UPDATE VIEW
# =============================================================================

@login_required
def client_update(request, client_id):
    """
    Update existing client information

    Uses same multi-tab form as create

    Permissions: Manager, Director, Admin (not Staff)
    - Manager: Can edit clients in their branch only
    - Director/Admin: Can edit any client
    """
    checker = PermissionChecker(request.user)

    client = get_object_or_404(Client, id=client_id)

    # Permission check
    if not checker.can_edit_client(client):
        messages.error(request, 'You do not have permission to edit this client.')
        raise PermissionDenied

    if request.method == 'POST':
        form = ClientUpdateForm(request.POST, request.FILES, instance=client, user=request.user)

        if form.is_valid():
            client = form.save()
            messages.success(request, f'Client {client.get_full_name()} updated successfully!')
            return redirect('core:client_detail', client_id=client.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ClientUpdateForm(instance=client, user=request.user)

    error_tab = min((_CLIENT_FIELD_TAB.get(f, 0) for f in form.errors), default=0)

    context = {
        'page_title': f'Edit Client: {client.get_full_name()}',
        'form': form,
        'client': client,
        'is_create': False,
        'error_tab': error_tab,
    }

    return render(request, 'clients/form.html', context)


# =============================================================================
# CLIENT APPROVE VIEW
# =============================================================================

@login_required
def client_approve(request, client_id):
    """
    Approve or reject client application

    Permissions: Manager, Director, Admin
    """
    checker = PermissionChecker(request.user)

    if not checker.can_approve_client():
        messages.error(request, 'You do not have permission to approve clients.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    # Can only approve draft or pending clients
    if client.approval_status not in ['draft', 'pending']:
        messages.error(request, 'This client cannot be approved. Only draft or pending clients can be approved.')
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        form = ClientApprovalForm(request.POST, fee_already_paid=client.registration_fee_paid)

        if form.is_valid():
            action = form.cleaned_data['action']
            notes = form.cleaned_data.get('notes', '')

            if action == 'approve':
                with transaction.atomic():
                    # Lock the row so concurrent submissions can't both process the fee
                    client = Client.objects.select_for_update().get(pk=client.pk)

                    client.approval_status = 'approved'
                    client.approved_by = request.user
                    client.approved_at = timezone.now()
                    client.approval_date = form.cleaned_data.get('approval_date')
                    # Use update_fields to avoid overwriting registration_fee_paid
                    # with a stale in-memory value from before this request started
                    client.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'approval_date'])

                    # Re-read from DB (select_for_update already gave us the latest)
                    if not client.registration_fee_paid:
                        payment_method = form.cleaned_data['payment_method']
                        fee_reference = form.cleaned_data.get('fee_reference', '')

                        payment_details = payment_method.replace('_', ' ').title()
                        if fee_reference:
                            payment_details += f' - Ref: {fee_reference}'

                        reg_txn_date = (
                            timezone.make_aware(datetime.datetime.combine(client.registration_date, datetime.time.min))
                            if client.registration_date else timezone.now()
                        )
                        first_txn = None
                        for item in CLIENT_REGISTRATION_FEE_BREAKDOWN:
                            txn = Transaction.objects.create(
                                client=client,
                                branch=client.branch,
                                transaction_type=item['key'],
                                amount=item['amount'],
                                payment_details=payment_details,
                                description=f"{item['label']} — {client.get_full_name()} via {payment_method.replace('_', ' ')}",
                                processed_by=request.user,
                                status='completed',
                                is_income=True,
                                transaction_date=reg_txn_date,
                            )
                            post_fee_collection_journal(
                                fee_type=item['key'],
                                amount=item['amount'],
                                client=client,
                                branch=client.branch,
                                processed_by=request.user,
                                transaction_obj=txn,
                            )
                            if first_txn is None:
                                first_txn = txn

                        client.registration_fee_paid = True
                        client.registration_fee_transaction = first_txn
                        client.save(update_fields=['registration_fee_paid', 'registration_fee_transaction'])

                    # Auto-create savings accounts for each selected product
                    selected_ids = request.POST.getlist('savings_product_ids')
                    accounts_created = 0
                    for pid in selected_ids:
                        try:
                            product = SavingsProduct.objects.get(id=pid, is_active=True)
                            already_exists = SavingsAccount.objects.filter(
                                client=client,
                                savings_product=product,
                                status__in=['pending', 'active'],
                            ).exists()
                            if not already_exists:
                                SavingsAccount.objects.create(
                                    client=client,
                                    savings_product=product,
                                    branch=client.branch,
                                    status='active',
                                    approved_by=request.user,
                                    approved_at=timezone.now(),
                                    is_auto_created=True,
                                    notes=f'Auto-created and activated during client approval by {request.user.get_full_name()}.',
                                )
                                accounts_created += 1
                        except SavingsProduct.DoesNotExist:
                            pass

                if accounts_created:
                    messages.success(
                        request,
                        f'Client {client.get_full_name()} approved and '
                        f'{accounts_created} savings account(s) created successfully.',
                    )
                else:
                    messages.success(request, f'Client {client.get_full_name()} approved successfully.')

                if client.assigned_staff:
                    notify(
                        user=client.assigned_staff,
                        notification_type='client_approved',
                        title='Client Approved',
                        message=f'Client {client.get_full_name()} ({client.client_id}) has been approved.',
                        related_client=client,
                    )
                notify_role(
                    roles='manager',
                    branch=client.branch,
                    notification_type='client_approved',
                    title='Client Approved',
                    message=f'Client {client.get_full_name()} ({client.client_id}) has been approved by {request.user.get_full_name()}.',
                    related_client=client,
                    exclude_user=request.user,
                )

            else:  # reject
                client.approval_status = 'rejected'
                client.approved_by = request.user
                client.approved_at = timezone.now()
                client.notes = notes
                client.save()

                messages.warning(request, f'Client {client.get_full_name()} rejected.')
                notify_role(
                    roles='manager',
                    branch=client.branch,
                    notification_type='client_rejected',
                    title='Client Rejected',
                    message=f'Client {client.get_full_name()} ({client.client_id}) was rejected by {request.user.get_full_name()}. Reason: {notes or "No reason given"}',
                    related_client=client,
                    is_urgent=True,
                    exclude_user=request.user,
                )

            return redirect('core:client_detail', client_id=client.id)
    else:
        form = ClientApprovalForm(fee_already_paid=client.registration_fee_paid)

    savings_products = SavingsProduct.objects.filter(is_active=True).order_by('name')

    context = {
        'page_title': f'Approve Client: {client.get_full_name()}',
        'client': client,
        'form': form,
        'savings_products': savings_products,
        'fee_breakdown': CLIENT_REGISTRATION_FEE_BREAKDOWN,
        'registration_fee': CLIENT_REGISTRATION_FEE,
    }

    return render(request, 'clients/approve.html', context)


# =============================================================================
# CLIENT ACTIVATE VIEW
# =============================================================================

@login_required
def client_activate(request, client_id):
    """
    Activate inactive client

    Permissions: Manager, Director, Admin

    Requirements:
    - Client must be approved
    - Client must be inactive
    - Registration fee must be paid
    """
    checker = PermissionChecker(request.user)

    if not checker.can_activate_client():
        messages.error(request, 'You do not have permission to activate clients.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    # Validation
    if client.is_active:
        messages.warning(request, 'This client is already active.')
        return redirect('core:client_detail', client_id=client.id)

    if client.approval_status != 'approved':
        messages.error(request, 'Client must be approved before activation.')
        return redirect('core:client_detail', client_id=client.id)

    if not client.registration_fee_paid:
        messages.error(request, 'Registration fee must be paid before activation.')
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        activation_date_str = request.POST.get('activation_date', '').strip()
        try:
            client.activation_date = date_type.fromisoformat(activation_date_str)
        except (ValueError, TypeError):
            client.activation_date = date_type.today()
        client.is_active = True
        client.save(update_fields=['is_active', 'activation_date', 'updated_at'])

        messages.success(request, f'Client {client.get_full_name()} activated successfully!')
        return redirect('core:client_detail', client_id=client.id)

    context = {
        'page_title': f'Activate Client: {client.get_full_name()}',
        'client': client,
    }

    return render(request, 'clients/activate_confirm.html', context)


# =============================================================================
# CLIENT DEACTIVATE VIEW
# =============================================================================

@login_required
def client_deactivate(request, client_id):
    """
    Deactivate active client

    Permissions: Manager, Director, Admin

    Checks:
    - Cannot deactivate if active loans exist
    """
    checker = PermissionChecker(request.user)

    if not checker.can_deactivate_client():
        messages.error(request, 'You do not have permission to deactivate clients.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    if not client.is_active:
        messages.warning(request, 'This client is already inactive.')
        return redirect('core:client_detail', client_id=client.id)

    # Check for active loans
    active_loans = client.loans.filter(status__in=['active', 'disbursed', 'overdue']).count()
    if active_loans > 0:
        messages.error(
            request,
            f'Cannot deactivate client with {active_loans} active loan(s). Please close all loans first.'
        )
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        reason = request.POST.get('reason', '')

        client.is_active = False
        client.notes = f"{client.notes}\n\nDeactivated: {reason}" if client.notes else f"Deactivated: {reason}"
        client.save()

        messages.success(request, f'Client {client.get_full_name()} deactivated successfully.')
        return redirect('core:client_detail', client_id=client.id)

    context = {
        'page_title': f'Deactivate Client: {client.get_full_name()}',
        'client': client,
    }

    return render(request, 'clients/deactivate_confirm.html', context)


# =============================================================================
# CLIENT DECEASED VIEWS
# =============================================================================

@login_required
def client_mark_deceased(request, client_id):
    """
    Mark a client as deceased.

    Deliberately does NOT require loans/savings to be resolved first — the
    death is often known before the paperwork is. Unresolved loans and
    savings balances are surfaced as a banner on the client detail page
    instead (see client_detail's unresolved_loans / accounts_needing_resolution).

    Permissions: Manager, Director, HR, Admin (same as activate/deactivate)
    """
    checker = PermissionChecker(request.user)
    if not checker.can_mark_deceased():
        messages.error(request, 'You do not have permission to mark clients as deceased.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    if client.is_deceased:
        messages.warning(request, 'This client is already marked as deceased.')
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        deceased_date_str = request.POST.get('deceased_date', '').strip()

        deceased_date = None
        if deceased_date_str:
            try:
                deceased_date = date_type.fromisoformat(deceased_date_str)
            except ValueError:
                deceased_date = None

        client.is_deceased = True
        client.deceased_date = deceased_date
        client.marked_deceased_by = request.user
        client.marked_deceased_at = timezone.now()
        note = f"Marked deceased{f' ({deceased_date})' if deceased_date else ''}: {reason}" if reason else "Marked deceased"
        client.notes = f"{client.notes}\n\n{note}" if client.notes else note
        client.save(update_fields=[
            'is_deceased', 'deceased_date', 'marked_deceased_by', 'marked_deceased_at',
            'notes', 'updated_at',
        ])

        messages.success(request, f'{client.get_full_name()} has been marked as deceased.')

    return redirect('core:client_detail', client_id=client.id)


@login_required
def client_unmark_deceased(request, client_id):
    """Undo an accidental "mark as deceased" — clears the flag and related fields."""
    checker = PermissionChecker(request.user)
    if not checker.can_unmark_deceased():
        messages.error(request, 'You do not have permission to change this.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    if not client.is_deceased:
        messages.warning(request, 'This client is not marked as deceased.')
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        client.is_deceased = False
        client.deceased_date = None
        client.marked_deceased_by = None
        client.marked_deceased_at = None
        note = f"Unmarked deceased by {request.user.get_full_name()}"
        client.notes = f"{client.notes}\n\n{note}" if client.notes else note
        client.save(update_fields=[
            'is_deceased', 'deceased_date', 'marked_deceased_by', 'marked_deceased_at',
            'notes', 'updated_at',
        ])

        messages.success(request, f'{client.get_full_name()} is no longer marked as deceased.')

    return redirect('core:client_detail', client_id=client.id)


# =============================================================================
# CLIENT DELETE VIEW
# =============================================================================

@login_required
def client_delete(request, client_id):
    """
    Soft delete client (admin only)

    Permissions: Admin only

    Requirements:
    - No active loans
    - No savings balance
    """
    checker = PermissionChecker(request.user)

    if not checker.can_delete_client():
        messages.error(request, 'You do not have permission to delete clients.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    # Validation
    active_loans = client.loans.filter(status__in=['active', 'disbursed', 'overdue']).count()
    if active_loans > 0:
        messages.error(request, f'Cannot delete client with {active_loans} active loan(s).')
        return redirect('core:client_detail', client_id=client.id)

    total_savings = client.savings_accounts.filter(status='active').aggregate(
        total=Sum('balance')
    )['total'] or Decimal('0.00')

    if total_savings > 0:
        messages.error(
            request,
            f'Cannot delete client with savings balance of ₦{total_savings:,.2f}. Please withdraw all funds first.'
        )
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        client_name = client.get_full_name()
        client.delete(hard=True)  # Permanent delete — admin only

        messages.success(request, f'Client {client_name} deleted successfully.')
        return redirect('core:client_list')

    context = {
        'page_title': f'Delete Client: {client.get_full_name()}',
        'client': client,
    }

    return render(request, 'clients/delete_confirm.html', context)


@login_required
def client_assign_staff(request, client_id):
    """
    Assign staff to a client

    Permissions: Manager, Director, Admin

    Requirements:
    - Staff must be from the same branch as the client
    """
    checker = PermissionChecker(request.user)

    # Check permissions - only managers, directors, and admins
    if not (checker.is_admin_or_director() or checker.is_manager()):
        messages.error(request, 'You do not have permission to assign staff to clients.')
        raise PermissionDenied

    client = get_object_or_404(Client, id=client_id)

    # Branch check for managers
    if checker.is_manager() and client.branch != request.user.branch:
        messages.error(request, 'You can only assign staff to clients in your branch.')
        raise PermissionDenied

    if request.method == 'POST':
        form = AssignStaffForm(request.POST, branch=client.branch)

        if form.is_valid():
            staff = form.cleaned_data['staff']
            notes = form.cleaned_data.get('notes', '')

            # Update client's assigned staff
            old_staff = client.assigned_staff
            client.assigned_staff = staff
            client.save()

            # Create notification or log entry (optional)
            if old_staff:
                messages.success(
                    request,
                    f'Client {client.get_full_name()} reassigned from {old_staff.get_full_name()} to {staff.get_full_name()}.'
                )
            else:
                messages.success(
                    request,
                    f'Staff {staff.get_full_name()} assigned to client {client.get_full_name()}.'
                )

            return redirect('core:client_detail', client_id=client.id)
    else:
        form = AssignStaffForm(branch=client.branch)

    context = {
        'page_title': f'Assign Staff: {client.get_full_name()}',
        'client': client,
        'form': form,
    }

    return render(request, 'clients/assign_staff.html', context)


# =============================================================================
# REGISTRATION FEE PAYMENT VIEW
# =============================================================================

@login_required
def client_pay_registration_fee(request, client_id):
    """
    Process registration fee payment for a client

    Permissions: All authenticated users (staff, manager, director, admin)
    This is a one-on-one interaction with the client
    """
    client = get_object_or_404(Client, id=client_id)

    # Check if registration fee is already paid
    if client.registration_fee_paid:
        messages.warning(request, 'Registration fee has already been paid for this client.')
        return redirect('core:client_detail', client_id=client.id)

    if request.method == 'POST':
        form = RegistrationFeePaymentForm(request.POST)

        if form.is_valid():
            payment_method = form.cleaned_data['payment_method']
            reference_number = form.cleaned_data.get('reference_number', '')
            notes = form.cleaned_data.get('notes', '')

            # Build payment details string
            payment_details = f"{payment_method.replace('_', ' ').title()}"
            if reference_number:
                payment_details += f" - Ref: {reference_number}"

            # Create one transaction + one journal entry per fee line item
            reg_txn_date = (
                timezone.make_aware(datetime.datetime.combine(client.registration_date, datetime.time.min))
                if client.registration_date else timezone.now()
            )
            first_transaction = None
            with transaction.atomic():
                for item in CLIENT_REGISTRATION_FEE_BREAKDOWN:
                    txn = Transaction.objects.create(
                        client=client,
                        branch=client.branch,
                        transaction_type=item['key'],
                        amount=item['amount'],
                        payment_details=payment_details,
                        description=f"{item['label']} — {client.get_full_name()} via {payment_method.replace('_', ' ')}",
                        notes=notes,
                        processed_by=request.user,
                        status='completed',
                        is_income=True,
                        transaction_date=reg_txn_date,
                    )
                    post_fee_collection_journal(
                        fee_type=item['key'],
                        amount=item['amount'],
                        client=client,
                        branch=client.branch,
                        processed_by=request.user,
                        transaction_obj=txn,
                    )
                    if first_transaction is None:
                        first_transaction = txn

                # Mark registration fee as paid
                client.registration_fee_paid = True
                client.registration_fee_transaction = first_transaction
                client.save()

            messages.success(
                request,
                f'Registration fee of ₦{CLIENT_REGISTRATION_FEE:,.2f} recorded successfully for {client.get_full_name()}!'
            )

            return redirect('core:client_detail', client_id=client.id)
    else:
        form = RegistrationFeePaymentForm()

    context = {
        'page_title': f'Pay Registration Fee: {client.get_full_name()}',
        'client': client,
        'form': form,
        'fee_breakdown': CLIENT_REGISTRATION_FEE_BREAKDOWN,
        'registration_fee': CLIENT_REGISTRATION_FEE,
    }

    return render(request, 'clients/pay_registration_fee.html', context)


# =============================================================================
# CLIENT STATEMENT VIEW
# =============================================================================

@login_required
def client_statement(request, client_id):
    """
    Printable client account statement.

    Shows a chronological ledger of all transactions for the client:
      - Loan disbursements & repayments
      - Savings deposits & withdrawals
      - Fee payments
      - Penalties

    Permissions: All authenticated users who can view the client.
    """
    checker = PermissionChecker(request.user)
    client = get_object_or_404(
        Client.objects.select_related('branch', 'assigned_staff'),
        id=client_id,
    )

    if not checker.can_view_client(client):
        raise PermissionDenied

    # Date range filter (default: last 12 months)
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')
    today = timezone.now().date()

    if date_from_str:
        try:
            from datetime import date
            date_from = date.fromisoformat(date_from_str)
        except ValueError:
            date_from = today.replace(month=1, day=1)
    else:
        date_from = today.replace(year=today.year - 1 if today.month > 1 else today.year - 1)

    if date_to_str:
        try:
            from datetime import date
            date_to = date.fromisoformat(date_to_str)
        except ValueError:
            date_to = today
    else:
        date_to = today

    transactions = (
        Transaction.objects.filter(
            client=client,
            transaction_date__date__range=[date_from, date_to],
        )
        .select_related('loan', 'savings_account', 'processed_by')
        .order_by('transaction_date')
    )

    # Outflow types: money leaving the bank (paid TO/FOR the client)
    _OUTFLOW = {'loan_disbursement', 'withdrawal'}

    # Evaluate queryset once so Python iteration caches the results
    transactions = list(transactions)

    # Reversed transactions (e.g. a duplicate disbursement corrected after the
    # fact) stay visible on the statement for the audit trail, but must not
    # count toward the running totals — they no longer reflect real movement.
    _countable = [t for t in transactions if t.status != 'reversed']
    total_out = sum(t.amount for t in _countable if t.transaction_type in _OUTFLOW)
    total_in  = sum(t.amount for t in _countable if t.transaction_type not in _OUTFLOW)

    if request.GET.get('export') == 'excel':
        from core.utils.excel_export import export_client_statement_excel
        return export_client_statement_excel(
            client, transactions, date_from, date_to,
            total_in, total_out, total_in - total_out,
        )

    context = {
        'page_title': f'Account Statement — {client.get_full_name()}',
        'client': client,
        'transactions': transactions,
        'transaction_count': len(transactions),
        'date_from': date_from,
        'date_to': date_to,
        'total_in': total_in,
        'total_out': total_out,
        'net_position': total_in - total_out,
        'today': today,
    }

    return render(request, 'clients/statement.html', context)


# =============================================================================
# CLIENT VOICE CALL REMINDER (manual, staff-initiated)
# =============================================================================

@login_required
def client_call_reminder(request, client_id, loan_id):
    """
    Place a one-off AI-voice reminder call to the client about a specific
    loan, triggered by the "Call" button on the client detail page's Loans
    tab. There is no automatic/scheduled calling — see core/voice_service.py.

    Same view permission as the client detail page itself: if you can see
    this client, you can call them about one of their loans.
    """
    checker = PermissionChecker(request.user)
    client = get_object_or_404(Client, id=client_id)

    if not checker.can_view_client(client):
        messages.error(request, 'You do not have permission to contact this client.')
        raise PermissionDenied

    if request.method != 'POST':
        return redirect('core:client_detail', client_id=client.id)

    loan = get_object_or_404(Loan, id=loan_id, client=client)

    if not client.phone:
        messages.error(request, 'This client has no phone number on file — no call was placed.')
        return redirect('core:client_detail', client_id=client.id)

    if not loan.outstanding_balance or loan.outstanding_balance <= 0:
        messages.warning(request, 'This loan has no outstanding balance — no reminder call was placed.')
        return redirect('core:client_detail', client_id=client.id)

    from core.voice_service import initiate_call
    # Loan.status is a stale DB cache only refreshed on save() (see
    # tracker_views._base_schedule_qs) and is effectively never 'overdue' in
    # practice — check next_repayment_date directly instead so the call's
    # wording ("is due on" vs "was due on... and is now overdue") is accurate.
    is_overdue = bool(loan.next_repayment_date and loan.next_repayment_date < date_type.today())
    purpose = 'overdue_alert' if is_overdue else 'manual'
    call_log = initiate_call(client, loan=loan, purpose=purpose, initiated_by=request.user)

    if call_log.status == 'failed':
        messages.error(request, f'Could not place the reminder call: {call_log.error_message}')
    else:
        messages.success(
            request,
            f'Reminder call placed to {client.get_full_name()} ({client.phone}) '
            f'about loan {loan.loan_number}.'
        )

    return redirect('core:client_detail', client_id=client.id)
