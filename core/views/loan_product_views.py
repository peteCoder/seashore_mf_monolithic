"""
Loan Product Views
==================

CRUD operations for loan products (Admin/Director only)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Count

from core.models import LoanProduct
from core.forms.product_forms import LoanProductForm, LoanProductSearchForm
from core.permissions import PermissionChecker


# =============================================================================
# LOAN PRODUCT LIST VIEW
# =============================================================================

@login_required
def loan_product_list(request):
    """
    Display paginated list of loan products with search and filters

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    # Permission check
    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to manage products.')
        raise PermissionDenied

    # Base queryset
    products = LoanProduct.objects.all()

    # Search form
    search_form = LoanProductSearchForm(request.GET or None)

    # Apply filters
    if search_form.is_valid():
        search = search_form.cleaned_data.get('search')
        if search:
            products = products.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search)
            )

        loan_type = search_form.cleaned_data.get('loan_type')
        if loan_type:
            products = products.filter(loan_type=loan_type)

        status = search_form.cleaned_data.get('status')
        if status == 'active':
            products = products.filter(is_active=True)
        elif status == 'inactive':
            products = products.filter(is_active=False)

    # Annotate with loan count
    products = products.annotate(loan_count=Count('loans')).order_by('-created_at')

    # Pagination
    paginator = Paginator(products, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Loan Products',
        'products': page_obj,
        'search_form': search_form,
        'total_count': products.count(),
    }

    return render(request, 'products/loans/list.html', context)


# =============================================================================
# LOAN PRODUCT DETAIL VIEW
# =============================================================================

@login_required
def loan_product_detail(request, product_id):
    """
    Display comprehensive loan product information

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to view products.')
        raise PermissionDenied

    product = get_object_or_404(
        LoanProduct.objects.annotate(loan_count=Count('loans')),
        id=product_id
    )

    # Get recent loans
    recent_loans = product.loans.select_related('client', 'branch').order_by('-created_at')[:10]

    context = {
        'page_title': f'Loan Product: {product.name}',
        'product': product,
        'recent_loans': recent_loans,
    }

    return render(request, 'products/loans/detail.html', context)


# =============================================================================
# LOAN PRODUCT CREATE VIEW
# =============================================================================

@login_required
def loan_product_create(request):
    """
    Create new loan product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to create products.')
        raise PermissionDenied

    if request.method == 'POST':
        form = LoanProductForm(request.POST)

        if form.is_valid():
            product = form.save(commit=False)
            product.is_active = True  # New products are active by default
            product.save()

            messages.success(
                request,
                f'Loan product {product.name} ({product.code}) created successfully!'
            )
            return redirect('core:loan_product_detail', product_id=product.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = LoanProductForm()

    context = {
        'page_title': 'Create Loan Product',
        'form': form,
        'is_create': True,
    }

    return render(request, 'products/loans/form.html', context)


# =============================================================================
# LOAN PRODUCT UPDATE VIEW
# =============================================================================

@login_required
def loan_product_update(request, product_id):
    """
    Update existing loan product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to edit products.')
        raise PermissionDenied

    product = get_object_or_404(LoanProduct, id=product_id)

    if request.method == 'POST':
        form = LoanProductForm(request.POST, instance=product)

        if form.is_valid():
            product = form.save()
            messages.success(request, f'Loan product {product.name} updated successfully!')
            return redirect('core:loan_product_detail', product_id=product.id)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = LoanProductForm(instance=product)

    context = {
        'page_title': f'Edit Loan Product: {product.name}',
        'form': form,
        'product': product,
        'is_create': False,
    }

    return render(request, 'products/loans/form.html', context)


# =============================================================================
# LOAN PRODUCT ACTIVATE VIEW
# =============================================================================

@login_required
def loan_product_activate(request, product_id):
    """
    Activate inactive loan product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to activate products.')
        raise PermissionDenied

    product = get_object_or_404(LoanProduct, id=product_id)

    if product.is_active:
        messages.warning(request, 'This product is already active.')
        return redirect('core:loan_product_detail', product_id=product.id)

    if request.method == 'POST':
        product.is_active = True
        product.save()

        messages.success(request, f'Loan product {product.name} activated successfully!')
        return redirect('core:loan_product_detail', product_id=product.id)

    context = {
        'page_title': f'Activate Loan Product: {product.name}',
        'product': product,
    }

    return render(request, 'products/loans/activate_confirm.html', context)


# =============================================================================
# LOAN PRODUCT DEACTIVATE VIEW
# =============================================================================

@login_required
def loan_product_deactivate(request, product_id):
    """
    Deactivate active loan product

    Permissions: Admin, Director
    """
    checker = PermissionChecker(request.user)

    if not checker.can_manage_products():
        messages.error(request, 'You do not have permission to deactivate products.')
        raise PermissionDenied

    product = get_object_or_404(LoanProduct, id=product_id)

    if not product.is_active:
        messages.warning(request, 'This product is already inactive.')
        return redirect('core:loan_product_detail', product_id=product.id)

    if request.method == 'POST':
        product.is_active = False
        product.save()

        messages.success(request, f'Loan product {product.name} deactivated successfully.')
        return redirect('core:loan_product_detail', product_id=product.id)

    context = {
        'page_title': f'Deactivate Loan Product: {product.name}',
        'product': product,
    }

    return render(request, 'products/loans/deactivate_confirm.html', context)


# =============================================================================
# LOAN PRODUCT DELETE VIEW
# =============================================================================

@login_required
def loan_product_delete(request, product_id):
    """
    Soft delete loan product (admin only)

    Permissions: Admin only

    Requirements:
    - No active loans
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin():
        messages.error(request, 'Only administrators can delete products.')
        raise PermissionDenied

    product = get_object_or_404(LoanProduct, id=product_id)

    # Check for active loans
    active_loans = product.loans.filter(status='active').count()
    if active_loans > 0:
        messages.error(request, f'Cannot delete product with {active_loans} active loan(s).')
        return redirect('core:loan_product_detail', product_id=product.id)

    if request.method == 'POST':
        product_name = product.name
        product.delete()  # Soft delete

        messages.success(request, f'Loan product {product_name} deleted successfully.')
        return redirect('core:loan_product_list')

    context = {
        'page_title': f'Delete Loan Product: {product.name}',
        'product': product,
    }

    return render(request, 'products/loans/delete_confirm.html', context)