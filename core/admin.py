from django.contrib import admin
from .models import (
    Branch, User, ClientGroup, Client,
    LoanProduct, SavingsProduct, SavingsAccount, Loan,
    Transaction, AccountType, AccountCategory, ChartOfAccounts,
    JournalEntry, JournalEntryLine, Notification,
    Guarantor, NextOfKin, AssignmentRequest,
    LoanRepaymentSchedule, LoanPenalty
)

# ==============================================================================
# CORE MODELS
# ==============================================================================

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'city', 'state', 'is_active', 'created_at']
    list_filter = ['is_active', 'state', 'city']
    search_fields = ['code', 'name', 'city']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'get_full_name', 'user_role', 'branch', 'is_active', 'is_approved']
    list_filter = ['user_role', 'is_active', 'is_approved', 'branch']
    search_fields = ['email', 'first_name', 'last_name', 'employee_id']
    readonly_fields = ['employee_id', 'date_joined', 'last_login']
    
    fieldsets = (
        ('Authentication', {
            'fields': ('email', 'password', 'employee_id')
        }),
        ('Personal Info', {
            'fields': ('first_name', 'last_name', 'phone')
        }),
        ('Employment', {
            'fields': ('user_role', 'designation', 'department', 'branch', 
                      'reports_to', 'hire_date', 'salary')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'is_approved',
                      'can_approve_loans', 'max_approval_amount')
        }),
        ('Timestamps', {
            'fields': ('date_joined', 'last_login'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ClientGroup)
class ClientGroupAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'branch', 'loan_officer', 'total_members', 
                   'status', 'meeting_day']
    list_filter = ['status', 'branch', 'meeting_day']
    search_fields = ['code', 'name']
    readonly_fields = ['code', 'total_members', 'active_members', 
                      'total_savings', 'total_loans_outstanding']


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['client_id', 'get_full_name', 'email', 'phone', 'branch',
                   'approval_status', 'registration_fee_paid']
    list_filter = ['approval_status', 'registration_fee_paid',
                  'branch', 'group', 'is_active']
    search_fields = ['client_id', 'email', 'first_name', 'last_name', 'phone']
    readonly_fields = ['client_id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Identifiers', {
            'fields': ('client_id',)
        }),
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 
                      'alternate_phone', 'date_of_birth', 'gender', 
                      'marital_status', 'number_of_dependents')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'postal_code', 'country')
        }),
        ('Assignment', {
            'fields': ('branch', 'group', 'assigned_staff', 'union_location')
        }),
        ('Client Status', {
            'fields': ('registration_fee_paid', 'approval_status', 'is_active')
        }),
        ('Employment/Business', {
            'fields': ('occupation', 'employer', 'monthly_income',
                      'business_name', 'business_type', 'business_location'),
            'classes': ('collapse',)
        }),
    )


# ==============================================================================
# PRODUCT MODELS
# ==============================================================================

@admin.register(LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'loan_type', 'min_principal_amount',
                   'max_principal_amount', 'monthly_interest_rate', 'is_active']
    list_filter = ['loan_type', 'is_active', 'is_featured']
    search_fields = ['code', 'name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SavingsProduct)
class SavingsProductAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'interest_rate_annual', 'minimum_balance', 'is_active']
    list_filter = [ 'is_active']
    search_fields = ['code', 'name']
    readonly_fields = ['created_at', 'updated_at']


# ==============================================================================
# ACCOUNT MODELS
# ==============================================================================

@admin.register(SavingsAccount)
class SavingsAccountAdmin(admin.ModelAdmin):
    list_display = ['account_number', 'client', 'balance',
                   'status', 'branch']
    list_filter = ['status', 'branch', 'is_auto_created']
    search_fields = ['account_number', 'client__first_name', 'client__last_name']
    readonly_fields = ['account_number', 'balance', 'interest_earned', 
                      'date_opened', 'created_at']


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ['loan_number', 'client', 'principal_amount', 
                   'outstanding_balance', 'status', 'disbursement_date']
    list_filter = ['status', 'loan_product__loan_type', 'branch', 'fees_paid']
    search_fields = ['loan_number', 'client__first_name', 'client__last_name']
    readonly_fields = ['loan_number', 'total_interest', 'total_repayment',
                      'installment_amount', 'amount_paid', 'outstanding_balance',
                      'application_date', 'created_at']
    
    fieldsets = (
        ('Loan Details', {
            'fields': ('loan_number', 'client', 'loan_product', 'branch')
        }),
        ('Amounts', {
            'fields': ('principal_amount', 'duration_months', 
                      'total_interest', 'total_repayment', 'installment_amount')
        }),
        ('Fees', {
            'fields': ('total_upfront_fees', 'fees_paid', 'fees_paid_date'),
        }),
        ('Status & Dates', {
            'fields': ('status', 'application_date', 'approval_date',
                      'disbursement_date', 'completion_date')
        }),
        ('Repayment Tracking', {
            'fields': ('amount_paid', 'outstanding_balance',
                      'next_repayment_date', 'first_repayment_date')
        }),
    )


