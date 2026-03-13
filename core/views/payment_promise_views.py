"""
Payment Promise Views
=====================
Record and track promise-to-pay agreements for loans.
"""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import PaymentPromise, Loan
from core.forms.promise_forms import PaymentPromiseForm, PaymentPromiseStatusForm
from core.permissions import PermissionChecker


# =============================================================================
# PAYMENT PROMISE LIST
# =============================================================================

@login_required
def payment_promise_list(request):
    checker = PermissionChecker(request.user)

    qs = PaymentPromise.objects.select_related(
        'loan', 'loan__client', 'loan__branch', 'recorded_by'
    )

    if checker.is_staff():
        qs = qs.filter(loan__client__assigned_staff=request.user)
    elif checker.is_manager():
        qs = qs.filter(loan__branch=request.user.branch)

    filter_by = request.GET.get('filter', 'pending')
    today = timezone.now().date()

    if filter_by == 'pending':
        qs = qs.filter(status='pending')
    elif filter_by == 'overdue':
        qs = qs.filter(status='pending', promise_date__lt=today)
    elif filter_by in ('kept', 'broken', 'partial'):
        qs = qs.filter(status=filter_by)

    qs = qs.order_by('promise_date')

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Summary
    base = PaymentPromise.objects.all()
    if checker.is_staff():
        base = base.filter(loan__client__assigned_staff=request.user)
    elif checker.is_manager():
        base = base.filter(loan__branch=request.user.branch)

    summary = {
        'total_pending': base.filter(status='pending').count(),
        'overdue': base.filter(status='pending', promise_date__lt=today).count(),
        'kept': base.filter(status='kept').count(),
        'broken': base.filter(status='broken').count(),
    }

    return render(request, 'payment_promises/list.html', {
        'page_title': 'Payment Promises',
        'promises': page_obj,
        'filter_by': filter_by,
        'summary': summary,
        'checker': checker,
        'today': today,
    })


# =============================================================================
# ADD PAYMENT PROMISE (nested under loan)
# =============================================================================

@login_required
def loan_add_promise(request, loan_id):
    loan = get_object_or_404(Loan.objects.select_related('client', 'branch'), id=loan_id)
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(loan):
        raise PermissionDenied

    if request.method == 'POST':
        form = PaymentPromiseForm(request.POST)
        if form.is_valid():
            promise = form.save(commit=False)
            promise.loan = loan
            promise.recorded_by = request.user
            promise.status = 'pending'
            promise.save()
            messages.success(
                request,
                f'Payment promise of ₦{promise.promised_amount:,.2f} recorded for '
                f'{promise.promise_date.strftime("%d %b %Y")}.'
            )
            return redirect('core:loan_detail', loan_id=loan.id)
    else:
        form = PaymentPromiseForm()

    return render(request, 'payment_promises/form.html', {
        'page_title': f'Record Payment Promise — {loan.loan_number}',
        'loan': loan,
        'form': form,
        'is_edit': False,
    })


# =============================================================================
# EDIT PAYMENT PROMISE
# =============================================================================

@login_required
def promise_update(request, promise_id):
    promise = get_object_or_404(
        PaymentPromise.objects.select_related('loan', 'loan__client', 'loan__branch', 'recorded_by'),
        id=promise_id,
    )
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(promise.loan):
        raise PermissionDenied

    if promise.status != 'pending':
        messages.error(request, 'Only pending promises can be edited.')
        return redirect('core:payment_promise_list')

    if request.method == 'POST':
        form = PaymentPromiseForm(request.POST, instance=promise)
        if form.is_valid():
            form.save()
            messages.success(request, 'Payment promise updated.')
            return redirect('core:payment_promise_list')
    else:
        form = PaymentPromiseForm(instance=promise)

    return render(request, 'payment_promises/form.html', {
        'page_title': 'Edit Payment Promise',
        'loan': promise.loan,
        'promise': promise,
        'form': form,
        'is_edit': True,
    })


# =============================================================================
# UPDATE PROMISE STATUS (pending → kept / broken / partial)
# =============================================================================

@login_required
def promise_update_status(request, promise_id):
    promise = get_object_or_404(
        PaymentPromise.objects.select_related('loan', 'loan__client', 'loan__branch'),
        id=promise_id,
    )
    checker = PermissionChecker(request.user)

    if not checker.can_view_loan(promise.loan):
        raise PermissionDenied

    if promise.status != 'pending':
        messages.error(request, 'This promise has already been resolved.')
        return redirect('core:payment_promise_list')

    if request.method == 'POST':
        form = PaymentPromiseStatusForm(request.POST)
        if form.is_valid():
            promise.status = form.cleaned_data['status']
            actual_paid = form.cleaned_data.get('actual_amount_paid')
            if actual_paid is not None:
                promise.actual_amount_paid = actual_paid
            extra_notes = form.cleaned_data.get('notes', '')
            if extra_notes:
                promise.notes = (
                    (promise.notes + '\n\n' + extra_notes).strip()
                    if promise.notes else extra_notes
                )
            promise.save()
            messages.success(
                request,
                f'Promise status updated to: {promise.get_status_display()}.'
            )
            return redirect('core:payment_promise_list')
    else:
        form = PaymentPromiseStatusForm()

    return render(request, 'payment_promises/update_status.html', {
        'page_title': 'Update Promise Status',
        'promise': promise,
        'loan': promise.loan,
        'form': form,
    })
