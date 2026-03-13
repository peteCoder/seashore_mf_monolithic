"""
Follow-up Task Views
====================
Assign, manage, and complete follow-up tasks linked to loans.
"""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import FollowUpTask, Loan
from core.forms.followup_forms import FollowUpTaskForm, FollowUpTaskCompleteForm
from core.permissions import PermissionChecker


# =============================================================================
# FOLLOW-UP TASK LIST
# =============================================================================

@login_required
def followup_list(request):
    """List follow-up tasks. Staff see their assigned tasks; managers see branch tasks."""
    checker = PermissionChecker(request.user)

    qs = FollowUpTask.objects.select_related(
        'loan', 'loan__client', 'loan__branch', 'assigned_to', 'created_by'
    )

    if checker.is_staff():
        qs = qs.filter(assigned_to=request.user)
    elif checker.is_manager():
        qs = qs.filter(loan__branch=request.user.branch)

    filter_by = request.GET.get('filter', 'pending')
    today = timezone.now().date()

    if filter_by == 'pending':
        qs = qs.filter(status='pending')
    elif filter_by == 'overdue':
        qs = qs.filter(status='pending', due_date__lt=today)
    elif filter_by == 'today':
        qs = qs.filter(status='pending', due_date=today)
    elif filter_by == 'completed':
        qs = qs.filter(status='completed')
    # 'all' — no filter

    priority = request.GET.get('priority', '')
    if priority:
        qs = qs.filter(priority=priority)

    qs = qs.order_by('due_date', '-priority')

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Summary counts (branch/staff scoped)
    base = FollowUpTask.objects.all()
    if checker.is_staff():
        base = base.filter(assigned_to=request.user)
    elif checker.is_manager():
        base = base.filter(loan__branch=request.user.branch)

    summary = {
        'total_pending': base.filter(status='pending').count(),
        'overdue': base.filter(status='pending', due_date__lt=today).count(),
        'due_today': base.filter(status='pending', due_date=today).count(),
    }

    return render(request, 'follow_ups/list.html', {
        'page_title': 'Follow-up Tasks',
        'tasks': page_obj,
        'filter_by': filter_by,
        'priority': priority,
        'summary': summary,
        'checker': checker,
        'today': today,
    })


# =============================================================================
# ADD FOLLOW-UP TASK (nested under loan)
# =============================================================================

@login_required
def loan_add_followup(request, loan_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if request.method == 'POST':
        form = FollowUpTaskForm(request.POST, branch=loan.branch)
        if form.is_valid():
            task = form.save(commit=False)
            task.loan = loan
            task.created_by = request.user
            task.status = 'pending'
            task.save()
            messages.success(
                request,
                f'Follow-up task assigned to {task.assigned_to.get_full_name()} due {task.due_date.strftime("%d %b %Y")}.'
            )
            return redirect('core:loan_detail', loan_id=loan.id)
    else:
        form = FollowUpTaskForm(
            branch=loan.branch,
            initial={'assigned_to': request.user},
        )

    return render(request, 'follow_ups/form.html', {
        'page_title': f'Add Follow-up — {loan.loan_number}',
        'loan': loan,
        'form': form,
        'is_edit': False,
    })


# =============================================================================
# EDIT FOLLOW-UP TASK
# =============================================================================

@login_required
def followup_update(request, task_id):
    task = get_object_or_404(
        FollowUpTask.objects.select_related('loan', 'loan__client', 'loan__branch', 'assigned_to', 'created_by'),
        id=task_id,
    )
    checker = PermissionChecker(request.user)

    if not (
        task.created_by == request.user
        or task.assigned_to == request.user
        or checker.is_manager()
        or checker.is_admin_or_director()
    ):
        raise PermissionDenied

    if task.status != 'pending':
        messages.error(request, 'Only pending tasks can be edited.')
        return redirect('core:followup_list')

    if request.method == 'POST':
        form = FollowUpTaskForm(request.POST, instance=task, branch=task.loan.branch)
        if form.is_valid():
            form.save()
            messages.success(request, 'Follow-up task updated.')
            return redirect('core:followup_list')
    else:
        form = FollowUpTaskForm(instance=task, branch=task.loan.branch)

    return render(request, 'follow_ups/form.html', {
        'page_title': 'Edit Follow-up Task',
        'loan': task.loan,
        'task': task,
        'form': form,
        'is_edit': True,
    })


# =============================================================================
# COMPLETE FOLLOW-UP TASK
# =============================================================================

@login_required
def followup_complete(request, task_id):
    task = get_object_or_404(
        FollowUpTask.objects.select_related('loan', 'loan__client', 'loan__branch', 'assigned_to'),
        id=task_id,
    )
    checker = PermissionChecker(request.user)

    if not (
        task.assigned_to == request.user
        or checker.is_manager()
        or checker.is_admin_or_director()
    ):
        raise PermissionDenied

    if task.status != 'pending':
        messages.error(request, 'Only pending tasks can be completed.')
        return redirect('core:followup_list')

    if request.method == 'POST':
        form = FollowUpTaskCompleteForm(request.POST)
        if form.is_valid():
            task.status = 'completed'
            task.outcome = form.cleaned_data['outcome']
            task.completed_at = timezone.now()
            task.save(update_fields=['status', 'outcome', 'completed_at', 'updated_at'])
            messages.success(request, 'Follow-up task marked as completed.')
            return redirect('core:followup_list')
    else:
        form = FollowUpTaskCompleteForm()

    return render(request, 'follow_ups/complete.html', {
        'page_title': f'Complete Follow-up — {task.loan.loan_number}',
        'task': task,
        'form': form,
    })


# =============================================================================
# CANCEL FOLLOW-UP TASK
# =============================================================================

@login_required
@require_POST
def followup_cancel(request, task_id):
    task = get_object_or_404(FollowUpTask.objects.select_related('created_by'), id=task_id)
    checker = PermissionChecker(request.user)

    if not (
        task.created_by == request.user
        or checker.is_manager()
        or checker.is_admin_or_director()
    ):
        raise PermissionDenied

    if task.status != 'pending':
        messages.error(request, 'Only pending tasks can be cancelled.')
        return redirect('core:followup_list')

    task.status = 'cancelled'
    task.save(update_fields=['status', 'updated_at'])
    messages.success(request, 'Follow-up task cancelled.')
    return redirect('core:followup_list')
