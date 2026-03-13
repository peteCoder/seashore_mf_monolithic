"""
Collateral Views
================
CRUD, verification, and release workflow for loan collaterals.
"""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Collateral, Loan
from core.forms.collateral_forms import CollateralForm, CollateralVerifyForm, CollateralReleaseForm
from core.permissions import PermissionChecker


# =============================================================================
# LIST COLLATERALS FOR A LOAN
# =============================================================================

@login_required
def loan_collaterals(request, loan_id):
    loan = get_object_or_404(
        Loan.objects.select_related('client', 'branch', 'loan_product'),
        id=loan_id,
    )
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    collaterals = loan.collaterals.select_related('verified_by').order_by('created_at')

    summary = {
        'total': collaterals.count(),
        'total_value': sum(c.value for c in collaterals),
        'pending': collaterals.filter(status='pending').count(),
        'verified': collaterals.filter(status='verified').count(),
        'released': collaterals.filter(status='released').count(),
    }

    return render(request, 'collaterals/list.html', {
        'page_title': f'Collaterals — {loan.loan_number}',
        'loan': loan,
        'collaterals': collaterals,
        'summary': summary,
        'checker': checker,
    })


# =============================================================================
# ADD COLLATERAL
# =============================================================================

@login_required
def loan_add_collateral(request, loan_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if request.method == 'POST':
        form = CollateralForm(request.POST)
        if form.is_valid():
            collateral = form.save(commit=False)
            collateral.loan = loan
            collateral.status = 'pending'
            collateral.save()
            messages.success(request, f'Collateral "{collateral.get_collateral_type_display()}" added successfully.')
            return redirect('core:loan_collaterals', loan_id=loan.id)
    else:
        form = CollateralForm()

    return render(request, 'collaterals/form.html', {
        'page_title': f'Add Collateral — {loan.loan_number}',
        'loan': loan,
        'form': form,
        'is_edit': False,
    })


# =============================================================================
# EDIT COLLATERAL
# =============================================================================

@login_required
def loan_edit_collateral(request, loan_id, collateral_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    collateral = get_object_or_404(Collateral, id=collateral_id, loan=loan)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if collateral.status not in ('pending',):
        messages.error(request, 'Only pending collaterals can be edited.')
        return redirect('core:loan_collaterals', loan_id=loan.id)

    if request.method == 'POST':
        form = CollateralForm(request.POST, instance=collateral)
        if form.is_valid():
            form.save()
            messages.success(request, 'Collateral updated successfully.')
            return redirect('core:loan_collaterals', loan_id=loan.id)
    else:
        form = CollateralForm(instance=collateral)

    return render(request, 'collaterals/form.html', {
        'page_title': f'Edit Collateral — {loan.loan_number}',
        'loan': loan,
        'collateral': collateral,
        'form': form,
        'is_edit': True,
    })


# =============================================================================
# VERIFY COLLATERAL
# =============================================================================

@login_required
def loan_verify_collateral(request, loan_id, collateral_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    collateral = get_object_or_404(Collateral, id=collateral_id, loan=loan)
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can verify collaterals.')

    if collateral.status != 'pending':
        messages.error(request, 'Only pending collaterals can be verified.')
        return redirect('core:loan_collaterals', loan_id=loan.id)

    if request.method == 'POST':
        form = CollateralVerifyForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data.get('notes', '')

            if decision == 'verify':
                collateral.status = 'verified'
                collateral.verified_by = request.user
                collateral.verified_at = timezone.now()
                collateral.notes = (
                    (collateral.notes + '\n\n' + notes).strip() if collateral.notes and notes
                    else notes or collateral.notes
                )
                collateral.save()
                messages.success(request, 'Collateral verified successfully.')
            else:
                collateral.status = 'rejected'
                collateral.notes = (
                    (collateral.notes + '\n\nRejection reason: ' + notes).strip()
                    if notes else collateral.notes
                )
                collateral.save()
                messages.warning(request, 'Collateral rejected.')

            return redirect('core:loan_collaterals', loan_id=loan.id)
    else:
        form = CollateralVerifyForm()

    return render(request, 'collaterals/verify.html', {
        'page_title': f'Verify Collateral — {loan.loan_number}',
        'loan': loan,
        'collateral': collateral,
        'form': form,
    })


# =============================================================================
# RELEASE COLLATERAL
# =============================================================================

@login_required
def loan_release_collateral(request, loan_id, collateral_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    collateral = get_object_or_404(Collateral, id=collateral_id, loan=loan)
    checker = PermissionChecker(request.user)

    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied('Only managers and above can release collaterals.')

    if collateral.status != 'verified':
        messages.error(request, 'Only verified collaterals can be released.')
        return redirect('core:loan_collaterals', loan_id=loan.id)

    if request.method == 'POST':
        form = CollateralReleaseForm(request.POST)
        if form.is_valid():
            notes = form.cleaned_data.get('notes', '')
            collateral.status = 'released'
            if notes:
                collateral.notes = (
                    (collateral.notes + '\n\nRelease notes: ' + notes).strip()
                    if collateral.notes else notes
                )
            collateral.save()
            messages.success(request, 'Collateral released to owner.')
            return redirect('core:loan_collaterals', loan_id=loan.id)
    else:
        form = CollateralReleaseForm()

    return render(request, 'collaterals/release.html', {
        'page_title': f'Release Collateral — {loan.loan_number}',
        'loan': loan,
        'collateral': collateral,
        'form': form,
    })


# =============================================================================
# DELETE COLLATERAL
# =============================================================================

@login_required
@require_POST
def loan_delete_collateral(request, loan_id, collateral_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    collateral = get_object_or_404(Collateral, id=collateral_id, loan=loan)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if collateral.status not in ('pending', 'rejected'):
        messages.error(request, 'Only pending or rejected collaterals can be deleted.')
        return redirect('core:loan_collaterals', loan_id=loan.id)

    collateral.delete()
    messages.success(request, 'Collateral removed.')
    return redirect('core:loan_collaterals', loan_id=loan.id)
