"""
Custom QuerySets and Managers
==============================

Provides reusable query methods for common filtering operations
"""

from django.db import models
from django.utils import timezone
from django.db.models import Q, Sum, Count, Avg, Max, Min, F
from decimal import Decimal


class BranchFilteredQuerySet(models.QuerySet):
    """QuerySet with branch filtering support"""
    
    def for_branch(self, branch):
        """Filter by branch"""
        return self.filter(branch=branch)
    
    def for_branches(self, branches):
        """Filter by multiple branches"""
        return self.filter(branch__in=branches)


class ActiveInactiveQuerySet(models.QuerySet):
    """QuerySet with active/inactive filtering"""
    
    def active(self):
        """Get only active records"""
        return self.filter(is_active=True)
    
    def inactive(self):
        """Get only inactive records"""
        return self.filter(is_active=False)


class ApprovalQuerySet(models.QuerySet):
    """QuerySet with approval status filtering"""
    
    def pending_approval(self):
        """Get records pending approval"""
        return self.filter(approval_status='pending')
    
    def approved(self):
        """Get approved records"""
        return self.filter(approval_status='approved')
    
    def rejected(self):
        """Get rejected records"""
        return self.filter(approval_status='rejected')
    
    def draft(self):
        """Get draft records"""
        return self.filter(approval_status='draft')


class ClientQuerySet(BranchFilteredQuerySet, ActiveInactiveQuerySet, ApprovalQuerySet):
    """Custom QuerySet for Client model"""
    
    def assigned_to_staff(self, staff):
        """Clients assigned to specific staff"""
        return self.filter(assigned_staff=staff)
    
    def in_group(self, group):
        """Clients in specific group"""
        return self.filter(group=group)
    
    def without_group(self):
        """Clients not in any group"""
        return self.filter(group__isnull=True)
    
    def fully_activated(self):
        """Clients who are active and approved"""
        return self.filter(is_active=True, is_approved=True)
    
    def with_registration_fee_paid(self):
        """Clients who paid registration fee"""
        return self.filter(registration_fee_paid=True)
    
    def with_loans(self):
        """Clients with at least one loan"""
        return self.filter(loans__isnull=False).distinct()
    
    def with_active_loans(self):
        """Clients with active loans"""
        return self.filter(
            loans__status__in=['active', 'overdue', 'disbursed']
        ).distinct()
    
    def with_savings_accounts(self):
        """Clients with savings accounts"""
        return self.filter(savings_accounts__isnull=False).distinct()
    
    def get_statistics(self):
        """Get client statistics"""
        return {
            'total': self.count(),
            'active': self.active().count(),
            'approved': self.approved().count(),
            'pending_approval': self.pending_approval().count(),
            'with_loans': self.with_active_loans().count(),
            'with_savings': self.with_savings_accounts().count(),
        }


class ClientManager(models.Manager):
    """Custom Manager for Client model"""
    
    def get_queryset(self):
        return ClientQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def assigned_to_staff(self, staff):
        return self.get_queryset().assigned_to_staff(staff)
    
    def in_group(self, group):
        return self.get_queryset().in_group(group)
    
    def fully_activated(self):
        return self.get_queryset().fully_activated()
    
    def for_branch(self, branch):
        return self.get_queryset().for_branch(branch)
    
    def pending_approval(self):
        return self.get_queryset().pending_approval()
    
    def bulk_assign_to_staff(self, client_ids, staff, assigned_by=None):
        """Efficiently assign multiple clients to staff"""
        clients = self.filter(id__in=client_ids, is_active=True)
        count = clients.update(
            assigned_staff=staff,
            updated_at=timezone.now()
        )
        
        # Create notification
        if count > 0 and assigned_by:
            from core.models import Notification
            Notification.objects.create(
                user=staff,
                notification_type='clients_assigned',
                title=f'{count} clients assigned to you',
                message=f'{assigned_by.get_full_name()} assigned {count} clients to you'
            )
        
        return count