# ==============================================================================
# TRANSACTION & ACCOUNTING
# ==============================================================================

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_ref', 'transaction_type', 'amount', 
                   'client', 'status', 'transaction_date', 'is_income']
    list_filter = ['transaction_type', 'status', 'is_income', 'branch']
    search_fields = ['transaction_ref', 'client__first_name', 'client__last_name']
    readonly_fields = ['transaction_ref', 'transaction_date', 'created_at']
    date_hierarchy = 'transaction_date'


@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'normal_balance', 'description']


@admin.register(AccountCategory)
class AccountCategoryAdmin(admin.ModelAdmin):
    list_display = ['code_prefix', 'name', 'account_type']
    list_filter = ['account_type']


@admin.register(ChartOfAccounts)
class ChartOfAccountsAdmin(admin.ModelAdmin):
    list_display = ['gl_code', 'account_name', 'account_type', 
                   'is_active', 'branch']
    list_filter = ['account_type', 'is_active', 'branch']
    search_fields = ['gl_code', 'account_name']


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ['journal_number', 'entry_type', 'transaction_date',
                   'status', 'branch']
    list_filter = ['entry_type', 'status', 'branch']
    search_fields = ['journal_number', 'description']
    readonly_fields = ['journal_number', 'posted_at', 'created_at']
    date_hierarchy = 'transaction_date'


@admin.register(JournalEntryLine)
class JournalEntryLineAdmin(admin.ModelAdmin):
    list_display = ['journal_entry', 'account', 'debit_amount', 
                   'credit_amount', 'client']
    list_filter = ['journal_entry__status']
    search_fields = ['journal_entry__journal_number', 'account__gl_code']


# ==============================================================================
# SUPPORTING MODELS
# ==============================================================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'notification_type', 'is_read', 
                   'is_urgent', 'created_at']
    list_filter = ['notification_type', 'is_read', 'is_urgent']
    search_fields = ['title', 'message', 'user__email']
    readonly_fields = ['created_at', 'read_at']


@admin.register(Guarantor)
class GuarantorAdmin(admin.ModelAdmin):
    list_display = ['name', 'loan', 'phone', 'relationship', 'occupation']
    search_fields = ['name', 'phone', 'client__first_name',]


@admin.register(NextOfKin)
class NextOfKinAdmin(admin.ModelAdmin):
    list_display = ['name', 'client', 'phone', 'relationship']
    search_fields = ['name', 'phone', 'client__first_name', 'client__last_name']


@admin.register(AssignmentRequest)
class AssignmentRequestAdmin(admin.ModelAdmin):
    list_display = ['assignment_type', 'requested_by', 'status', 
                   'affected_count', 'created_at']
    list_filter = ['assignment_type', 'status', 'branch']
    search_fields = ['description']
    readonly_fields = ['created_at', 'reviewed_at', 'executed_at']


@admin.register(LoanRepaymentSchedule)
class LoanRepaymentScheduleAdmin(admin.ModelAdmin):
    list_display = ['loan', 'installment_number', 'due_date', 'total_amount',
                   'amount_paid', 'outstanding_amount', 'status']
    list_filter = ['status', 'loan__status']
    search_fields = ['loan__loan_number']
    readonly_fields = ['outstanding_amount']


@admin.register(LoanPenalty)
class LoanPenaltyAdmin(admin.ModelAdmin):
    list_display = ['loan', 'penalty_type', 'amount', 'is_paid', 
                   'is_waived', 'created_at']
    list_filter = ['penalty_type', 'is_paid', 'is_waived']
    search_fields = ['loan__loan_number', 'reason']

    