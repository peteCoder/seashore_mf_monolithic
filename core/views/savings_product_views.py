"""
Savings Product Views
=====================

CRUD operations for savings products (Admin/Director only)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Count

from core.models import SavingsProduct
from core.forms.product_forms import SavingsProductForm, SavingsProductSearchForm
from core.permissions import PermissionChecker


# =============================================================================
# SAVINGS PRODUCT LIST VIEW
# =============================================================================

@login_required
def savings_product_list(request):
    """
    Display paginated list of savings products with search and filters

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to manage products.')
        raise PermissionDenied

    # Base queryset
    products = SavingsProduct.objects.all()

    # Search form
    search_form = SavingsProductSearchForm(request.GET or None)

    # Apply filters
    if search_form.is_valid():
        search = search_form.cleaned_data.get('search')
        if search:
            products = products.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search)
            )

        product_type = search_form.cleaned_data.get('product_type')
        if product_type:
            products = products.filter(product_type=product_type)

        status = search_form.cleaned_data.get('status')
        if status == 'active':
            products = products.filter(is_active=True)
        elif status == 'inactive':
            products = products.filter(is_active=False)

    # Annotate with account count
    products = products.annotate(account_count=Count('accounts')).order_by('-created_at')

    # Pagination
    paginator = Paginator(products, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Savings Products',
        'products': page_obj,
        'search_form': search_form,
        'total_count': products.count(),
    }

    return render(request, 'products/savings/list.html', context)


# =============================================================================
# SAVINGS PRODUCT DETAIL VIEW
# =============================================================================

@login_required
def savings_product_detail(request, product_id):
    """
    Display comprehensive savings product information

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to view products.')
        raise PermissionDenied

    product = get_object_or_404(
        SavingsProduct.objects.annotate(account_count=Count('accounts')),
        id=product_id
    )

    # Get recent accounts
    recent_accounts = product.accounts.select_related('client', 'branch').order_by('-created_at')[:10]

    context = {
        'page_title': f'Savings Product: {product.name}',
        'product': product,
        'recent_accounts': recent_accounts,
    }

    return render(request, 'products/savings/detail.html', context)


# =============================================================================
# SAVINGS PRODUCT CREATE VIEW
# =============================================================================

@login_required
def savings_product_create(request):
    """
    Create new savings product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to create products.')
        raise PermissionDenied

    if request.method == 'POST':
        form = SavingsProductForm(request.POST)

        if form.is_valid():
            product = form.save(commit=False)
            product.is_active = True  # New products are active by default
            product.save()

            messages.success(
                request,
                f'Savings product {product.name} ({product.code}) created successfully!'
            )
            return redirect('core:savings_product_detail', product_id=product.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SavingsProductForm()

    context = {
        'page_title': 'Create Savings Product',
        'form': form,
        'is_create': True,
    }

    return render(request, 'products/savings/form.html', context)


# =============================================================================
# SAVINGS PRODUCT UPDATE VIEW
# =============================================================================

@login_required
def savings_product_update(request, product_id):
    """
    Update existing savings product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to edit products.')
        raise PermissionDenied

    product = get_object_or_404(SavingsProduct, id=product_id)

    if request.method == 'POST':
        form = SavingsProductForm(request.POST, instance=product)

        if form.is_valid():
            product = form.save()
            messages.success(request, f'Savings product {product.name} updated successfully!')
            return redirect('core:savings_product_detail', product_id=product.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SavingsProductForm(instance=product)

    context = {
        'page_title': f'Edit Savings Product: {product.name}',
        'form': form,
        'product': product,
        'is_create': False,
    }

    return render(request, 'products/savings/form.html', context)


# =============================================================================
# SAVINGS PRODUCT ACTIVATE VIEW
# =============================================================================

@login_required
def savings_product_activate(request, product_id):
    """
    Activate inactive savings product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to activate products.')
        raise PermissionDenied

    product = get_object_or_404(SavingsProduct, id=product_id)

    if product.is_active:
        messages.warning(request, 'This product is already active.')
        return redirect('core:savings_product_detail', product_id=product.id)

    if request.method == 'POST':
        product.is_active = True
        product.save()

        messages.success(request, f'Savings product {product.name} activated successfully!')
        return redirect('core:savings_product_detail', product_id=product.id)

    context = {
        'page_title': f'Activate Savings Product: {product.name}',
        'product': product,
    }

    return render(request, 'products/savings/activate_confirm.html', context)


# =============================================================================
# SAVINGS PRODUCT DEACTIVATE VIEW
# =============================================================================

@login_required
def savings_product_deactivate(request, product_id):
    """
    Deactivate active savings product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to deactivate products.')
        raise PermissionDenied

    product = get_object_or_404(SavingsProduct, id=product_id)

    if not product.is_active:
        messages.warning(request, 'This product is already inactive.')
        return redirect('core:savings_product_detail', product_id=product.id)

    if request.method == 'POST':
        product.is_active = False
        product.save()

        messages.success(request, f'Savings product {product.name} deactivated successfully.')
        return redirect('core:savings_product_detail', product_id=product.id)

    context = {
        'page_title': f'Deactivate Savings Product: {product.name}',
        'product': product,
    }

    return render(request, 'products/savings/deactivate_confirm.html', context)


# =============================================================================
# SAVINGS PRODUCT DELETE VIEW
# =============================================================================

@login_required
def savings_product_delete(request, product_id):
    """
    Soft delete savings product (admin only)

    Permissions: Admin only

    Requirements:
    - No active accounts
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin():
        messages.error(request, 'Only administrators can delete products.')
        raise PermissionDenied

    product = get_object_or_404(SavingsProduct, id=product_id)

    # Check for active accounts
    active_accounts = product.accounts.filter(status='active').count()
    if active_accounts > 0:
        messages.error(request, f'Cannot delete product with {active_accounts} active account(s).')
        return redirect('core:savings_product_detail', product_id=product.id)

    if request.method == 'POST':
        product_name = product.name
        product.delete()  # Soft delete

        messages.success(request, f'Savings product {product_name} deleted successfully.')
        return redirect('core:savings_product_list')

    context = {
        'page_title': f'Delete Savings Product: {product.name}',
        'product': product,
    }

    return render(request, 'products/savings/delete_confirm.html', context)