class LoanQuerySet(BranchFilteredQuerySet):
    """Custom QuerySet for Loan model"""
    
    def active(self):
        """Active loans (disbursed and being repaid)"""
        return self.filter(status__in=['active', 'disbursed'])
    
    def overdue(self):
        """Overdue loans"""
        return self.filter(
            status='overdue',
            next_repayment_date__lt=timezone.now().date()
        )
    
    def pending_fees(self):
        """Loans pending fee payment"""
        return self.filter(status='pending_fees', fees_paid=False)
    
    def pending_approval(self):
        """Loans pending approval"""
        return self.filter(status='pending_approval', fees_paid=True)
    
    def approved_not_disbursed(self):
        """Approved but not yet disbursed"""
        return self.filter(status='approved', disbursement_date__isnull=True)
    
    def completed(self):
        """Completed loans"""
        return self.filter(status='completed')
    
    def by_type(self, loan_type):
        """Filter by loan type"""
        return self.filter(loan_product__loan_type=loan_type)
    
    def for_client(self, client):
        """Loans for specific client"""
        return self.filter(client=client)
    
    def for_staff(self, staff):
        """Loans managed by specific staff (via client)"""
        return self.filter(client__assigned_staff=staff)
    
    def for_group(self, group):
        """Loans for clients in a group"""
        return self.filter(client__group=group)
    
    def disbursed_between(self, start_date, end_date):
        """Loans disbursed in date range"""
        return self.filter(
            disbursement_date__gte=start_date,
            disbursement_date__lte=end_date
        )
    
    def due_this_week(self):
        """Loans with payments due this week"""
        today = timezone.now().date()
        week_end = today + timezone.timedelta(days=7)
        return self.filter(
            next_repayment_date__gte=today,
            next_repayment_date__lte=week_end,
            status__in=['active', 'overdue']
        )
    
    def get_portfolio_summary(self):
        """Get loan portfolio summary"""
        aggregate_data = self.aggregate(
            total_loans=Count('id'),
            total_principal=Sum('principal_amount'),
            total_disbursed=Sum('amount_disbursed'),
            total_outstanding=Sum('outstanding_balance'),
            total_collected=Sum('amount_paid'),
            avg_loan_size=Avg('principal_amount'),
        )
        
        # Calculate additional metrics
        active_count = self.active().count()
        overdue_count = self.overdue().count()
        completed_count = self.completed().count()
        
        return {
            **aggregate_data,
            'active_loans': active_count,
            'overdue_loans': overdue_count,
            'completed_loans': completed_count,
            'total_disbursed': aggregate_data['total_disbursed'] or Decimal('0.00'),
            'total_outstanding': aggregate_data['total_outstanding'] or Decimal('0.00'),
            'total_collected': aggregate_data['total_collected'] or Decimal('0.00'),
        }


class LoanManager(models.Manager):
    """Custom Manager for Loan model"""
    
    def get_queryset(self):
        return LoanQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def overdue(self):
        return self.get_queryset().overdue()
    
    def pending_approval(self):
        return self.get_queryset().pending_approval()
    
    def for_branch(self, branch):
        return self.get_queryset().for_branch(branch)
    
    def for_staff(self, staff):
        return self.get_queryset().for_staff(staff)
    
    def due_this_week(self):
        return self.get_queryset().due_this_week()


class SavingsAccountQuerySet(BranchFilteredQuerySet):
    """Custom QuerySet for SavingsAccount model"""
    
    def active(self):
        """Active savings accounts"""
        return self.filter(status='active')
    
    def pending_approval(self):
        """Accounts pending approval"""
        return self.filter(status='pending')
    
    def by_type(self, account_type):
        """Filter by account type"""
        return self.filter(account_type=account_type)
    
    def for_client(self, client):
        """Accounts for specific client"""
        return self.filter(client=client)
    
    def auto_created(self):
        """Auto-created accounts"""
        return self.filter(is_auto_created=True)
    
    def manually_created(self):
        """Manually created accounts"""
        return self.filter(is_auto_created=False)
    
    def with_balance_above(self, amount):
        """Accounts with balance above specified amount"""
        return self.filter(balance__gte=amount)
    
    def get_total_balance(self):
        """Get total balance across all accounts"""
        total = self.aggregate(total=Sum('balance'))['total']
        return total or Decimal('0.00')


class SavingsAccountManager(models.Manager):
    """Custom Manager for SavingsAccount model"""
    
    def get_queryset(self):
        return SavingsAccountQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def for_client(self, client):
        return self.get_queryset().for_client(client)
    
    def for_branch(self, branch):
        return self.get_queryset().for_branch(branch)


