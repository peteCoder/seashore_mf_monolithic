"""
AJAX views for the multi-tab client registration form.

Three endpoints:
  POST  /clients/ajax/validate-tab/          — validate one tab's fields server-side
  POST  /clients/ajax/create/               — create the client once all tabs pass
  POST  /clients/<uuid>/ajax/update/        — update an existing client
  GET   /clients/ajax/savings-accounts/     — list a client's active savings accounts
  GET   /clients/ajax/details/             — return a client's details for auto-population
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.forms.client_forms import ClientCreateForm, ClientUpdateForm
from core.models import Client, SavingsAccount
from core.permissions import PermissionChecker


# ── Field→tab mapping ─────────────────────────────────────────────────────────

# Lists the form field names that belong to each tab (0-indexed).
_TAB_FIELDS = {
    0: [
        'first_name', 'last_name', 'nickname', 'email', 'phone',
        'alternate_phone', 'date_of_birth', 'gender', 'marital_status',
        'number_of_dependents', 'education_level',
    ],
    1: [
        'address', 'city', 'state', 'postal_code', 'country',
        'landmark', 'location', 'residential_status', 'union_location',
    ],
    2: [
        'id_type', 'id_number', 'bvn',
        'profile_picture', 'id_card_front', 'id_card_back', 'signature',
    ],
    3: [
        'occupation', 'employer', 'monthly_income', 'years_in_business',
        'business_name', 'business_type', 'business_type_2',
        'business_landmark', 'business_location', 'business_address',
    ],
    4: [
        'account_number', 'bank_name',
        'emergency_contact_name', 'emergency_contact_phone',
        'emergency_contact_relationship', 'emergency_contact_address',
        'branch', 'group', 'group_role', 'origin_channel',
    ],
}

# Inverse: field name → tab index (used to find which tab to show on submit errors)
_FIELD_TAB = {
    field: tab
    for tab, fields in _TAB_FIELDS.items()
    for field in fields
}


# ── Validation endpoint ───────────────────────────────────────────────────────

@login_required
@require_POST
def client_validate_tab(request):
    """
    Validate a single tab of the client registration form.

    POST body: tab=<int>  +  all field values for that tab (multipart/form-data).

    Response:
        { "valid": true }
        { "valid": false, "errors": { "<field>": ["<message>", ...], ... } }
    """
    checker = PermissionChecker(request.user)
    if not checker.can_create_client():
        return JsonResponse(
            {'valid': False, 'errors': {'__all__': ['Permission denied.']}},
            status=403,
        )

    try:
        tab = int(request.POST.get('tab', 0))
    except (TypeError, ValueError):
        tab = 0

    tab_fields = _TAB_FIELDS.get(tab, [])

    # Instantiate the full form so every custom validator and model-level
    # check runs (e.g. unique email).  We then filter errors to the
    # current tab only — errors on other tabs are expected and ignored.
    form = ClientCreateForm(request.POST, request.FILES, user=request.user)
    form.is_valid()  # populates form.errors; return value intentionally ignored

    errors = {
        field: list(msgs)
        for field, msgs in form.errors.items()
        if field in tab_fields
    }

    return JsonResponse({'valid': not errors, 'errors': errors})


# ── Create endpoint ───────────────────────────────────────────────────────────

@login_required
@require_POST
def client_create_ajax(request):
    """
    Create a client from the complete multi-tab form.

    POST body: all field values + files (multipart/form-data).

    Response (success):
        { "success": true, "redirect_url": "...", "message": "..." }
    Response (failure):
        { "success": false, "errors": { "<field>": [...] }, "error_tab": <int> }
    """
    checker = PermissionChecker(request.user)
    if not checker.can_create_client():
        return JsonResponse(
            {'success': False, 'errors': {'__all__': ['Permission denied.']}},
            status=403,
        )

    form = ClientCreateForm(request.POST, request.FILES, user=request.user)

    if form.is_valid():
        client = form.save(commit=False)
        client.approval_status = 'draft'
        client.is_active = False
        if request.user.user_role == 'staff':
            client.assigned_staff = request.user
            client.original_officer = request.user
        try:
            client.save()
        except Exception as exc:
            return JsonResponse(
                {'success': False, 'errors': {'__all__': [str(exc)]}},
                status=500,
            )

        return JsonResponse({
            'success': True,
            'message': (
                f'Client {client.get_full_name()} registered successfully! '
                f'Client ID: {client.client_id}'
            ),
            'redirect_url': reverse(
                'core:client_detail', kwargs={'client_id': client.id}
            ),
        })

    # Build error map and determine which tab to show first
    errors = {field: list(msgs) for field, msgs in form.errors.items()}
    first_error_tab = min(
        (_FIELD_TAB.get(f, 0) for f in errors if f != '__all__'),
        default=0,
    )

    return JsonResponse(
        {'success': False, 'errors': errors, 'error_tab': first_error_tab},
        status=400,
    )


# ── Update endpoint ───────────────────────────────────────────────────────────

@login_required
@require_POST
def client_update_ajax(request, client_id):
    """
    Update an existing client from the complete multi-tab form.

    POST body: all field values + files (multipart/form-data).

    Response (success):
        { "success": true, "redirect_url": "...", "message": "..." }
    Response (failure):
        { "success": false, "errors": { "<field>": [...] }, "error_tab": <int> }
    """
    client = get_object_or_404(Client, id=client_id)

    checker = PermissionChecker(request.user)
    if not checker.can_edit_client(client):
        return JsonResponse(
            {'success': False, 'errors': {'__all__': ['Permission denied.']}},
            status=403,
        )

    form = ClientUpdateForm(request.POST, request.FILES, instance=client, user=request.user)

    if form.is_valid():
        try:
            client = form.save()
        except Exception as exc:
            return JsonResponse(
                {'success': False, 'errors': {'__all__': [str(exc)]}},
                status=500,
            )

        return JsonResponse({
            'success': True,
            'message': f'Client {client.get_full_name()} updated successfully!',
            'redirect_url': reverse(
                'core:client_detail', kwargs={'client_id': client.id}
            ),
        })

    errors = {field: list(msgs) for field, msgs in form.errors.items()}
    first_error_tab = min(
        (_FIELD_TAB.get(f, 0) for f in errors if f != '__all__'),
        default=0,
    )

    return JsonResponse(
        {'success': False, 'errors': errors, 'error_tab': first_error_tab},
        status=400,
    )


# ── Client savings accounts lookup ────────────────────────────────────────────

@login_required
def client_savings_accounts(request):
    """
    Return a client's active savings accounts as JSON for the loan form dropdown.

    GET /clients/ajax/savings-accounts/?client_id=UUID
    Response: { "accounts": [{ "id": "...", "label": "..." }, ...] }
    """
    client_id = request.GET.get('client_id', '').strip()
    if not client_id:
        return JsonResponse({'accounts': []})

    client = get_object_or_404(Client, id=client_id)
    accounts = (
        SavingsAccount.objects
        .filter(client=client, status='active')
        .select_related('savings_product')
        .order_by('account_number')
    )
    data = [
        {
            'id': str(acc.id),
            'label': f"{acc.account_number} — {acc.savings_product.name} (₦{acc.balance:,.2f})",
        }
        for acc in accounts
    ]
    return JsonResponse({'accounts': data})


# ── Client details lookup ──────────────────────────────────────────────────────

@login_required
def client_details(request):
    """
    Return a client's personal details as JSON for guarantor form auto-population.

    GET /clients/ajax/details/?client_id=UUID
    Response: { "name": "...", "phone": "...", "email": "...", "address": "...",
                "occupation": "...", "employer": "...", "monthly_income": "...",
                "id_type": "...", "id_number": "..." }
    """
    client_id = request.GET.get('client_id', '').strip()
    if not client_id:
        return JsonResponse({'error': 'client_id required'}, status=400)

    client = get_object_or_404(Client, id=client_id)
    return JsonResponse({
        'name': client.get_full_name(),
        'phone': client.phone or '',
        'email': client.email or '',
        'address': client.address or '',
        'occupation': client.occupation or '',
        'employer': client.employer or '',
        'monthly_income': str(client.monthly_income) if client.monthly_income else '',
        'id_type': client.id_type or '',
        'id_number': client.id_number or '',
    })
