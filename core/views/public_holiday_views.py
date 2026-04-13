"""
Public Holiday Views
====================

Admin-only CRUD for managing public holidays that are excluded from
loan repayment schedules.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from core.models import PublicHoliday
from core.forms.holiday_forms import PublicHolidayForm
from core.permissions import PermissionChecker


# =============================================================================
# PUBLIC HOLIDAY LIST
# =============================================================================

@login_required
def public_holiday_list(request):
    """
    List all public holidays, optionally filtered by year.
    Accessible to: admin, director, hr (all can view; only admin can mutate).
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin_or_director():
        messages.error(request, 'You do not have permission to view public holidays.')
        raise PermissionDenied

    # Year filter
    current_year = timezone.now().year
    selected_year = request.GET.get('year', '')
    holidays = PublicHoliday.objects.all()
    if selected_year:
        try:
            selected_year = int(selected_year)
            holidays = holidays.filter(date__year=selected_year)
        except ValueError:
            selected_year = ''

    # Build a list of available years for the filter dropdown
    from django.db.models.functions import ExtractYear
    years = (
        PublicHoliday.objects.annotate(yr=ExtractYear('date'))
        .values_list('yr', flat=True)
        .distinct()
        .order_by('-yr')
    )

    context = {
        'page_title': 'Public Holidays',
        'holidays': holidays,
        'selected_year': selected_year,
        'years': list(years),
        'current_year': current_year,
        'checker': checker,
    }
    return render(request, 'holidays/list.html', context)


# =============================================================================
# PUBLIC HOLIDAY CREATE
# =============================================================================

@login_required
def public_holiday_create(request):
    """
    Add a new public holiday. Admin only.
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin():
        messages.error(request, 'Only administrators can add public holidays.')
        raise PermissionDenied

    if request.method == 'POST':
        form = PublicHolidayForm(request.POST)
        if form.is_valid():
            holiday = form.save(commit=False)
            holiday.created_by = request.user
            holiday.save()
            messages.success(request, f'"{holiday.name}" ({holiday.date}) added successfully.')
            return redirect('core:public_holiday_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PublicHolidayForm()

    context = {
        'page_title': 'Add Public Holiday',
        'form': form,
        'is_create': True,
    }
    return render(request, 'holidays/form.html', context)


# =============================================================================
# PUBLIC HOLIDAY EDIT
# =============================================================================

@login_required
def public_holiday_edit(request, holiday_id):
    """
    Edit an existing public holiday. Admin only.
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin():
        messages.error(request, 'Only administrators can edit public holidays.')
        raise PermissionDenied

    holiday = get_object_or_404(PublicHoliday, pk=holiday_id)

    if request.method == 'POST':
        form = PublicHolidayForm(request.POST, instance=holiday)
        if form.is_valid():
            form.save()
            messages.success(request, f'"{holiday.name}" updated successfully.')
            return redirect('core:public_holiday_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PublicHolidayForm(instance=holiday)

    context = {
        'page_title': f'Edit Holiday: {holiday.name}',
        'form': form,
        'holiday': holiday,
        'is_create': False,
    }
    return render(request, 'holidays/form.html', context)


# =============================================================================
# PUBLIC HOLIDAY DELETE
# =============================================================================

@login_required
def public_holiday_delete(request, holiday_id):
    """
    Delete a public holiday. Admin only.
    """
    checker = PermissionChecker(request.user)

    if not checker.is_admin():
        messages.error(request, 'Only administrators can delete public holidays.')
        raise PermissionDenied

    holiday = get_object_or_404(PublicHoliday, pk=holiday_id)

    if request.method == 'POST':
        name = holiday.name
        date = holiday.date
        holiday.delete()
        messages.success(request, f'"{name}" ({date}) deleted successfully.')
        return redirect('core:public_holiday_list')

    context = {
        'page_title': f'Delete Holiday: {holiday.name}',
        'holiday': holiday,
    }
    return render(request, 'holidays/delete_confirm.html', context)
