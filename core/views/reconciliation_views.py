"""
Bank / Cash Reconciliation Views
=================================
No journal entries are posted here — this is purely a matching/tracking
exercise. Correcting journals must be posted separately via the manual
journal entry view.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal

from core.models import BankReconciliation, BankStatementLine, JournalEntryLine, Branch
from core.forms.reconciliation_forms import (
    BankReconciliationCreateForm, BankStatementLineForm, MatchingForm
)
from core.permissions import PermissionChecker


@login_required
def reconciliation_list(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    qs = BankReconciliation.objects.select_related(
        'gl_account', 'branch', 'created_by', 'completed_by'
    )
    if checker.is_manager():
        qs = qs.filter(branch=request.user.branch)

    status_filter    = request.GET.get('status', '')
    branch_filter    = request.GET.get('branch', '')

    if status_filter:
        qs = qs.filter(status=status_filter)
    if branch_filter and checker.is_admin_or_director():
        qs = qs.filter(branch_id=branch_filter)

    qs = qs.order_by('-period_end', '-created_at')
    paginator = Paginator(qs, 25)
    page_obj  = paginator.get_page(request.GET.get('page'))

    branches = Branch.objects.filter(is_active=True) if checker.is_admin_or_director() else None

    return render(request, 'reconciliation/list.html', {
        'page_title':    'Bank Reconciliations',
        'reconciliations': page_obj,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
        'branches':      branches,
        'checker':       checker,
    })


@login_required
def reconciliation_create(request):
    checker = PermissionChecker(request.user)
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    if request.method == 'POST':
        form = BankReconciliationCreateForm(request.POST, user=request.user)
        if form.is_valid():
            recon = form.save(commit=False)
            recon.created_by = request.user
            recon.status     = 'draft'
            recon.save()
            messages.success(request, f'Reconciliation {recon.recon_ref} created.')
            return redirect('core:reconciliation_detail', recon_id=recon.id)
    else:
        form = BankReconciliationCreateForm(user=request.user)

    return render(request, 'reconciliation/create.html', {
        'page_title': 'New Bank Reconciliation',
        'form':       form,
    })


@login_required
def reconciliation_detail(request, recon_id):
    recon = get_object_or_404(
        BankReconciliation.objects.select_related(
            'gl_account', 'branch', 'created_by', 'completed_by'
        ),
        id=recon_id,
    )
    checker = PermissionChecker(request.user)
    if checker.is_manager() and recon.branch != request.user.branch:
        raise PermissionDenied
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    # IDs of GL lines already matched to bank lines in this reconciliation
    matched_gl_ids = BankStatementLine.objects.filter(
        reconciliation=recon,
        matched_gl_line__isnull=False,
    ).values_list('matched_gl_line_id', flat=True)

    # Unmatched GL lines for this account / period
    gl_lines = JournalEntryLine.objects.filter(
        account=recon.gl_account,
        journal_entry__status='posted',
        journal_entry__transaction_date__gte=recon.period_start,
        journal_entry__transaction_date__lte=recon.period_end,
    ).exclude(
        id__in=matched_gl_ids,
    ).select_related(
        'journal_entry', 'journal_entry__branch', 'client',
    ).order_by('journal_entry__transaction_date', 'id')

    bank_lines = recon.lines.select_related(
        'matched_gl_line', 'matched_gl_line__journal_entry',
    ).order_by('line_date', 'id')

    # Stats
    gl_total_debits  = gl_lines.aggregate(t=Sum('debit_amount'))['t']  or Decimal('0.00')
    gl_total_credits = gl_lines.aggregate(t=Sum('credit_amount'))['t'] or Decimal('0.00')
    bank_debits      = bank_lines.aggregate(t=Sum('debit_amount'))['t']  or Decimal('0.00')
    bank_credits     = bank_lines.aggregate(t=Sum('credit_amount'))['t'] or Decimal('0.00')
    matched_count    = bank_lines.filter(status='matched').count()
    unmatched_count  = bank_lines.filter(status='unmatched').count()

    return render(request, 'reconciliation/detail.html', {
        'page_title':      f'Reconciliation — {recon.recon_ref}',
        'recon':           recon,
        'gl_lines':        gl_lines,
        'bank_lines':      bank_lines,
        'gl_total_debits': gl_total_debits,
        'gl_total_credits':gl_total_credits,
        'bank_debits':     bank_debits,
        'bank_credits':    bank_credits,
        'matched_count':   matched_count,
        'unmatched_count': unmatched_count,
        'gl_closing':      recon.get_gl_closing_balance(),
        'difference':      recon.get_difference(),
        'add_line_form':   BankStatementLineForm(),
        'match_form':      MatchingForm(),
        'checker':         checker,
    })


@login_required
def reconciliation_add_line(request, recon_id):
    """POST only — add a BankStatementLine to a reconciliation."""
    recon = get_object_or_404(BankReconciliation, id=recon_id)
    checker = PermissionChecker(request.user)
    if checker.is_manager() and recon.branch != request.user.branch:
        raise PermissionDenied
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied
    if recon.status == 'completed':
        messages.error(request, 'Cannot add lines to a completed reconciliation.')
        return redirect('core:reconciliation_detail', recon_id=recon.id)

    if request.method == 'POST':
        form = BankStatementLineForm(request.POST)
        if form.is_valid():
            line = form.save(commit=False)
            line.reconciliation = recon
            line.status         = 'unmatched'
            line.save()
            if recon.status == 'draft':
                recon.status = 'in_progress'
                recon.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Bank statement line added.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

    return redirect('core:reconciliation_detail', recon_id=recon.id)


@login_required
def reconciliation_match(request, recon_id):
    """POST only — match or unmatch a bank line to a GL line."""
    recon = get_object_or_404(BankReconciliation, id=recon_id)
    checker = PermissionChecker(request.user)
    if checker.is_manager() and recon.branch != request.user.branch:
        raise PermissionDenied
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied
    if recon.status == 'completed':
        messages.error(request, 'Cannot modify a completed reconciliation.')
        return redirect('core:reconciliation_detail', recon_id=recon.id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'match':
            form = MatchingForm(request.POST)
            if form.is_valid():
                bank_line_id = form.cleaned_data['bank_line_id']
                gl_line_id   = form.cleaned_data['gl_line_id']
                try:
                    with db_transaction.atomic():
                        bank_line = BankStatementLine.objects.select_for_update().get(
                            id=bank_line_id, reconciliation=recon
                        )
                        gl_line = JournalEntryLine.objects.get(
                            id=gl_line_id,
                            account=recon.gl_account,
                            journal_entry__status='posted',
                        )
                        # Prevent double-matching the same GL line
                        already_matched = BankStatementLine.objects.filter(
                            matched_gl_line=gl_line
                        ).exclude(id=bank_line.id).exists()
                        if already_matched:
                            messages.error(
                                request,
                                'That GL line is already matched to another bank statement line.'
                            )
                        else:
                            bank_line.matched_gl_line = gl_line
                            bank_line.status          = 'matched'
                            bank_line.save(update_fields=['matched_gl_line', 'status', 'updated_at'])
                            messages.success(request, 'Lines matched successfully.')
                except BankStatementLine.DoesNotExist:
                    messages.error(request, 'Bank statement line not found.')
                except JournalEntryLine.DoesNotExist:
                    messages.error(request, 'GL journal line not found.')
            else:
                messages.error(request, 'Invalid match data.')

        elif action == 'unmatch':
            bank_line_id = request.POST.get('bank_line_id')
            try:
                with db_transaction.atomic():
                    bank_line = BankStatementLine.objects.select_for_update().get(
                        id=bank_line_id, reconciliation=recon
                    )
                    bank_line.matched_gl_line = None
                    bank_line.status          = 'unmatched'
                    bank_line.save(update_fields=['matched_gl_line', 'status', 'updated_at'])
                    messages.success(request, 'Match removed.')
            except BankStatementLine.DoesNotExist:
                messages.error(request, 'Bank line not found.')

    return redirect('core:reconciliation_detail', recon_id=recon.id)


@login_required
def reconciliation_complete(request, recon_id):
    """POST only — mark a reconciliation as completed."""
    recon = get_object_or_404(BankReconciliation, id=recon_id)
    checker = PermissionChecker(request.user)
    if checker.is_manager() and recon.branch != request.user.branch:
        raise PermissionDenied
    if not (checker.is_manager() or checker.is_admin_or_director()):
        raise PermissionDenied

    if request.method == 'POST':
        if recon.status == 'completed':
            messages.info(request, 'This reconciliation is already completed.')
            return redirect('core:reconciliation_detail', recon_id=recon.id)

        if not recon.is_complete_eligible():
            messages.error(
                request,
                'Cannot complete: there are still unmatched bank statement lines. '
                'Match or mark them as disputed first.'
            )
            return redirect('core:reconciliation_detail', recon_id=recon.id)

        with db_transaction.atomic():
            recon.status       = 'completed'
            recon.completed_by = request.user
            recon.completed_at = timezone.now()
            recon.save(update_fields=['status', 'completed_by', 'completed_at', 'updated_at'])

        messages.success(request, f'Reconciliation {recon.recon_ref} marked as completed.')

    return redirect('core:reconciliation_detail', recon_id=recon.id)
