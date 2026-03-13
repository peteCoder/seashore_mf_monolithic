"""
Dashboard View - CORRECTED VERSION
===================================

CRITICAL CHANGES:
- All references to account.account_type changed to account.savings_product.product_type
- Uses aggregation with proper filtering on savings_product__product_type
- No more direct account_type field access

Role-based dashboard with statistics and quick actions
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, Avg
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.models import (
    Client, Loan, SavingsAccount, Transaction,
    Branch, ClientGroup, User
)
from core.permissions import PermissionChecker


@login_required
def dashboard_view(request):
    """
    Main dashboard view - shows role-based statistics
    
    - Admin/Director: System-wide stats
    - Manager: Branch-level stats
    - Staff: Personal stats (assigned clients)
    """
    user = request.user
    checker = PermissionChecker(user)
    
    # Get date ranges
    today = timezone.now().date()
    this_month_start = today.replace(day=1)
    last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
    
    # =========================================================================
    # BASE QUERYSETS (FILTERED BY ROLE)
    # =========================================================================
    
    clients = checker.filter_clients(Client.objects.all())
    loans = checker.filter_loans(Loan.objects.all())
    savings_accounts = checker.filter_savings_accounts(SavingsAccount.objects.all())
    transactions = checker.filter_transactions(Transaction.objects.all())
    
    # =========================================================================
    # CLIENT STATISTICS
    # =========================================================================
    
    client_stats = {
        'total': clients.count(),
        'active': clients.filter(is_active=True).count(),
        'pending_approval': clients.filter(approval_status='pending').count(),
        'new_this_month': clients.filter(created_at__gte=this_month_start).count(),
    }
    
    # =========================================================================
    # LOAN STATISTICS
    # =========================================================================
    
    loan_aggregates = loans.aggregate(
        total_disbursed=Sum('amount_disbursed'),
        total_outstanding=Sum('outstanding_balance'),
        total_collected=Sum('amount_paid')
    )
    
    loan_stats = {
        'total': loans.count(),
        'active': loans.filter(status__in=['active', 'disbursed']).count(),
        'overdue': loans.filter(status='overdue').count(),
        'pending_approval': loans.filter(status='pending_approval').count(),
        'pending_fees': loans.filter(status='pending_fees').count(),
        'completed': loans.filter(status='completed').count(),
        'disbursed_this_month': loans.filter(
            disbursement_date__gte=this_month_start
        ).count(),
        'total_disbursed': loan_aggregates['total_disbursed'] or Decimal('0.00'),
        'total_outstanding': loan_aggregates['total_outstanding'] or Decimal('0.00'),
        'total_collected': loan_aggregates['total_collected'] or Decimal('0.00'),
    }
    
    # Portfolio at risk (overdue loans)
    if loan_stats['total_outstanding'] > 0:
        overdue_balance = loans.filter(status='overdue').aggregate(
            total=Sum('outstanding_balance')
        )['total'] or Decimal('0.00')
        
        loan_stats['portfolio_at_risk_pct'] = float(
            (overdue_balance / loan_stats['total_outstanding']) * 100
        )
    else:
        loan_stats['portfolio_at_risk_pct'] = 0.0
    
    # =========================================================================
    # SAVINGS STATISTICS - CORRECTED (uses savings_product__product_type)
    # =========================================================================
    
    savings_aggregates = savings_accounts.aggregate(
        total_balance=Sum('balance'),
        total_interest=Sum('interest_earned')
    )
    
    savings_stats = {
        'total_accounts': savings_accounts.count(),
        'active_accounts': savings_accounts.filter(status='active').count(),
        'total_balance': savings_aggregates['total_balance'] or Decimal('0.00'),
        'total_interest_paid': savings_aggregates['total_interest'] or Decimal('0.00'),
        # CORRECTED: Filter by savings_product__product_type instead of account_type
        'by_type': {
            'regular': savings_accounts.filter(
                savings_product__product_type='regular'
            ).count(),
            'fixed': savings_accounts.filter(
                savings_product__product_type='fixed'
            ).count(),
            'target': savings_accounts.filter(
                savings_product__product_type='target'
            ).count(),
            'children': savings_accounts.filter(
                savings_product__product_type='children'
            ).count(),
        }
    }
    
    # =========================================================================
    # TRANSACTION STATISTICS
    # =========================================================================
    
    transactions_today = transactions.filter(transaction_date__date=today)
    transactions_this_month = transactions.filter(transaction_date__gte=this_month_start)
    
    today_aggregates = transactions_today.aggregate(
        deposits=Sum('amount', filter=Q(transaction_type='deposit')),
        withdrawals=Sum('amount', filter=Q(transaction_type='withdrawal')),
        loan_repayments=Sum('amount', filter=Q(transaction_type='loan_repayment')),
    )
    
    month_aggregates = transactions_this_month.aggregate(
        total_income=Sum('amount', filter=Q(is_income=True)),
        deposits=Sum('amount', filter=Q(transaction_type='deposit')),
        withdrawals=Sum('amount', filter=Q(transaction_type='withdrawal')),
        loan_disbursements=Sum('amount', filter=Q(transaction_type='loan_disbursement')),
        loan_repayments=Sum('amount', filter=Q(transaction_type='loan_repayment')),
    )
    
    transaction_stats = {
        'today_count': transactions_today.count(),
        'today_deposits': today_aggregates['deposits'] or Decimal('0.00'),
        'today_withdrawals': today_aggregates['withdrawals'] or Decimal('0.00'),
        'today_repayments': today_aggregates['loan_repayments'] or Decimal('0.00'),
        'month_count': transactions_this_month.count(),
        'month_income': month_aggregates['total_income'] or Decimal('0.00'),
        'month_deposits': month_aggregates['deposits'] or Decimal('0.00'),
        'month_withdrawals': month_aggregates['withdrawals'] or Decimal('0.00'),
        'month_disbursements': month_aggregates['loan_disbursements'] or Decimal('0.00'),
        'month_repayments': month_aggregates['loan_repayments'] or Decimal('0.00'),
    }
    
    # =========================================================================
    # BRANCH STATISTICS (FOR ADMIN/DIRECTOR)
    # =========================================================================
    
    branch_stats = None
    if checker.can_view_all_branches():
        branches = Branch.objects.filter(is_active=True)
        branch_stats = []
        
        for branch in branches[:5]:  # Top 5 branches
            branch_loans = Loan.objects.filter(branch=branch, status__in=['active', 'disbursed'])
            branch_clients = Client.objects.filter(branch=branch, is_active=True)
            
            branch_stats.append({
                'branch': branch,
                'client_count': branch_clients.count(),
                'loan_count': branch_loans.count(),
                'portfolio': branch_loans.aggregate(
                    total=Sum('outstanding_balance')
                )['total'] or Decimal('0.00')
            })
    
    # =========================================================================
    # RECENT ACTIVITIES
    # =========================================================================
    
    recent_clients = clients.order_by('-created_at')[:5]
    recent_loans = loans.order_by('-created_at')[:5]
    recent_transactions = transactions.order_by('-transaction_date')[:10]
    
    # Pending approvals (for managers and above)
    pending_items = {}
    if checker.can_approve_clients():
        pending_items['clients'] = clients.filter(approval_status='pending').count()
    
    if checker.can_approve_loans():
        pending_items['loans'] = loans.filter(status='pending_approval').count()
    
    if checker.can_approve_transactions():
        pending_items['transactions'] = transactions.filter(status='pending').count()
    
    # =========================================================================
    # ALERTS & NOTIFICATIONS
    # =========================================================================
    
    alerts = []
    
    # Overdue loans alert
    if loan_stats['overdue'] > 0:
        alerts.append({
            'type': 'warning',
            'icon': '⚠️',
            'message': f"{loan_stats['overdue']} overdue loan(s) requiring attention",
            'action_url': reverse('core:loan_list') + '?status=overdue',
            'action_text': 'View Overdue Loans'
        })

    # Pending approvals alert
    if pending_items.get('clients', 0) > 0:
        alerts.append({
            'type': 'info',
            'icon': '👥',
            'message': f"{pending_items['clients']} client(s) pending approval",
            'action_url': reverse('core:client_list') + '?approval_status=pending',
            'action_text': 'Review Clients'
        })

    if pending_items.get('loans', 0) > 0:
        alerts.append({
            'type': 'info',
            'icon': '💰',
            'message': f"{pending_items['loans']} loan(s) pending approval",
            'action_url': reverse('core:loan_list') + '?status=pending_approval',
            'action_text': 'Review Loans'
        })

    # Low portfolio performance alert
    if loan_stats['portfolio_at_risk_pct'] > 10:
        alerts.append({
            'type': 'error',
            'icon': '📉',
            'message': f"Portfolio at risk: {loan_stats['portfolio_at_risk_pct']:.1f}%",
            'action_url': reverse('core:report_par_aging'),
            'action_text': 'View PAR Report'
        })
    
    # =========================================================================
    # CONTEXT
    # =========================================================================
    
    context = {
        'page_title': 'Dashboard',
        'user_role': user.get_user_role_display(),
        'can_view_all_branches': checker.can_view_all_branches(),
        
        # Statistics
        'client_stats': client_stats,
        'loan_stats': loan_stats,
        'savings_stats': savings_stats,
        'transaction_stats': transaction_stats,
        'branch_stats': branch_stats,
        
        # Recent activities
        'recent_clients': recent_clients,
        'recent_loans': recent_loans,
        'recent_transactions': recent_transactions,
        
        # Pending items
        'pending_items': pending_items,
        
        # Alerts
        'alerts': alerts,
        
        # Quick stats for cards
        'quick_stats': [
            {
                'title': 'Total Clients',
                'value': client_stats['total'],
                'change': f"+{client_stats['new_this_month']} this month",
                'icon': '👥',
                'color': 'blue',
                'url': reverse('core:client_list'),
            },
            {
                'title': 'Active Loans',
                'value': loan_stats['active'],
                'change': f"₦{loan_stats['total_outstanding']:,.0f} outstanding",
                'icon': '💰',
                'color': 'green',
                'url': reverse('core:loan_list'),
            },
            {
                'title': 'Savings Balance',
                'value': f"₦{savings_stats['total_balance']:,.0f}",
                'change': f"{savings_stats['active_accounts']} accounts",
                'icon': '🏦',
                'color': 'purple',
                'url': reverse('core:savings_account_list'),
            },
            {
                'title': "Today's Transactions",
                'value': transaction_stats['today_count'],
                'change': f"₦{transaction_stats['today_deposits']:,.0f} deposits",
                'icon': '📊',
                'color': 'yellow',
                'url': reverse('core:savings_transaction_list'),
            },
        ]
    }
    
    return render(request, 'dashboard/dashboard.html', context)