class TransactionQuerySet(BranchFilteredQuerySet):
    """Custom QuerySet for Transaction model"""
    
    def completed(self):
        """Completed transactions"""
        return self.filter(status='completed')
    
    def pending(self):
        """Pending transactions"""
        return self.filter(status='pending')
    
    def approved(self):
        """Approved transactions"""
        return self.filter(status='approved')
    
    def by_type(self, transaction_type):
        """Filter by transaction type"""
        return self.filter(transaction_type=transaction_type)
    
    def deposits(self):
        """Deposit transactions"""
        return self.filter(transaction_type='deposit')
    
    def withdrawals(self):
        """Withdrawal transactions"""
        return self.filter(transaction_type='withdrawal')
    
    def loan_transactions(self):
        """Loan-related transactions"""
        return self.filter(
            transaction_type__in=['loan_disbursement', 'loan_repayment']
        )
    
    def income_transactions(self):
        """Income transactions (fees, charges)"""
        return self.filter(is_income=True)
    
    def for_client(self, client):
        """Transactions for specific client"""
        return self.filter(client=client)
    
    def for_date_range(self, start_date, end_date):
        """Transactions in date range"""
        return self.filter(
            transaction_date__gte=start_date,
            transaction_date__lte=end_date
        )
    
    def today(self):
        """Today's transactions"""
        today = timezone.now().date()
        return self.filter(transaction_date__date=today)
    
    def this_month(self):
        """This month's transactions"""
        today = timezone.now().date()
        return self.filter(
            transaction_date__year=today.year,
            transaction_date__month=today.month
        )
    
    def get_summary(self):
        """Get transaction summary"""
        aggregate_data = self.aggregate(
            total_transactions=Count('id'),
            total_amount=Sum('amount'),
        )
        
        deposits_total = self.deposits().completed().aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        withdrawals_total = self.withdrawals().completed().aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        income_total = self.income_transactions().completed().aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        return {
            'total_transactions': aggregate_data['total_transactions'],
            'total_amount': aggregate_data['total_amount'] or Decimal('0.00'),
            'deposits_total': deposits_total,
            'withdrawals_total': withdrawals_total,
            'income_total': income_total,
            'net_flow': deposits_total - withdrawals_total,
        }


class TransactionManager(models.Manager):
    """Custom Manager for Transaction model"""
    
    def get_queryset(self):
        return TransactionQuerySet(self.model, using=self._db)
    
    def completed(self):
        return self.get_queryset().completed()
    
    def pending(self):
        return self.get_queryset().pending()
    
    def for_branch(self, branch):
        return self.get_queryset().for_branch(branch)
    
    def today(self):
        return self.get_queryset().today()
    
    def this_month(self):
        return self.get_queryset().this_month()


class ClientGroupQuerySet(BranchFilteredQuerySet, ActiveInactiveQuerySet):
    """Custom QuerySet for ClientGroup model"""
    
    def pending_approval(self):
        """Groups pending approval"""
        return self.filter(status='pending')
    
    def approved(self):
        """Approved/active groups"""
        return self.filter(status='active')
    
    def closed(self):
        """Closed groups"""
        return self.filter(status='closed')
    
    def for_staff(self, staff):
        """Groups managed by staff"""
        return self.filter(loan_officer=staff)
    
    def by_meeting_day(self, day):
        """Groups meeting on specific day"""
        return self.filter(meeting_day=day)
    
    def by_group_type(self, group_type):
        """Filter by group type"""
        return self.filter(group_type=group_type)
    
    def with_members_above(self, count):
        """Groups with more than X members"""
        return self.filter(total_members__gte=count)
    
    def with_members_below(self, count):
        """Groups with less than X members"""
        return self.filter(total_members__lte=count)
    
    def at_capacity(self):
        """Groups that have reached max capacity"""
        return self.filter(
            max_members__isnull=False,
            total_members__gte=models.F('max_members')
        )
    
    def with_capacity(self):
        """Groups that still have capacity"""
        return self.filter(
            models.Q(max_members__isnull=True) |
            models.Q(total_members__lt=models.F('max_members'))
        )
    
    def get_statistics(self):
        """Get group statistics"""
        from decimal import Decimal
        
        aggregate_data = self.aggregate(
            total_groups=Count('id'),
            total_members=Sum('total_members'),
            total_savings=Sum('total_savings'),
            total_loans_outstanding=Sum('total_loans_outstanding'),
        )
        
        return {
            'total_groups': aggregate_data['total_groups'] or 0,
            'total_members': aggregate_data['total_members'] or 0,
            'total_savings': aggregate_data['total_savings'] or Decimal('0.00'),
            'total_loans_outstanding': aggregate_data['total_loans_outstanding'] or Decimal('0.00'),
            'active_groups': self.filter(status='active').count(),
            'pending_groups': self.filter(status='pending').count(),
        }


class ClientGroupManager(models.Manager):
    """Custom Manager for ClientGroup model"""
    
    def get_queryset(self):
        return ClientGroupQuerySet(self.model, using=self._db)
    
    def active(self):
        """Get active groups"""
        return self.get_queryset().filter(status='active')
    
    def pending(self):
        """Get pending groups"""
        return self.get_queryset().pending_approval()
    
    def approved(self):
        """Get approved/active groups (alias for active)"""
        return self.get_queryset().approved()
    
    def for_branch(self, branch):
        """Get groups for specific branch"""
        return self.get_queryset().for_branch(branch)
    
    def for_staff(self, staff):
        """Get groups managed by specific staff"""
        return self.get_queryset().for_staff(staff)
    
    def by_group_type(self, group_type):
        """Get groups by type"""
        return self.get_queryset().by_group_type(group_type)
    
    def with_capacity(self):
        """Get groups that still have capacity for new members"""
        return self.get_queryset().with_capacity()
    
    def at_capacity(self):
        """Get groups at maximum capacity"""
        return self.get_queryset().at_capacity()
    

