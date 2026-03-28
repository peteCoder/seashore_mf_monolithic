"""
Seashore Microfinance Bank - COMPLETE Consolidated Models
==========================================================

ALL MODELS IN ONE FILE FOR DJANGO MIGRATIONS

This file contains all 15+ models consolidated from multiple files.
Auto-generated - do not edit manually.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction as db_transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from cloudinary.models import CloudinaryField
from datetime import timedelta, date
from decimal import Decimal, ROUND_UP, ROUND_HALF_UP
import uuid
from datetime import time

# Import base models and utilities
from .base import BaseModel, AuditedModel, ApprovalWorkflowMixin, StatusTrackingMixin
from core.utils.money import MoneyCalculator, InterestCalculator
from core.managers import (
    ClientManager, LoanManager, SavingsAccountManager, 
    TransactionManager, ClientGroupManager
)

from core.utils.helpers import (
    generate_repayment_schedule,
    count_business_days_in_months,
    next_business_day,
    add_one_business_day,
)
from core.utils.accounting_helpers import (
    post_loan_disbursement_journal,
    post_loan_repayment_journal,
    post_loan_upfront_fees_journal,
    post_savings_deposit_journal,
    post_savings_withdrawal_journal,
)

import logging
import calendar
from django.db.models import F, Q





logger = logging.getLogger(__name__)



# =============================================================================
# FROM: models.py
# =============================================================================


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

MONTHLY_INTEREST_RATE = Decimal('0.035')  # 3.5% per month (flat rate)
LOAN_INSURANCE_RATE = Decimal('0.03')  # 3% of principal
LOAN_FORM_FEE = Decimal('200.00')  # Fixed N200
# Registration fee line items (each becomes its own transaction + journal entry)
CLIENT_REGISTRATION_FEE_BREAKDOWN = [
    {'key': 'registration_fee',    'label': 'Registration Fee', 'amount': Decimal('2000.00'), 'gl_code': '4110'},
    {'key': 'membership_card_fee', 'label': 'Membership Card',  'amount': Decimal('100.00'),  'gl_code': '4114'},
]
CLIENT_REGISTRATION_FEE = sum(item['amount'] for item in CLIENT_REGISTRATION_FEE_BREAKDOWN)  # 2100.00


# =============================================================================
# CENTRALIZED LOAN TYPE CHOICES
# =============================================================================

LOAN_TYPE_CHOICES = [
    ('regular', 'Regular Loan'),
    ('special', 'Special Loan'),
    ('med',     'Med Loan'),
    ('asset',   'Asset Loan'),
    ('thrift',  'Thrift Loan'),
    ('midterm', 'Midterm Loan'),
    ('golden',  'Golden Loan'),
]

# Default repayment frequency seeded per loan type when a new product is created.
# After creation the admin can override via the repayment_frequency field.
REPAYMENT_FREQUENCY_MAP = {
    'regular': 'weekly',
    'special': 'monthly',
    'med':     'monthly',
    'asset':   'monthly',
    'thrift':  'daily',
    'midterm': 'weekly',
    'golden':  'monthly',
}

REPAYMENT_FREQUENCY_CHOICES = [
    ('daily',       'Daily'),
    ('weekly',      'Weekly'),
    ('fortnightly', 'Fortnightly'),
    ('monthly',     'Monthly'),
    ('yearly',      'Yearly'),
]


# =============================================================================
# BRANCH MODEL (ENHANCED)
# =============================================================================

class Branch(BaseModel, StatusTrackingMixin):
    """
    Branch/Office Locations
    
    ENHANCEMENTS:
    - Inherits from BaseModel (soft delete + timestamps)
    - Inherits from StatusTrackingMixin (is_active tracking)
    - Added constraints for data integrity
    - Added comprehensive indexing
    """
    
    name = models.CharField(
        max_length=100, 
        help_text="Branch name"
    )
    code = models.CharField(
        max_length=20, 
        unique=True,
        db_index=True,
        help_text="Unique branch code (e.g., 'MB01', 'IKJ')"
    )
    address = models.TextField()
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    
    # Manager assignment
    manager = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_branches',
        limit_choices_to={'user_role': 'manager'},
        help_text="Branch manager"
    )

    class Meta:
        verbose_name_plural = "Branches"
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
            models.Index(fields=['state', 'city']),
        ]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(code=''),
                name='branch_code_not_empty'
            ),
            models.UniqueConstraint(
                fields=['code'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_branch_code'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def clean(self):
        """Validate branch data"""
        super().clean()
        
        errors = {}
        
        # Validate code format (alphanumeric, no spaces)
        if self.code and not self.code.replace('-', '').replace('_', '').isalnum():
            errors['code'] = "Branch code must be alphanumeric (hyphens/underscores allowed)"
        
        # Validate phone format
        if self.phone and not self.phone.replace('+', '').replace('-', '').replace(' ', '').isdigit():
            errors['phone'] = "Invalid phone number format"
        
        if errors:
            raise ValidationError(errors)
    
    def get_staff_count(self):
        """Get number of staff in this branch"""
        return self.users.filter(is_active=True).count()
    
    def get_client_count(self):
        """Get number of clients in this branch"""
       
        return self.clients.filter(is_active=True, approval_status='approved').count()
    
    def get_active_loans_count(self):
        """Get number of active loans in this branch"""
        return self.loans.filter(status__in=['active', 'disbursed', 'overdue']).count()
    
    def get_portfolio_summary(self):
        """Get branch portfolio summary"""
        from django.db.models import Sum, Count
        
        loans = self.loans.filter(status__in=['active', 'disbursed', 'overdue'])
        loan_summary = loans.aggregate(
            total_loans=Count('id'),
            total_disbursed=Sum('amount_disbursed'),
            total_outstanding=Sum('outstanding_balance'),
        )
        
        savings = self.savings_accounts.filter(status='active')
        savings_summary = savings.aggregate(
            total_accounts=Count('id'),
            total_balance=Sum('balance'),
        )
        
        return {
            **loan_summary,
            **savings_summary,
            'staff_count': self.get_staff_count(),
            'client_count': self.get_client_count(),  # This calls the fixed method above
        }

# =============================================================================
# USER MODEL & MANAGER (ENHANCED)
# =============================================================================

class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication"""
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email address is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_approved', True)
        extra_fields.setdefault('user_role', 'admin')
        return self.create_user(email, password, **extra_fields)
    
    def active_staff(self):
        """Get all active staff members"""
        return self.filter(
            is_active=True,
            is_approved=True,
            user_role__in=['staff', 'manager', 'director', 'hr', 'admin']
        )
    
    def managers(self):
        """Get all managers"""
        return self.filter(user_role='manager', is_active=True)
    
    def directors(self):
        """Get all directors"""
        return self.filter(user_role='director', is_active=True)
    
    def for_branch(self, branch):
        """Get staff for specific branch"""
        return self.filter(branch=branch, is_active=True)


class User(AbstractUser, StatusTrackingMixin):
    """
    Custom User Model - Email-based authentication with integrated staff fields
    
    ENHANCEMENTS:
    - Inherits from StatusTrackingMixin
    - Added database constraints
    - Added comprehensive validation
    - Added helper methods for permissions
    - Improved indexing
    """
    
    ROLE_CHOICES = [
        ('staff', 'Staff/Loan Officer'),
        ('manager', 'Branch Manager'),
        ('director', 'Director'),
        ('hr', 'Human Resources Manager'),
        ('admin', 'System Administrator'),
    ]
    
    DEPARTMENT_CHOICES = [
        ('operations', 'Operations'),
        ('loans', 'Loans'),
        ('savings', 'Savings'),
        ('customer_service', 'Customer Service'),
        ('accounts', 'Accounts/Finance'),
        ('IT', 'IT/Technical'),
        ('management', 'Management'),
        ('board', 'Board of Directors'),
    ]
    
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]
    
    BLOOD_GROUP_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'),
        ('O+', 'O+'), ('O-', 'O-'),
    ]
    
    ID_TYPE_CHOICES = [
        ('national_id', 'National ID'),
        ('passport', 'International Passport'),
        ('drivers_license', "Driver's License"),
        ('voters_card', "Voter's Card"),
    ]

    # ============================================
    # CORE USER FIELDS
    # ============================================
    username = None
    email = models.EmailField(unique=True, db_index=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_role = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$')
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    branch = models.ForeignKey(
        Branch, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='users'
    )
    
    # ============================================
    # EMPLOYEE INFORMATION
    # ============================================
    employee_id = models.CharField(
        max_length=20, 
        unique=True, 
        blank=True, 
        null=True,
        db_index=True,
        help_text="Auto-generated employee ID (EMP001, EMP002, etc.)"
    )
    city = models.CharField(
        max_length=100, 
        blank=True,
        help_text="City"
    )
    state = models.CharField(
        max_length=100, 
        blank=True,
        help_text="State"
    )
    designation = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Job title/position"
    )
    department = models.CharField(
        max_length=50, 
        choices=DEPARTMENT_CHOICES,
        blank=True
    )

    # Password Reset (ADD THESE)
    password_reset_token = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Token for password reset"
    )
    password_reset_expires = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expiry time for reset token"
    )
    
    # Employment Dates
    hire_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    
    # ============================================
    # COMPENSATION
    # ============================================
    salary = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    bank_account = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    
    # ============================================
    # PERSONAL INFORMATION
    # ============================================
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=10, 
        choices=GENDER_CHOICES, 
        blank=True
    )
    blood_group = models.CharField(
        max_length=5, 
        choices=BLOOD_GROUP_CHOICES, 
        blank=True
    )
    address = models.TextField(blank=True)
    
    # ============================================
    # EMERGENCY CONTACT
    # ============================================
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=17, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)
    
    # ============================================
    # REPORTING STRUCTURE
    # ============================================
    reports_to = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='direct_reports'
    )
    
    # ============================================
    # APPROVAL PERMISSIONS
    # ============================================
    can_approve_loans = models.BooleanField(default=False)
    can_approve_accounts = models.BooleanField(default=False)
    max_approval_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Maximum amount this staff can approve"
    )
    
    # ============================================
    # IDENTIFICATION
    # ============================================
    id_type = models.CharField(
        max_length=50, 
        choices=ID_TYPE_CHOICES,
        blank=True
    )
    id_number = models.CharField(max_length=50, blank=True)
    
    # ============================================
    # DOCUMENTS/IMAGES
    # ============================================
    profile_picture = CloudinaryField(
        'profile_picture', 
        folder='staff/profile_pictures', 
        null=True, 
        blank=True, 
        resource_type='image'
    )
    id_card_front = CloudinaryField(
        'id_card_front', 
        folder='staff/id_cards/front', 
        null=True, 
        blank=True, 
        resource_type='image'
    )
    id_card_back = CloudinaryField(
        'id_card_back', 
        folder='staff/id_cards/back', 
        null=True, 
        blank=True, 
        resource_type='image'
    )
    cv_document = CloudinaryField(
        'cv_document', 
        folder='staff/cv_documents', 
        null=True, 
        blank=True, 
        resource_type='raw'
    )
    
    # ============================================
    # ADDITIONAL NOTES
    # ============================================
    notes = models.TextField(blank=True)
    
    # ============================================
    # ACCOUNT STATUS & SECURITY
    # ============================================
    is_approved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(null=True, blank=True)
    
    failed_login_attempts = models.IntegerField(default=0)
    account_locked_until = models.DateTimeField(null=True, blank=True)

    # ============================================
    # TWO-FACTOR AUTHENTICATION (TOTP)
    # ============================================
    totp_secret = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Base32 TOTP secret key (set when user enables 2FA)",
    )
    is_2fa_enabled = models.BooleanField(
        default=False,
        help_text="Whether TOTP two-factor authentication is enabled",
    )

    # ============================================
    # DJANGO PERMISSIONS
    # ============================================
    groups = models.ManyToManyField(
        'auth.Group', 
        blank=True, 
        related_name='custom_user_set'
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', 
        blank=True, 
        related_name='custom_user_set'
    )

    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'user_role']

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['user_role', 'is_active']),
            models.Index(fields=['employee_id']),
            models.Index(fields=['is_approved', 'is_active']),
            models.Index(fields=['branch', 'user_role']),
            models.Index(fields=['hire_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(salary__gte=0) | models.Q(salary__isnull=True),
                name='user_salary_positive'
            ),
            models.CheckConstraint(
                check=models.Q(max_approval_amount__gte=0) | models.Q(max_approval_amount__isnull=True),
                name='user_max_approval_positive'
            ),
            models.CheckConstraint(
                check=models.Q(failed_login_attempts__gte=0),
                name='user_failed_attempts_positive'
            ),
        ]

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_user_role_display()})"

    def save(self, *args, **kwargs):
        # Auto-set approval permissions for managers and above
        if self.user_role in ['manager', 'director', 'hr', 'admin']:
            self.can_approve_loans = True
            self.can_approve_accounts = True

        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_employee_id():
        """Auto-generate employee ID (EMP001, EMP002, etc.)"""
        last_user = User.objects.filter(
            employee_id__startswith='EMP'
        ).order_by('-employee_id').first()
        
        if last_user and last_user.employee_id:
            try:
                last_number = int(last_user.employee_id[3:])
                new_number = last_number + 1
            except (ValueError, IndexError):
                new_number = 1
        else:
            new_number = 1
        
        return f'EMP{new_number:03d}'

    def clean(self):
        """Validate user data"""
        super().clean()
        
        errors = {}
        
        # Validate email
        if self.email and not '@' in self.email:
            errors['email'] = "Invalid email format"
        
        # Validate dates
        if self.hire_date and self.termination_date:
            if self.termination_date < self.hire_date:
                errors['termination_date'] = "Termination date cannot be before hire date"
        
        # Validate date of birth
        if self.date_of_birth:
            age = (timezone.now().date() - self.date_of_birth).days // 365
            if age < 18:
                errors['date_of_birth'] = "Staff member must be at least 18 years old"
            if age > 100:
                errors['date_of_birth'] = "Please check date of birth"
        
        # Validate branch assignment for non-admin roles
        if self.user_role in ['staff', 'manager'] and not self.branch:
            errors['branch'] = f"{self.get_user_role_display()} must be assigned to a branch"
        # director, hr, and admin operate across all branches — no branch assignment required
        
        if errors:
            raise ValidationError(errors)

    # ============================================
    # HELPER METHODS
    # ============================================
    
    def is_employment_active(self):
        """Check if staff is currently employed"""
        return self.termination_date is None and self.is_active
    
    def can_approve_users(self):
        """Check if user can approve other users"""
        return self.user_role in ['manager', 'director', 'hr', 'admin'] and self.is_approved

    def can_approve_transactions(self):
        """Check if user can approve transactions"""
        return self.user_role in ['manager', 'director', 'hr', 'admin'] and self.is_approved

    def can_approve_loan_amount(self, amount):
        """Check if user can approve loan of given amount"""
        if not self.can_approve_loans:
            return False
        if self.user_role in ['director', 'hr', 'admin']:
            return True
        if self.max_approval_amount:
            return Decimal(str(amount)) <= self.max_approval_amount
        return False

    def get_accessible_branches(self):
        """Get branches accessible to this user"""
        if self.user_role in ['director', 'hr', 'admin']:
            return Branch.objects.active()
        elif self.user_role in ['manager', 'staff'] and self.branch:
            return Branch.objects.filter(id=self.branch_id, is_active=True)
        return Branch.objects.none()
    
    def get_managed_clients_count(self):
        """Get number of clients assigned to this staff"""
        if self.user_role == 'staff':
            return self.assigned_clients.filter(is_active=True).count()
        elif self.user_role == 'manager' and self.branch:
            return self.branch.clients.filter(is_active=True).count()
        return 0
    
    def get_active_loans_count(self):
        """Get number of active loans managed by this staff"""
        if self.user_role == 'staff':
            return self.assigned_clients.filter(
                loans__status__in=['active', 'disbursed', 'overdue']
            ).count()
        elif self.user_role == 'manager' and self.branch:
            return self.branch.loans.filter(
                status__in=['active', 'disbursed', 'overdue']
            ).count()
        return 0
    
    @property
    def age(self):
        """Calculate age from date of birth"""
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None
    
    # Image URL helper methods
    def get_profile_picture_url(self):
        if self.profile_picture:
            try:
                return self.profile_picture.url
            except:
                return None
        return None
    
    def get_id_card_front_url(self):
        if self.id_card_front:
            try:
                return self.id_card_front.url
            except:
                return None
        return None
    
    def get_id_card_back_url(self):
        if self.id_card_back:
            try:
                return self.id_card_back.url
            except:
                return None
        return None


# =============================================================================
# CLIENT GROUP MODEL (ENHANCED)
# =============================================================================

class ClientGroup(BaseModel, StatusTrackingMixin, ApprovalWorkflowMixin):
    """
    Client Groups - For organizing clients into groups
    
    ENHANCEMENTS:
    - Inherits from BaseModel, StatusTrackingMixin, ApprovalWorkflowMixin
    - Added custom manager
    - Added validation
    - Added statistics calculation
    """
    
    GROUP_TYPE_CHOICES = [
        ('lending', 'Lending Group'),
        ('savings', 'Savings Group'),
        ('mixed', 'Mixed (Lending & Savings)'),
        ('cooperative', 'Cooperative'),
        ('self_help', 'Self-Help Group'),
    ]
    
    DAY_CHOICES = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]
    
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('fortnightly', 'Fortnightly'),
        ('monthly', 'Monthly'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('closed', 'Closed'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True, db_index=True, blank=True)
    description = models.TextField(blank=True)
    
    # NEW: Group Type
    group_type = models.CharField(
        max_length=20,
        choices=GROUP_TYPE_CHOICES,
        default='mixed',
        help_text="Type of group activity"
    )
    
    branch = models.ForeignKey(
        Branch, 
        on_delete=models.PROTECT, 
        related_name='client_groups'
    )
    loan_officer = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='managed_client_groups',
        limit_choices_to={'user_role__in': ['staff', 'manager']}
    )
    
    registration_date = models.DateField(default=date.today)
    meeting_day = models.CharField(
        max_length=10, 
        choices=DAY_CHOICES,
        blank=True,
        help_text="Day of the week for group meetings"
    )
    meeting_frequency = models.CharField(
        max_length=20, 
        choices=FREQUENCY_CHOICES, 
        default='weekly'
    )
    meeting_time = models.TimeField(
        null=True, 
        blank=True,
        help_text="Time of group meetings"
    )
    
    # RENAMED: union_location -> meeting_location
    meeting_location = models.CharField(
        max_length=200, 
        blank=True,
        help_text="Physical location where group meets"
    )
    
    # NEW: Max Members
    max_members = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of members allowed (leave empty for unlimited)"
    )
    
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending',
        db_index=True
    )
    
    # Statistics (auto-calculated)
    total_members = models.IntegerField(default=0)
    active_members = models.IntegerField(default=0)
    total_savings = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        default=Decimal('0.00')
    )
    total_loans_outstanding = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        default=Decimal('0.00')
    )
    
    # Audit
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='created_client_groups'
    )
    
    # Custom Manager
    objects = ClientGroupManager()
    
    class Meta:
        ordering = ['name']
        verbose_name = "Client Group"
        verbose_name_plural = "Client Groups"
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['meeting_day']),
            models.Index(fields=['loan_officer']),
            models.Index(fields=['group_type']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(total_members__gte=0),
                name='group_total_members_positive'
            ),
            models.CheckConstraint(
                check=models.Q(active_members__gte=0),
                name='group_active_members_positive'
            ),
            models.CheckConstraint(
                check=models.Q(total_savings__gte=0),
                name='group_total_savings_positive'
            ),
            models.CheckConstraint(
                check=models.Q(total_loans_outstanding__gte=0),
                name='group_loans_outstanding_positive'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_group_code()
        self.name = self.name.title()
        super().save(*args, **kwargs)
    
    def generate_group_code(self):
        """Generate unique group code"""
        from django.utils.crypto import get_random_string
        
        branch_code = self.branch.code[:3].upper() if self.branch else 'GRP'
        random_suffix = get_random_string(5, '0123456789')
        code = f"GRP-{branch_code}-{random_suffix}"
        
        max_attempts = 10
        attempts = 0
        while ClientGroup.objects.filter(code=code).exists() and attempts < max_attempts:
            random_suffix = get_random_string(5, '0123456789')
            code = f"GRP-{branch_code}-{random_suffix}"
            attempts += 1
        
        return code
    
    def clean(self):
        """Validate group data"""
        super().clean()
        
        errors = {}
        
        # Validate name is not empty
        if not self.name or not self.name.strip():
            errors['name'] = "Group name cannot be empty"
        
        # Validate loan officer is from same branch
        if self.loan_officer and self.branch:
            if self.loan_officer.branch_id != self.branch_id:
                errors['loan_officer'] = "Loan officer must be from the same branch"
        
        # Validate max_members
        if self.max_members is not None and self.max_members < 2:
            errors['max_members'] = "Maximum members must be at least 2"
        
        if errors:
            raise ValidationError(errors)
    
    @db_transaction.atomic
    def update_statistics(self):
        """
        Update group statistics
        
        Called automatically when members are added/removed or when
        member loans/savings change
        """
        from django.db.models import Sum, Count
        
        # Get active members
        members = self.members.filter(is_active=True, approval_status='approved')
        self.total_members = self.members.count()
        self.active_members = members.count()
        
        # Calculate total savings
        from core.models import SavingsAccount
        total_savings = SavingsAccount.objects.filter(
            client__group=self,
            status='active'
        ).aggregate(total=Sum('balance'))['total'] or Decimal('0.00')
        
        # Calculate total outstanding loans
        from core.models import Loan
        total_loans = Loan.objects.filter(
            client__group=self,
            status__in=['active', 'disbursed', 'overdue']
        ).aggregate(total=Sum('outstanding_balance'))['total'] or Decimal('0.00')
        
        self.total_loans_outstanding = total_loans
        self.total_savings = total_savings
        
        self.save(update_fields=[
            'total_members', 'active_members', 'total_savings', 
            'total_loans_outstanding', 'updated_at'
        ])
    
    def get_meeting_schedule_text(self):
        """Get human-readable meeting schedule"""
        day = self.get_meeting_day_display() if self.meeting_day else "TBD"
        freq = self.get_meeting_frequency_display()
        time_str = self.meeting_time.strftime('%I:%M %p') if self.meeting_time else ''
        
        if time_str:
            return f"{freq} on {day}s at {time_str}"
        return f"{freq} on {day}s"
    
    def can_add_member(self, client):
        """Check if client can be added to group"""
        if self.status != 'active':
            return False, "Group is not active"
        
        if client.group and client.group != self:
            return False, "Client already belongs to another group"
        
        if client.branch_id != self.branch_id:
            return False, "Client must be from the same branch"
        
        # Check max_members limit
        if self.max_members and self.total_members >= self.max_members:
            return False, f"Group has reached maximum capacity ({self.max_members} members)"
        
        return True, "OK"


# =============================================================================
# GROUP MEMBERSHIP REQUEST MODEL
# =============================================================================

class GroupMembershipRequest(BaseModel):
    """
    Track pending member additions to client groups

    When a client is added to a group, a membership request is created
    with status='pending'. Once approved by a manager/director/admin,
    the client's group and group_role fields are updated.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    group = models.ForeignKey(
        ClientGroup,
        on_delete=models.CASCADE,
        related_name='membership_requests'
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.CASCADE,
        related_name='group_membership_requests'
    )
    requested_role = models.CharField(
        max_length=20,
        choices=[
            ('member', 'Member'),
            ('secretary', 'Secretary'),
            ('leader', 'Leader'),
        ],
        default='member',
        help_text="Requested role within the group"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    # Who requested the addition
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_memberships'
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    # Who approved/rejected
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_memberships'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = "Group Membership Request"
        verbose_name_plural = "Group Membership Requests"
        # Note: unique_together removed to allow clients to rejoin groups after leaving
        # Application logic should prevent duplicate pending requests instead
        indexes = [
            models.Index(fields=['status', 'group']),
            models.Index(fields=['client', 'status']),
            models.Index(fields=['requested_at']),
        ]

    def __str__(self):
        return f"{self.client.full_name} → {self.group.name} ({self.status})"

    def clean(self):
        """Validate that there are no duplicate pending requests"""
        if self.status == 'pending':
            # Check for existing pending requests for this client/group combination
            existing = GroupMembershipRequest.objects.filter(
                group=self.group,
                client=self.client,
                status='pending'
            ).exclude(pk=self.pk)

            if existing.exists():
                raise ValidationError(
                    f"{self.client.full_name} already has a pending membership request for {self.group.name}"
                )

    def approve(self, reviewed_by):
        """Approve the membership request and add client to group"""
        from django.utils import timezone

        if self.status != 'pending':
            raise ValidationError("Only pending requests can be approved")

        # Update client's group and role
        self.client.group = self.group
        self.client.group_role = self.requested_role
        self.client.save(update_fields=['group', 'group_role', 'updated_at'])

        # Update request status
        self.status = 'approved'
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        # Update group statistics
        self.group.update_statistics()

    def reject(self, reviewed_by, notes=''):
        """Reject the membership request"""
        from django.utils import timezone

        if self.status != 'pending':
            raise ValidationError("Only pending requests can be rejected")

        self.status = 'rejected'
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.review_notes = notes
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])


# =============================================================================
# CLIENT MODEL (ENHANCED)
# =============================================================================

class Client(BaseModel, StatusTrackingMixin, ApprovalWorkflowMixin):
    """
    Client/Customer Model
    
    ENHANCEMENTS:
    - Inherits from BaseModel (soft delete)
    - Inherits from StatusTrackingMixin (is_active tracking)
    - Inherits from ApprovalWorkflowMixin (approval workflow)
    - Custom ClientManager with advanced queries
    - Database constraints for data integrity
    - Comprehensive validation
    - Financial properties (total savings, loans, ratios)
    - Helper methods
    """
    
    MARITAL_STATUS_CHOICES = [
        ('single', 'Single'),
        ('married', 'Married'),
        ('divorced', 'Divorced'),
        ('widowed', 'Widowed'),
    ]
    
    EDUCATION_CHOICES = [
        ('none', 'No Formal Education'),
        ('primary', 'Primary Education'),
        ('secondary', 'Secondary Education'),
        ('tertiary', 'Tertiary Education'),
        ('postgraduate', 'Postgraduate'),
    ]
    
    RESIDENTIAL_STATUS_CHOICES = [
        ('owned', 'Owned'),
        ('rented', 'Rented'),
        ('family', 'Family Owned'),
        ('other', 'Other'),
    ]
    
    ID_TYPE_CHOICES = [
        ('national_id', 'National ID'),
        ('passport', 'International Passport'),
        ('drivers_license', "Driver's License"),
        ('voters_card', "Voter's Card"),
    ]
    
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]
    
    GROUP_ROLE_CHOICES = [
        ('member', 'Member'),
        ('secretary', 'Secretary'),
        ('leader', 'Leader'),
    ]
    
    LOCATION_CHOICES = [
        ('rural', 'Rural'),
        ('semi_urban', 'Semi Urban'),
        ('urban', 'Urban'),
    ]
    
    ORIGIN_CHANNEL_CHOICES = [
        ('NONE', 'None'),
        ('referral', 'Referral'),
        ('walk_in', 'Walk-in'),
        ('online', 'Online'),
        ('advertisement', 'Advertisement'),
        ('group_member', 'Group Member Referral'),
        ('staff_referral', 'Staff Referral'),
        ('other', 'Other'),
    ]
    
    # ============================================
    # IDENTIFIERS
    # ============================================
    client_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        db_index=True,
        help_text="Auto-generated client ID"
    )
    external_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="External / legacy system identifier"
    )
    
    # ============================================
    # PERSONAL INFORMATION
    # ============================================
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    nickname = models.CharField(
        max_length=100,
        blank=True,
        help_text="Client's common name or nickname"
    )
    email = models.EmailField(unique=True, db_index=True, blank=True, null=True)

    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$')
    phone = models.CharField(validators=[phone_regex], max_length=17)
    alternate_phone = models.CharField(
        validators=[phone_regex],
        max_length=17,
        blank=True
    )
    
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    marital_status = models.CharField(
        max_length=20,
        choices=MARITAL_STATUS_CHOICES,
        blank=True
    )
    number_of_dependents = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    
    # ============================================
    # EDUCATION & RESIDENCE
    # ============================================
    education_level = models.CharField(
        max_length=50,
        choices=EDUCATION_CHOICES,
        blank=True
    )
    residential_status = models.CharField(
        max_length=20,
        choices=RESIDENTIAL_STATUS_CHOICES,
        blank=True
    )
    
    # ============================================
    # ADDRESS
    # ============================================
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='Nigeria')
    landmark = models.CharField(
        max_length=200,
        blank=True,
        help_text="Nearest landmark to residential address"
    )
    location = models.CharField(
        max_length=20,
        choices=LOCATION_CHOICES,
        blank=True,
        help_text="Residential area classification"
    )
    
    # ============================================
    # IDENTIFICATION
    # ============================================
    id_type = models.CharField(max_length=50, choices=ID_TYPE_CHOICES)
    id_number = models.CharField(max_length=50)
    bvn = models.CharField(max_length=11, blank=True)
    
    # ============================================
    # DOCUMENTS/IMAGES
    # ============================================
    profile_picture = CloudinaryField(
        'profile_picture',
        folder='clients/profile_pictures',
        null=True,
        blank=True,
        resource_type='image'
    )
    id_card_front = CloudinaryField(
        'id_card_front',
        folder='clients/id_cards/front',
        null=True,
        blank=True,
        resource_type='image'
    )
    id_card_back = CloudinaryField(
        'id_card_back',
        folder='clients/id_cards/back',
        null=True,
        blank=True,
        resource_type='image'
    )
    signature = CloudinaryField(
        'signature_image',
        folder='clients/signature_image',
        null=True,
        blank=True,
        resource_type='image'
    )
    
    # ============================================
    # EMPLOYMENT
    # ============================================
    occupation = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=100, blank=True)
    monthly_income = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # ============================================
    # BUSINESS INFORMATION
    # ============================================
    business_name = models.CharField(max_length=200, blank=True)
    business_type = models.CharField(max_length=100, blank=True)
    business_location = models.TextField(blank=True)
    years_in_business = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    business_type_2 = models.CharField(
        max_length=100,
        blank=True,
        help_text="Secondary business type, if any"
    )
    business_address = models.TextField(
        blank=True,
        help_text="Business premises address"
    )
    business_landmark = models.CharField(
        max_length=200,
        blank=True,
        help_text="Nearest landmark to business address"
    )
    
    # ============================================
    # BANKING DETAILS
    # ============================================
    account_number = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    
    # ============================================
    # EMERGENCY CONTACT
    # ============================================
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(
        validators=[phone_regex],
        max_length=17,
        blank=True
    )
    emergency_contact_relationship = models.CharField(
        max_length=100,
        blank=True
    )
    emergency_contact_address = models.TextField(blank=True)
    
    # ============================================
    # BRANCH & GROUP ASSIGNMENT
    # ============================================
    union_location = models.CharField(max_length=200, blank=True)
    
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name='clients'
    )
    group = models.ForeignKey(
        ClientGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )
    group_role = models.CharField(
        max_length=20,
        choices=GROUP_ROLE_CHOICES,
        default='member',
        blank=True,
        help_text="Role within assigned client group"
    )
    
    # ============================================
    # STAFF ASSIGNMENT
    # ============================================
    original_officer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originally_assigned_clients',
        limit_choices_to={'user_role__in': ['staff', 'manager']},
        help_text="Original loan officer who registered this client"
    )
    assigned_staff = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_clients',
        limit_choices_to={'user_role': 'staff'},
        help_text="Currently assigned loan officer"
    )
    
    # ============================================
    # REGISTRATION & APPROVAL
    # ============================================
    registration_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the client was physically registered (entered by staff)"
    )
    approval_date = models.DateField(
        null=True,
        blank=True,
        help_text="Official approval date entered by the approving manager/director"
    )
    activation_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the client account was activated, entered by the activating officer"
    )
    origin_channel = models.CharField(
        max_length=100,
        choices=ORIGIN_CHANNEL_CHOICES,
        default='NONE',
        blank=True,
        help_text="How this client was acquired"
    )
    registration_fee_paid = models.BooleanField(default=False, db_index=True)
    registration_fee_transaction = models.ForeignKey(
        'Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registration_fee_for'
    )
    
    # is_active, is_approved inherited from mixins
    # approval_status, approved_by, approved_at inherited from ApprovalWorkflowMixin
    
    # ============================================
    # CLOSURE
    # ============================================
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the client account was closed"
    )
    
    # ============================================
    # NOTES
    # ============================================
    notes = models.TextField(blank=True)
    
    # Custom Manager
    objects = ClientManager()
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        indexes = [
            models.Index(fields=['client_id']),
            models.Index(fields=['external_id']),
            models.Index(fields=['email']),
            models.Index(fields=['phone']),
            models.Index(fields=['branch', 'is_active']),
            models.Index(fields=['assigned_staff', 'is_active']),
            models.Index(fields=['group', 'is_active']),
            models.Index(fields=['group', 'group_role']),
            models.Index(fields=['approval_status']),
            models.Index(fields=['registration_fee_paid']),
            models.Index(fields=['date_of_birth']),
            models.Index(fields=['closed_at']),
            models.Index(fields=['origin_channel']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(monthly_income__gte=0) | models.Q(monthly_income__isnull=True),
                name='client_monthly_income_positive'
            ),
            models.CheckConstraint(
                check=models.Q(number_of_dependents__gte=0) | models.Q(number_of_dependents__isnull=True),
                name='client_dependents_positive'
            ),
            models.CheckConstraint(
                check=models.Q(years_in_business__gte=0) | models.Q(years_in_business__isnull=True),
                name='client_years_in_business_positive'
            ),
            # group_role only meaningful when group is set
            models.CheckConstraint(
                check=(
                    models.Q(group__isnull=True, group_role='') |
                    models.Q(group__isnull=True, group_role='member') |
                    models.Q(group__isnull=False)
                ),
                name='client_group_role_requires_group'
            ),
            models.UniqueConstraint(
                fields=['email'],
                condition=models.Q(deleted_at__isnull=True, email__isnull=False),
                name='unique_active_client_email'
            ),
            models.UniqueConstraint(
                fields=['client_id'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_client_id'
            ),
            # external_id unique among non-deleted, only when populated
            models.UniqueConstraint(
                fields=['external_id'],
                condition=models.Q(deleted_at__isnull=True, external_id__gt=''),
                name='unique_active_client_external_id'
            ),
        ]

    def __str__(self):
        return f"{self.client_id} - {self.get_full_name()}"
    
    def save(self, *args, **kwargs):
        # Auto-generate client_id
        if not self.client_id:
            self.client_id = self.generate_client_id()
        
        # Set original officer if not set
        if self.assigned_staff and not self.original_officer:
            self.original_officer = self.assigned_staff
        
        # Clear group_role when removed from a group
        if not self.group_id and self.group_role:
            self.group_role = ''
        
        # Stamp closed_at when client is deactivated
        if not self.is_active and self.closed_at is None:
            self.closed_at = timezone.now()
        
        # Clear closed_at if client is reactivated
        if self.is_active and self.closed_at is not None:
            self.closed_at = None
        
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_client_id():
        """Generate unique client ID in format: XXXX-XXXX-XXXXX"""
        max_attempts = 10
        for _ in range(max_attempts):
            part1 = get_random_string(4, '0123456789')
            part2 = get_random_string(4, '0123456789')
            part3 = get_random_string(5, '0123456789')
            client_id = f"{part1}-{part2}-{part3}"
            
            if not Client.objects.filter(client_id=client_id).exists():
                return client_id
        
        # Fallback to timestamp-based
        timestamp = str(int(timezone.now().timestamp()))[-13:]
        return f"{timestamp[:4]}-{timestamp[4:8]}-{timestamp[8:13]}"
    
    def clean(self):
        """Validate client data"""
        super().clean()
        
        errors = {}
        
        # Validate age
        if self.date_of_birth:
            age = self.calculate_age()
            if age < 18:
                errors['date_of_birth'] = "Client must be at least 18 years old"
            if age > 100:
                errors['date_of_birth'] = "Please verify date of birth"
        
        # Validate BVN length if provided
        if self.bvn and len(self.bvn) != 11:
            errors['bvn'] = "BVN must be exactly 11 digits"
        
        # Validate group and branch match
        if self.group and self.branch:
            if self.group.branch_id != self.branch_id:
                errors['group'] = "Client group must be from the same branch"
        
        # group_role requires a group
        if self.group_role and not self.group_id:
            errors['group_role'] = "Cannot assign a group role without a group"
        
        # Validate assigned staff and branch match
        if self.assigned_staff and self.branch:
            if self.assigned_staff.branch_id != self.branch_id:
                errors['assigned_staff'] = "Assigned staff must be from the same branch"
        
        # Validate business info consistency
        if self.business_name and not self.business_type:
            errors['business_type'] = "Business type is required when business name is provided"
        
        # business_type_2 without primary business_type is meaningless
        if self.business_type_2 and not self.business_type:
            errors['business_type_2'] = "Primary business type is required before adding a secondary type"
        
        # business_landmark / business_address consistency
        if self.business_landmark and not self.business_address:
            errors['business_landmark'] = "Business address is required when a business landmark is provided"
        
        if errors:
            raise ValidationError(errors)
    
    # ============================================
    # PROPERTIES
    # ============================================
    
    @property
    def full_name(self):
        """Get full name"""
        return f"{self.first_name} {self.last_name}"
    
    def get_full_name(self):
        """Get full name (method version)"""
        return self.full_name
    
    @property
    def display_name(self):
        """
        Display name for list views and tables.
        Shows nickname in parentheses if set, otherwise plain full name.
        """
        if self.nickname:
            return f"{self.full_name} ({self.nickname})"
        return self.full_name
    
    @property
    def age(self):
        """Calculate age from date of birth"""
        return self.calculate_age()
    
    def calculate_age(self):
        """Calculate age from date of birth"""
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None
    
    @property
    def total_savings_balance(self):
        """Total balance across all savings accounts"""
        from django.db.models import Sum
        
        total = self.savings_accounts.filter(
            status='active'
        ).aggregate(
            total=Sum('balance')
        )['total']
        
        return total or Decimal('0.00')
    
    @property
    def total_outstanding_loans(self):
        """Total outstanding balance across all active loans"""
        from django.db.models import Sum
        
        total = self.loans.filter(
            status__in=['active', 'disbursed', 'overdue']
        ).aggregate(
            total=Sum('outstanding_balance')
        )['total']
        
        return total or Decimal('0.00')
    
    @property
    def debt_to_savings_ratio(self):
        """Calculate debt-to-savings ratio"""
        savings = self.total_savings_balance
        loans = self.total_outstanding_loans
        
        if savings == 0:
            return None
        
        ratio = MoneyCalculator.safe_divide(loans, savings)
        return ratio
    
    @property
    def has_active_loans(self):
        """Check if client has any active loans"""
        return self.loans.filter(
            status__in=['active', 'disbursed', 'overdue']
        ).exists()
    
    @property
    def has_overdue_loans(self):
        """Check if client has any overdue loans"""
        return self.loans.filter(status='overdue').exists()
    
    @property
    def is_closed(self):
        """Whether this client account has been closed"""
        return not self.is_active and self.closed_at is not None
    
    # ============================================
    # HELPER METHODS
    # ============================================
    
    def can_borrow(self, amount):
        """
        Check if client can borrow - SIMPLIFIED VERSION
        
        Changes:
        - Removed tier limit checks
        - Loan product will handle amount restrictions
        - Only checks basic eligibility
        
        Args:
            amount: Requested loan amount
        
        Returns:
            tuple: (can_borrow: bool, message: str)
        """
        amount = Decimal(str(amount))
        
        # Check 1: Client must be approved
        if not self.is_approved or self.approval_status != 'approved':
            return False, "Client is not approved"
        
        # Check 2: Client must be active
        if not self.is_active:
            return False, "Client account is not active"
        
        # Check 3: Registration fee must be paid
        if not self.registration_fee_paid:
            return False, "Registration fee not paid"
        
        # Check 4: Check for overdue loans
        if self.has_overdue_loans:
            return False, "Client has overdue loans"
        
        # Check 5: Basic amount validation (must be positive)
        if amount <= 0:
            return False, "Loan amount must be greater than zero"
        
        # ✓ ALL CHECKS PASSED
        # Note: Loan product will validate amount limits
        return True, "Client is eligible to borrow"
    
    def get_active_savings_accounts(self):
        """Get all active savings accounts"""
        return self.savings_accounts.filter(status='active')
    
    def get_active_loans(self):
        """Get all active loans"""
        return self.loans.filter(status__in=['active', 'disbursed', 'overdue'])
    
    def get_loan_history_summary(self):
        """Get summary of loan history"""
        from django.db.models import Count, Sum
        
        summary = self.loans.aggregate(
            total_loans=Count('id'),
            total_borrowed=Sum('principal_amount'),
            total_repaid=Sum('amount_paid'),
            total_outstanding=Sum('outstanding_balance'),
        )
        
        completed_loans = self.loans.filter(status='completed').count()
        active_loans = self.loans.filter(status__in=['active', 'disbursed']).count()
        overdue_loans = self.loans.filter(status='overdue').count()
        
        return {
            **summary,
            'completed_loans': completed_loans,
            'active_loans': active_loans,
            'overdue_loans': overdue_loans,
        }
    
    def get_profile_picture_url(self):
        """Get profile picture URL safely"""
        if self.profile_picture:
            try:
                return self.profile_picture.url
            except:
                return None
        return None



# =============================================================================
# FROM: product_models.py
# =============================================================================

# =============================================================================
# =============================================================================
MONTHLY_INTEREST_RATE = Decimal('0.035')
LOAN_FORM_FEE = Decimal('200.00')


# =============================================================================
# CENTRALIZED LOAN TYPE CHOICES
# =============================================================================

LOAN_TYPE_CHOICES = [
    ('regular', 'Regular Loan'),
    ('special', 'Special Loan'),
    ('med',     'Med Loan'),
    ('asset',   'Asset Loan'),
    ('thrift',  'Thrift Loan'),
    ('midterm', 'Midterm Loan'),
    ('golden',  'Golden Loan'),
]

REPAYMENT_FREQUENCY_MAP = {
    'regular': 'weekly',
    'special': 'monthly',
    'med':     'monthly',
    'asset':   'monthly',
    'thrift':  'daily',
    'midterm': 'weekly',
    'golden':  'monthly',
}


# =============================================================================
# LOAN PRODUCT MODEL (ENHANCED)
# =============================================================================

class LoanProduct(BaseModel, StatusTrackingMixin):
    """
    Loan Product Configuration
    
    ENHANCEMENTS:
    - Inherits from BaseModel (soft delete)
    - Inherits from StatusTrackingMixin (is_active)
    - Database constraints
    - Comprehensive validation
    - Helper methods for eligibility checking
    - Fee calculation methods
    """
    
    FEE_CALCULATION_CHOICES = [
        ('percentage', 'Percentage of Principal'),
        ('flat', 'Flat Amount'),
    ]
    
    INTEREST_METHOD_CHOICES = [
        ('flat', 'Flat Rate'),
        ('reducing_balance', 'Reducing Balance'),
    ]
    
    # =========================================================================
    # BASIC INFO
    # =========================================================================
    
    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Product code (e.g., THR-STD, BUS-001)"
    )
    
    name = models.CharField(
        max_length=200,
        help_text="Product name (e.g., 'Thrift Loan - Standard')"
    )
    
    description = models.TextField(blank=True)
    
    loan_type = models.CharField(
        max_length=20,
        choices=LOAN_TYPE_CHOICES,
        db_index=True,
        help_text="Type of loan product"
    )
    
    gl_code = models.CharField(
        max_length=10,
        blank=True,
        help_text="GL code for accounting"
    )
    
    # =========================================================================
    # INTEREST RATES
    # =========================================================================
    
    monthly_interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=MONTHLY_INTEREST_RATE,
        validators=[MinValueValidator(Decimal('0.0001'))],
        help_text="Monthly interest rate (e.g., 0.0350 = 3.5%)"
    )
    
    annual_interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('42.00'),
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Annual interest rate"
    )
    
    interest_calculation_method = models.CharField(
        max_length=20,
        choices=INTEREST_METHOD_CHOICES,
        default='flat'
    )
    
    # =========================================================================
    # FEE STRUCTURE - DETAILED BREAKDOWN
    # =========================================================================
    
    # Risk Premium Fee
    risk_premium_enabled = models.BooleanField(default=True)
    risk_premium_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0150'),
        validators=[MinValueValidator(Decimal('0.0000'))]
    )
    risk_premium_calculation = models.CharField(
        max_length=20,
        choices=FEE_CALCULATION_CHOICES,
        default='percentage'
    )
    
    # RP Income Fee
    rp_income_enabled = models.BooleanField(default=True)
    rp_income_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0150'),
        validators=[MinValueValidator(Decimal('0.0000'))]
    )
    rp_income_calculation = models.CharField(
        max_length=20,
        choices=FEE_CALCULATION_CHOICES,
        default='percentage'
    )
    
    # Tech Fee
    tech_fee_enabled = models.BooleanField(default=True)
    tech_fee_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0050'),
        validators=[MinValueValidator(Decimal('0.0000'))]
    )
    tech_fee_calculation = models.CharField(
        max_length=20,
        choices=FEE_CALCULATION_CHOICES,
        default='percentage'
    )
    
    # Loan Form Fee
    loan_form_fee_enabled = models.BooleanField(default=True)
    loan_form_fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=LOAN_FORM_FEE,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # =========================================================================
    # LOAN LIMITS
    # =========================================================================
    
    min_principal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('10000.00'),
        validators=[MinValueValidator(Decimal('1.00'))]
    )
    
    max_principal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('500000.00'),
        validators=[MinValueValidator(Decimal('1.00'))]
    )
    
    min_duration_months = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1)]
    )
    
    max_duration_months = models.IntegerField(
        default=24,
        validators=[MinValueValidator(1)]
    )
    
    # =========================================================================
    # REPAYMENT CONFIGURATION
    # =========================================================================

    repayment_frequency = models.CharField(
        max_length=20,
        choices=REPAYMENT_FREQUENCY_CHOICES,
        default='monthly',
        help_text="How often borrowers make installment payments (does not affect interest calculation)",
    )
    allow_early_repayment = models.BooleanField(default=True)
    early_repayment_penalty_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0000'),
        validators=[MinValueValidator(Decimal('0.0000'))]
    )
    grace_period_days = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    
    # =========================================================================
    # REQUIREMENTS
    # =========================================================================
    
    requires_collateral = models.BooleanField(default=False)
    min_collateral_value_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    required_guarantors = models.IntegerField(
        default=2,
        validators=[MinValueValidator(0)]
    )
    requires_insurance = models.BooleanField(default=True)
    
    # =========================================================================
    # ELIGIBILITY
    # =========================================================================
    
    min_client_age = models.IntegerField(
        default=18,
        validators=[MinValueValidator(18)]
    )
    max_client_age = models.IntegerField(
        default=65,
        validators=[MinValueValidator(18)]
    )
    requires_business = models.BooleanField(default=False)
    min_membership_months = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    
    # =========================================================================
    # APPROVAL WORKFLOW
    # =========================================================================
    
    auto_approve_under_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    requires_director_approval = models.BooleanField(default=False)
    
    # =========================================================================
    # DISPLAY
    # =========================================================================
    
    is_featured = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    
    # =========================================================================
    # AUDIT
    # =========================================================================
    
    created_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_products_created'
    )
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = "Loan Product"
        verbose_name_plural = "Loan Products"
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
            models.Index(fields=['loan_type', 'is_active']),
            models.Index(fields=['display_order']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(min_principal_amount__lte=models.F('max_principal_amount')),
                name='loanproduct_min_max_principal_valid'
            ),
            models.CheckConstraint(
                check=models.Q(min_duration_months__lte=models.F('max_duration_months')),
                name='loanproduct_min_max_duration_valid'
            ),
            models.CheckConstraint(
                check=models.Q(monthly_interest_rate__gte=0),
                name='loanproduct_interest_rate_positive'
            ),
            models.CheckConstraint(
                check=models.Q(min_client_age__lte=models.F('max_client_age')),
                name='loanproduct_min_max_age_valid'
            ),
            models.UniqueConstraint(
                fields=['code'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_loanproduct_code'
            ),
        ]
    
    def __str__(self):
        return f"{self.code} - {self.name}"
    
    def clean(self):
        """Validate product configuration"""
        super().clean()
        
        errors = {}
        
        # Validate principal amounts
        if self.min_principal_amount > self.max_principal_amount:
            errors['max_principal_amount'] = "Maximum amount must be greater than minimum"
        
        # Validate duration
        if self.min_duration_months > self.max_duration_months:
            errors['max_duration_months'] = "Maximum duration must be greater than minimum"
        
        # Validate ages
        if self.min_client_age > self.max_client_age:
            errors['max_client_age'] = "Maximum age must be greater than minimum"
        
        # Validate code format
        if self.code and not self.code.replace('-', '').replace('_', '').isalnum():
            errors['code'] = "Product code must be alphanumeric"
        
        if errors:
            raise ValidationError(errors)
    
    @property
    def monthly_interest_rate_pct(self):
        """Return monthly interest rate as a percentage value (e.g. 0.035 → 3.50)."""
        return self.monthly_interest_rate * Decimal('100')

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def calculate_fees(self, principal_amount):
        """
        Calculate all fees for given principal amount
        
        Returns dict with fee breakdown
        """
        principal = Decimal(str(principal_amount))
        fees = {}
        
        # Risk Premium
        if self.risk_premium_enabled:
            if self.risk_premium_calculation == 'percentage':
                fees['risk_premium_fee'] = MoneyCalculator.calculate_percentage(
                    principal, self.risk_premium_rate
                )
            else:
                fees['risk_premium_fee'] = MoneyCalculator.round_money(self.risk_premium_rate)
        else:
            fees['risk_premium_fee'] = Decimal('0.00')
        
        # RP Income
        if self.rp_income_enabled:
            if self.rp_income_calculation == 'percentage':
                fees['rp_income_fee'] = MoneyCalculator.calculate_percentage(
                    principal, self.rp_income_rate
                )
            else:
                fees['rp_income_fee'] = MoneyCalculator.round_money(self.rp_income_rate)
        else:
            fees['rp_income_fee'] = Decimal('0.00')
        
        # Tech Fee
        if self.tech_fee_enabled:
            if self.tech_fee_calculation == 'percentage':
                fees['tech_fee'] = MoneyCalculator.calculate_percentage(
                    principal, self.tech_fee_rate
                )
            else:
                fees['tech_fee'] = MoneyCalculator.round_money(self.tech_fee_rate)
        else:
            fees['tech_fee'] = Decimal('0.00')
        
        # Loan Form Fee
        if self.loan_form_fee_enabled:
            fees['loan_form_fee'] = self.loan_form_fee_amount
        else:
            fees['loan_form_fee'] = Decimal('0.00')
        
        # Total
        fees['total_upfront_fees'] = MoneyCalculator.sum_amounts(
            fees['risk_premium_fee'],
            fees['rp_income_fee'],
            fees['tech_fee'],
            fees['loan_form_fee']
        )
        
        return fees
    
    def is_amount_valid(self, amount):
        """Check if amount is within product limits"""
        amount = Decimal(str(amount))
        return self.min_principal_amount <= amount <= self.max_principal_amount
    
    def is_duration_valid(self, months):
        """Check if duration is within product limits"""
        return self.min_duration_months <= months <= self.max_duration_months
    
    def check_eligibility(self, client):
        """
        Check if client is eligible for this product
        
        Returns: (is_eligible, list_of_reasons)
        """
        reasons = []
        
        # Age check
        if hasattr(client, 'age') and client.age:
            if client.age < self.min_client_age:
                reasons.append(f"Client must be at least {self.min_client_age} years old")
            if client.age > self.max_client_age:
                reasons.append(f"Client must be under {self.max_client_age} years old")
        
        # Membership duration check
        if self.min_membership_months > 0 and hasattr(client, 'created_at'):
            if client.created_at:
                months_member = (timezone.now().date() - client.created_at.date()).days // 30
                if months_member < self.min_membership_months:
                    reasons.append(
                        f"Must be member for at least {self.min_membership_months} months"
                    )
        
        # Business requirement check
        if self.requires_business:
            has_business = bool(
                hasattr(client, 'business_name') and
                hasattr(client, 'business_type') and
                client.business_name and
                client.business_type
            )
            if not has_business:
                reasons.append("Business registration required for this product")
        
        # Approval status check
        if hasattr(client, 'is_approved') and not client.is_approved:
            reasons.append("Client must be approved")
        
        # Registration fee check
        if hasattr(client, 'registration_fee_paid') and not client.registration_fee_paid:
            reasons.append("Registration fee must be paid")
        
        return len(reasons) == 0, reasons
    
    def get_approval_level_required(self, amount):
        """Determine approval level required for given amount"""
        amount = Decimal(str(amount))
        
        if self.auto_approve_under_amount > 0 and amount < self.auto_approve_under_amount:
            return 'auto'
        elif self.requires_director_approval or amount > Decimal('1000000.00'):
            return 'director'
        else:
            return 'manager'
    
    def get_fee_summary_text(self):
        """Get human-readable fee summary"""
        fees_text = []
        
        if self.risk_premium_enabled:
            if self.risk_premium_calculation == 'percentage':
                fees_text.append(f"Risk Premium: {float(self.risk_premium_rate)*100:.2f}%")
            else:
                fees_text.append(f"Risk Premium: ₦{self.risk_premium_rate:,.2f}")
        
        if self.rp_income_enabled:
            if self.rp_income_calculation == 'percentage':
                fees_text.append(f"RP Income: {float(self.rp_income_rate)*100:.2f}%")
            else:
                fees_text.append(f"RP Income: ₦{self.rp_income_rate:,.2f}")
        
        if self.tech_fee_enabled:
            if self.tech_fee_calculation == 'percentage':
                fees_text.append(f"Tech Fee: {float(self.tech_fee_rate)*100:.2f}%")
            else:
                fees_text.append(f"Tech Fee: ₦{self.tech_fee_rate:,.2f}")
        
        if self.loan_form_fee_enabled:
            fees_text.append(f"Form Fee: ₦{self.loan_form_fee_amount:,.2f}")
        
        return ", ".join(fees_text) if fees_text else "No fees"




# =============================================================================
# SAVINGS PRODUCT MODEL
# =============================================================================




# =============================================================================
# SAVINGS PRODUCT MODEL - SINGLE SOURCE OF TRUTH
# =============================================================================

class SavingsProduct(BaseModel, StatusTrackingMixin):
    """
    Savings Product Configuration - SINGLE SOURCE OF TRUTH
    
    This model defines ALL rules for savings accounts:
    - Account type (regular, fixed, target, children)
    - Interest rates and calculation methods
    - Balance requirements and limits
    - Transaction limits
    - Fees and penalties
    
    When a SavingsAccount is created, it inherits ALL behavior from its product.
    """
    
    # =========================================================================
    # BASIC INFO
    # =========================================================================
    
    name = models.CharField(
        max_length=100, 
        unique=True,
        help_text="Product name (e.g., 'Basic Savings Account', 'Fixed Deposit 6M')"
    )
    code = models.CharField(
        max_length=20, 
        unique=True, 
        db_index=True,
        help_text="Unique product code (e.g., 'REG-SAV', 'FD-6M')"
    )
    description = models.TextField(
        blank=True,
        help_text="Product description and features"
    )
    gl_code = models.CharField(
        max_length=10, 
        blank=True,
        help_text="General Ledger code for accounting"
    )

    # =========================================================================
    # PRODUCT TYPE - SINGLE SOURCE OF TRUTH FOR ACCOUNT BEHAVIOR
    # =========================================================================
    
    PRODUCT_TYPE_CHOICES = [
        ('regular', 'Regular Savings'),
        ('fixed', 'Fixed Deposit'),
        ('target', 'Voluntary Savings'),
        ('children', 'Children Savings'),
        ('thrift', 'Thrift Savings'),
    ]
    
    product_type = models.CharField(
        max_length=20,
        choices=PRODUCT_TYPE_CHOICES,
        default='regular',
        db_index=True,
        help_text='Type of savings product - determines ALL account behavior'
    )
    
    # =========================================================================
    # INTEREST CONFIGURATION
    # =========================================================================
    
    interest_rate_annual = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('5.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Annual interest rate percentage (e.g., 5.00 for 5%)"
    )
    
    INTEREST_METHOD_CHOICES = [
        ('simple', 'Simple Interest'),
        ('compound', 'Compound Interest'),
    ]
    
    interest_calculation_method = models.CharField(
        max_length=20,
        choices=INTEREST_METHOD_CHOICES,
        default='simple',
        help_text="How interest is calculated"
    )
    
    INTEREST_FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annually', 'Annually'),
        ('maturity', 'At Maturity'),
    ]
    
    interest_payment_frequency = models.CharField(
        max_length=20,
        choices=INTEREST_FREQUENCY_CHOICES,
        default='monthly',
        help_text="How often interest is paid out"
    )
    
    # =========================================================================
    # BALANCE REQUIREMENTS
    # =========================================================================
    
    minimum_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum balance that must be maintained"
    )
    
    minimum_opening_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum balance required to open account"
    )
    
    maximum_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Maximum balance allowed (null = no limit)"
    )
    
    # =========================================================================
    # TRANSACTION LIMITS
    # =========================================================================
    
    min_deposit_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('100.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum amount per deposit"
    )
    
    min_withdrawal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('100.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum amount per withdrawal"
    )
    
    max_withdrawal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Maximum amount per withdrawal (null = no limit)"
    )
    
    daily_withdrawal_limit = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Total daily withdrawal limit (null = no limit)"
    )
    
    # =========================================================================
    # FIXED DEPOSIT SETTINGS (only applicable when product_type='fixed')
    # =========================================================================
    
    fixed_term_months = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Fixed term in months (required for fixed deposit products)"
    )
    
    allows_withdrawal_before_maturity = models.BooleanField(
        default=True,
        help_text="Can customers withdraw before maturity date?"
    )
    
    early_withdrawal_penalty_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Penalty rate (%) for early withdrawal from fixed deposits"
    )
    
    # =========================================================================
    # FEES
    # =========================================================================
    
    monthly_maintenance_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Monthly account maintenance fee"
    )
    
    withdrawal_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Fee per withdrawal transaction"
    )
    
    below_minimum_balance_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Fee charged when balance falls below minimum"
    )
    
    # =========================================================================
    # DISPLAY & ORDERING
    # =========================================================================
    
    is_featured = models.BooleanField(
        default=False,
        help_text="Display prominently on website/app"
    )
    
    display_order = models.IntegerField(
        default=0,
        help_text="Order for displaying products (lower = first)"
    )
    
    # =========================================================================
    # AUDIT
    # =========================================================================
    
    created_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='savings_products_created'
    )
    
    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = "Savings Product"
        verbose_name_plural = "Savings Products"
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['product_type']),
            models.Index(fields=['is_active']),
            models.Index(fields=['display_order']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(minimum_opening_balance__gte=0),
                name='savingsproduct_min_opening_balance_positive'
            ),
            models.CheckConstraint(
                check=models.Q(minimum_balance__gte=0),
                name='savingsproduct_min_balance_positive'
            ),
            models.CheckConstraint(
                check=models.Q(interest_rate_annual__gte=0),
                name='savingsproduct_interest_rate_positive'
            ),
            models.UniqueConstraint(
                fields=['code'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_savingsproduct_code'
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"
    
    def clean(self):
        """Validate product configuration"""
        super().clean()
        
        errors = {}
        
        # Validate code format
        if self.code and not self.code.replace('-', '').replace('_', '').isalnum():
            errors['code'] = "Product code must be alphanumeric (hyphens and underscores allowed)"
        
        # Validate fixed deposit settings
        if self.product_type == 'fixed':
            if not self.fixed_term_months:
                errors['fixed_term_months'] = "Fixed term is required for fixed deposit products"
            if self.fixed_term_months and self.fixed_term_months < 1:
                errors['fixed_term_months'] = "Fixed term must be at least 1 month"
        
        # Validate balances
        if self.maximum_balance and self.minimum_balance > self.maximum_balance:
            errors['maximum_balance'] = "Maximum balance must be greater than minimum balance"
        
        # Validate minimum opening balance
        if self.minimum_opening_balance < self.minimum_balance:
            errors['minimum_opening_balance'] = "Minimum opening balance should be at least the minimum balance"
        
        if errors:
            raise ValidationError(errors)
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    @property
    def is_fixed_deposit(self):
        """Check if this is a fixed deposit product"""
        return self.product_type == 'fixed'
    
    @property
    def is_regular(self):
        """Check if this is a regular savings product"""
        return self.product_type == 'regular'
    
    @property
    def is_target(self):
        """Check if this is a voluntary savings product"""
        return self.product_type == 'target'
    
    @property
    def is_children(self):
        """Check if this is a children savings product"""
        return self.product_type == 'children'

    @property
    def is_thrift(self):
        """Check if this is a thrift savings product"""
        return self.product_type == 'thrift'
    
    def calculate_interest(self, balance, months):
        """
        Calculate interest for a given balance and duration
        
        Args:
            balance (Decimal): The balance amount
            months (int): Duration in months
        
        Returns:
            Decimal: Interest amount
        """
        if self.interest_rate_annual <= 0:
            return Decimal('0.00')
        
        balance = Decimal(str(balance))
        annual_rate = Decimal(str(self.interest_rate_annual))
        
        # Convert percentage to decimal
        rate_decimal = annual_rate / Decimal('100')
        
        # Calculate monthly interest
        monthly_rate = rate_decimal / Decimal('12')
        
        # Simple interest: balance * monthly_rate * months
        interest = balance * monthly_rate * Decimal(str(months))
        
        return interest.quantize(Decimal('0.01'))

    def is_withdrawal_allowed(self, account):
        """
        Check if withdrawal is allowed for an account with this product
        
        Args:
            account: SavingsAccount instance
            
        Returns:
            tuple: (bool, str) - (allowed, message)
        """
        if self.product_type == 'fixed' and account.maturity_date:
            if timezone.now().date() < account.maturity_date:
                if not self.allows_withdrawal_before_maturity:
                    days_remaining = (account.maturity_date - timezone.now().date()).days
                    return False, f"Withdrawals not allowed before maturity ({days_remaining} days remaining)"
                else:
                    return True, f"Early withdrawal penalty of {self.early_withdrawal_penalty_rate}% applies"
        
        return True, "Withdrawal allowed"
    
    def calculate_early_withdrawal_penalty(self, withdrawal_amount):
        """
        Calculate penalty for early withdrawal
        
        Args:
            withdrawal_amount (Decimal): Amount being withdrawn
            
        Returns:
            Decimal: Penalty amount
        """
        if not self.early_withdrawal_penalty_rate:
            return Decimal('0.00')
        
        withdrawal_amount = Decimal(str(withdrawal_amount))
        penalty_rate = Decimal(str(self.early_withdrawal_penalty_rate))
        
        penalty = withdrawal_amount * (penalty_rate / Decimal('100'))
        
        return penalty.quantize(Decimal('0.01'))


# =============================================================================
# SAVINGS ACCOUNT MODEL - CORRECTED (NO account_type FIELD)
# =============================================================================

class SavingsAccount(BaseModel, ApprovalWorkflowMixin):
    """
    Individual Savings Account for a Client
    
    CRITICAL CHANGE: account_type field REMOVED
    - All account type information comes from savings_product.product_type
    - SavingsProduct is the SINGLE SOURCE OF TRUTH
    - This eliminates redundancy and ensures consistency
    
    The account inherits ALL behavior from its SavingsProduct:
    - Account type (regular, fixed, target, children)
    - Interest rates
    - Transaction limits
    - Fees and penalties
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('closed', 'Closed'),
        ('matured', 'Matured'),
    ]
    
    # =========================================================================
    # IDENTIFIERS
    # =========================================================================
    
    account_number = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Auto-generated unique account number"
    )
    
    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    
    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='savings_accounts',
        help_text="Account owner"
    )
    
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='savings_accounts',
        help_text="Branch where account was opened"
    )
    
    # =========================================================================
    # PRODUCT CONFIGURATION - SINGLE SOURCE OF TRUTH
    # =========================================================================
    
    savings_product = models.ForeignKey(
        'SavingsProduct',
        on_delete=models.PROTECT,
        related_name='accounts',
        help_text='Savings product - determines ALL account behavior (type, interest, limits, fees)'
    )
    
    # NOTE: account_type field REMOVED - use savings_product.product_type instead
    
    # =========================================================================
    # ACCOUNT STATUS
    # =========================================================================
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        help_text="Current account status"
    )
    
    is_auto_created = models.BooleanField(
        default=False,
        help_text="Was this account auto-created during client activation?"
    )
    
    # =========================================================================
    # FIXED DEPOSIT SETTINGS (populated from product at creation)
    # =========================================================================
    
    fixed_deposit_term = models.IntegerField(
        null=True,
        blank=True,
        help_text="Term in months for fixed deposits (copied from product at creation)"
    )
    
    maturity_date = models.DateField(
        null=True,
        blank=True,
        help_text="Maturity date for fixed deposits (calculated at creation)"
    )
    
    # =========================================================================
    # BALANCE TRACKING
    # =========================================================================
    
    balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Current account balance"
    )
    
    minimum_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Minimum balance to maintain (copied from product at creation)"
    )
    
    # =========================================================================
    # INTEREST TRACKING
    # =========================================================================
    
    interest_earned = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Total interest earned over lifetime"
    )
    
    last_interest_date = models.DateField(
        null=True, 
        blank=True,
        help_text="Last date interest was calculated/posted"
    )
    
    # =========================================================================
    # DATES
    # =========================================================================
    
    date_opened = models.DateField(
        default=date.today,
        help_text="Date account was opened (editable — defaults to today)"
    )

    approval_date = models.DateField(
        null=True,
        blank=True,
        help_text="Official date the account was approved (entered by the approver)"
    )
    
    date_closed = models.DateField(
        null=True, 
        blank=True,
        help_text="Date account was closed"
    )
    
    closed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_savings_accounts',
        help_text="User who closed the account"
    )
    
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when account was closed"
    )
    
    # =========================================================================
    # NOTES
    # =========================================================================
    
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about the account"
    )
    
    # =========================================================================
    # CUSTOM MANAGER
    # =========================================================================
    
    objects = SavingsAccountManager()
    
    # =========================================================================
    # META
    # =========================================================================
    
    class Meta:
        ordering = ['-date_opened']
        verbose_name = "Savings Account"
        verbose_name_plural = "Savings Accounts"
        indexes = [
            models.Index(fields=['account_number']),
            models.Index(fields=['client', 'status']),
            models.Index(fields=['branch', 'status']),
            models.Index(fields=['maturity_date']),
            models.Index(fields=['status', '-date_opened']),
            models.Index(fields=['savings_product', 'status']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=0),
                name='savingsaccount_balance_positive'
            ),
            models.CheckConstraint(
                check=models.Q(minimum_balance__gte=0),
                name='savingsaccount_min_balance_positive'
            ),
            models.CheckConstraint(
                check=models.Q(interest_earned__gte=0),
                name='savingsaccount_interest_positive'
            ),
            models.UniqueConstraint(
                fields=['account_number'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_account_number'
            ),
        ]

    def __str__(self):
        product_name = self.savings_product.name if self.savings_product else 'Unknown'
        return f"{self.account_number} - {product_name}"

    @property
    def current_balance(self):
        """Alias for balance — used by templates."""
        return self.balance

    @property
    def available_balance(self):
        """Balance available for withdrawal (balance minus minimum balance requirement)."""
        available = self.balance - self.minimum_balance
        return available if available > Decimal('0.00') else Decimal('0.00')

    def save(self, *args, **kwargs):
        """Override save to auto-generate account number and set defaults"""
        if not self.account_number:
            self.account_number = self.generate_account_number()
        
        # Set minimum balance from product if not set
        if self.savings_product and not self.minimum_balance:
            self.minimum_balance = self.savings_product.minimum_balance
        
        # Set fixed deposit term from product if applicable
        if self.savings_product and self.savings_product.product_type == 'fixed':
            if not self.fixed_deposit_term and self.savings_product.fixed_term_months:
                self.fixed_deposit_term = self.savings_product.fixed_term_months
        
        super().save(*args, **kwargs)

    @staticmethod
    def generate_account_number():
        """Generate unique account number: YYMMDDHHMMSSRRRR (14 digits)"""
        timestamp = timezone.now().strftime('%y%m%d%H%M%S')
        random_suffix = get_random_string(4, '0123456789')
        account_number = f"{timestamp}{random_suffix}"
        
        while SavingsAccount.objects.filter(account_number=account_number).exists():
            random_suffix = get_random_string(4, '0123456789')
            account_number = f"{timestamp}{random_suffix}"
        
        return account_number
    
    def clean(self):
        """Validate account data"""
        super().clean()
        
        errors = {}
        
        # Validate savings_product is set
        if not self.savings_product:
            errors['savings_product'] = "Savings product is required"
        
        # Validate fixed deposit settings
        if self.savings_product and self.savings_product.product_type == 'fixed':
            if not self.fixed_deposit_term:
                errors['fixed_deposit_term'] = "Fixed deposit term is required for fixed deposit products"
        
        # Validate client and branch match
        if self.client and self.branch:
            if self.client.branch_id != self.branch_id:
                errors['branch'] = "Account branch must match client's branch"
        
        if errors:
            raise ValidationError(errors)
    
    # =========================================================================
    # PROPERTIES - ACCOUNT TYPE FROM PRODUCT (SINGLE SOURCE OF TRUTH)
    # =========================================================================
    
    @property
    def account_type(self):
        """
        Get account type from savings product.
        
        Returns:
            str: Account type ('regular', 'fixed', 'target', 'children')
        """
        if self.savings_product:
            return self.savings_product.product_type
        return 'regular'  # Default fallback
    
    def get_account_type_display(self):
        """
        Get human-readable account type.
        
        Returns:
            str: Human-readable account type (e.g., "Fixed Deposit")
        """
        if self.savings_product:
            return self.savings_product.get_product_type_display()
        return 'Regular Savings'
    
    @property
    def account_type_display(self):
        """Alias for get_account_type_display"""
        return self.get_account_type_display()
    
    @property
    def is_fixed_deposit(self):
        """Check if this is a fixed deposit account"""
        return self.savings_product and self.savings_product.product_type == 'fixed'
    
    @property
    def is_regular(self):
        """Check if this is a regular savings account"""
        return self.savings_product and self.savings_product.product_type == 'regular'
    
    @property
    def is_target(self):
        """Check if this is a voluntary savings account"""
        return self.savings_product and self.savings_product.product_type == 'target'
    
    @property
    def is_children(self):
        """Check if this is a children savings account"""
        return self.savings_product and self.savings_product.product_type == 'children'
    
    @property
    def is_matured(self):
        """Check if fixed deposit has matured"""
        if self.is_fixed_deposit and self.maturity_date:
            return timezone.now().date() >= self.maturity_date
        return False
    
    @property
    def days_to_maturity(self):
        """Days until maturity for fixed deposits"""
        if self.is_fixed_deposit and self.maturity_date:
            delta = self.maturity_date - timezone.now().date()
            return max(delta.days, 0)
        return None
    
    @property
    def available_balance(self):
        """Calculate available balance (balance - minimum_balance)"""
        return max(self.balance - self.minimum_balance, Decimal('0.00'))
    
    # =========================================================================
    # TRANSACTION METHODS (THREAD-SAFE WITH ROW LOCKING)
    # =========================================================================
    
    @db_transaction.atomic
    def deposit(self, amount, processed_by, description='', transaction_date=None):
        """
        Deposit money into account - THREAD-SAFE VERSION

        Args:
            amount (Decimal): Amount to deposit
            processed_by (User): User processing the transaction
            description (str): Transaction description
            transaction_date: Date of the deposit (date or datetime). Defaults to now.

        Returns:
            Transaction: Created transaction object

        Raises:
            ValueError: If deposit validation fails
        """
        from core.models import Transaction
        from django.db.models import F
        import datetime as _dt
        
        amount = Decimal(str(amount))
        
        # Validation
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        
        if self.status not in ['active', 'pending']:
            raise ValueError(f"Cannot deposit to {self.get_status_display()} account")
        
        # Validate against product limits
        if self.savings_product:
            if amount < self.savings_product.min_deposit_amount:
                raise ValueError(
                    f"Minimum deposit amount is ₦{self.savings_product.min_deposit_amount:,.2f}"
                )
        
        logger.info(
            f"Deposit initiated: Account={self.account_number}, "
            f"Amount=₦{amount}, ProcessedBy={processed_by.email}"
        )
        
        # CRITICAL: Lock the row
        account = SavingsAccount.objects.select_for_update().get(pk=self.pk)
        
        old_balance = account.balance
        
        # Update balance atomically
        account.balance = F('balance') + amount
        account.save(update_fields=['balance', 'updated_at'])
        
        # Refresh to get actual value
        account.refresh_from_db()
        
        # Verify update
        expected_balance = old_balance + amount
        if abs(account.balance - expected_balance) > Decimal('0.01'):
            logger.error(
                f"Balance mismatch after deposit! "
                f"Expected: ₦{expected_balance}, Actual: ₦{account.balance}, "
                f"Account: {account.account_number}"
            )
            raise ValueError("Balance update verification failed")
        
        # Resolve transaction datetime (backdate if payment_date supplied)
        txn_dt = transaction_date if transaction_date is not None else timezone.now()
        if isinstance(txn_dt, _dt.date) and not isinstance(txn_dt, _dt.datetime):
            txn_dt = timezone.make_aware(_dt.datetime.combine(txn_dt, _dt.time.min))

        # Create transaction record
        txn = Transaction.objects.create(
            transaction_type='deposit',
            amount=amount,
            client=account.client,
            savings_account=account,
            branch=account.branch,
            balance_before=old_balance,
            balance_after=account.balance,
            processed_by=processed_by,
            description=description or f"Deposit to {account.account_number}",
            status='completed',
            transaction_date=txn_dt,
        )

        logger.info(
            f"Deposit completed: Account={account.account_number}, "
            f"Amount=₦{amount}, OldBalance=₦{old_balance}, "
            f"NewBalance=₦{account.balance}, TxnRef={txn.transaction_ref}"
        )

        # Create journal entry (Dr Cash, Cr Savings Liability)
        try:
            post_savings_deposit_journal(
                savings_account=account,
                amount=amount,
                processed_by=processed_by,
                transaction_obj=txn
            )
            logger.info(f"Journal entry created for savings deposit: {txn.transaction_ref}")
        except Exception as e:
            logger.error(f"Failed to create journal entry for deposit {txn.transaction_ref}: {str(e)}")
            # Continue even if journal entry fails - can be fixed later

        return txn
    
    @db_transaction.atomic
    def withdraw(self, amount, processed_by, description='', transaction_date=None):
        """
        Withdraw money from account - THREAD-SAFE VERSION

        Args:
            amount (Decimal): Amount to withdraw
            processed_by (User): User processing the transaction
            description (str): Transaction description
            transaction_date: Date of the withdrawal (date or datetime). Defaults to now.

        Returns:
            Transaction: Created transaction object

        Raises:
            ValueError: If withdrawal validation fails
        """
        from core.models import Transaction
        from django.db.models import F
        import datetime as _dt
        
        amount = Decimal(str(amount))
        
        # Basic validation
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        
        if self.status != 'active':
            raise ValueError(f"Cannot withdraw from {self.get_status_display()} account")
        
        logger.info(
            f"Withdrawal initiated: Account={self.account_number}, "
            f"Amount=₦{amount}, ProcessedBy={processed_by.email}"
        )
        
        # CRITICAL: Lock the row and get fresh data
        account = SavingsAccount.objects.select_for_update().get(pk=self.pk)
        
        # Re-validate with fresh balance
        can_withdraw, message = account.can_withdraw(amount)
        if not can_withdraw:
            logger.warning(
                f"Withdrawal rejected: Account={account.account_number}, "
                f"Amount=₦{amount}, Reason={message}"
            )
            raise ValueError(message)
        
        old_balance = account.balance
        
        # Update balance atomically
        account.balance = F('balance') - amount
        account.save(update_fields=['balance', 'updated_at'])
        
        # Refresh to get actual value
        account.refresh_from_db()
        
        # Verify update
        expected_balance = old_balance - amount
        if abs(account.balance - expected_balance) > Decimal('0.01'):
            logger.error(
                f"Balance mismatch after withdrawal! "
                f"Expected: ₦{expected_balance}, Actual: ₦{account.balance}, "
                f"Account: {account.account_number}"
            )
            raise ValueError("Balance update verification failed")
        
        # Resolve transaction datetime (backdate if withdrawal_date supplied)
        txn_dt = transaction_date if transaction_date is not None else timezone.now()
        if isinstance(txn_dt, _dt.date) and not isinstance(txn_dt, _dt.datetime):
            txn_dt = timezone.make_aware(_dt.datetime.combine(txn_dt, _dt.time.min))

        # Create transaction record
        txn = Transaction.objects.create(
            transaction_type='withdrawal',
            amount=amount,
            client=account.client,
            savings_account=account,
            branch=account.branch,
            balance_before=old_balance,
            balance_after=account.balance,
            processed_by=processed_by,
            description=description or f"Withdrawal from {account.account_number}",
            status='completed',
            transaction_date=txn_dt,
        )

        logger.info(
            f"Withdrawal completed: Account={account.account_number}, "
            f"Amount=₦{amount}, OldBalance=₦{old_balance}, "
            f"NewBalance=₦{account.balance}, TxnRef={txn.transaction_ref}"
        )

        # Create journal entry (Dr Savings Liability, Cr Cash)
        try:
            post_savings_withdrawal_journal(
                savings_account=account,
                amount=amount,
                processed_by=processed_by,
                transaction_obj=txn
            )
            logger.info(f"Journal entry created for savings withdrawal: {txn.transaction_ref}")
        except Exception as e:
            logger.error(f"Failed to create journal entry for withdrawal {txn.transaction_ref}: {str(e)}")
            # Continue even if journal entry fails - can be fixed later

        return txn
    
    def can_withdraw(self, amount):
        """
        Check if withdrawal is allowed - ENHANCED VERSION
        
        Args:
            amount (Decimal): Amount to withdraw
        
        Returns:
            tuple: (bool, str) - (can_withdraw, reason/message)
        """
        amount = Decimal(str(amount))
        
        # Check account status
        if self.status != 'active':
            return False, f"Account is {self.get_status_display()}"
        
        # Check basic balance
        if amount > self.balance:
            return False, f"Insufficient balance. Current balance: ₦{self.balance:,.2f}"
        
        # Check minimum balance requirement
        available_balance = self.balance - self.minimum_balance
        if amount > available_balance:
            return False, (
                f"Withdrawal would violate minimum balance requirement. "
                f"Available: ₦{available_balance:,.2f} "
                f"(Balance: ₦{self.balance:,.2f} - Minimum: ₦{self.minimum_balance:,.2f})"
            )
        
        # Check fixed deposit maturity using product
        if self.savings_product and self.savings_product.product_type == 'fixed' and self.maturity_date:
            if timezone.now().date() < self.maturity_date:
                if not self.savings_product.allows_withdrawal_before_maturity:
                    days_remaining = (self.maturity_date - timezone.now().date()).days
                    return False, (
                        f"Fixed deposit has not matured. "
                        f"Maturity date: {self.maturity_date.strftime('%B %d, %Y')} "
                        f"({days_remaining} days remaining)"
                    )
                elif self.savings_product.early_withdrawal_penalty_rate > 0:
                    penalty_rate = self.savings_product.early_withdrawal_penalty_rate
                    penalty = amount * (penalty_rate / Decimal('100'))
                    return True, (
                        f"Early withdrawal allowed with penalty. "
                        f"Penalty: ₦{penalty:,.2f} ({penalty_rate}% of withdrawal amount)"
                    )
        
        # Check product limits
        if self.savings_product:
            if amount < self.savings_product.min_withdrawal_amount:
                return False, (
                    f"Amount below minimum withdrawal limit. "
                    f"Minimum: ₦{self.savings_product.min_withdrawal_amount:,.2f}"
                )
            
            if self.savings_product.max_withdrawal_amount:
                if amount > self.savings_product.max_withdrawal_amount:
                    return False, (
                        f"Amount exceeds maximum withdrawal limit. "
                        f"Maximum: ₦{self.savings_product.max_withdrawal_amount:,.2f}"
                    )
        
        return True, "Withdrawal allowed"
    
    def calculate_interest(self, calculation_date=None):
        """
        Calculate pending/accrued interest for this account
        
        Args:
            calculation_date (date): Date to calculate interest up to (default: today)
        
        Returns:
            Decimal: Interest amount
        """
        if not self.savings_product or self.savings_product.interest_rate_annual <= 0:
            return Decimal('0.00')
        
        # Only calculate for active accounts
        if self.status != 'active':
            return Decimal('0.00')
        
        # Determine calculation date
        calculation_date = calculation_date or timezone.now().date()
        
        # Determine start date
        if self.last_interest_date:
            start_date = self.last_interest_date
        else:
            start_date = self.date_opened
        
        # Calculate days elapsed
        if calculation_date <= start_date:
            return Decimal('0.00')
        
        days_elapsed = (calculation_date - start_date).days
        
        if days_elapsed <= 0:
            return Decimal('0.00')
        
        # Get annual interest rate
        annual_rate = Decimal(str(self.savings_product.interest_rate_annual))
        rate_decimal = annual_rate / Decimal('100')
        
        # Determine actual days in year (accounting for leap years)
        is_leap = calendar.isleap(calculation_date.year)
        days_in_year = Decimal('366' if is_leap else '365')
        
        # Calculate daily interest rate
        daily_rate = rate_decimal / days_in_year
        
        # Calculate interest: balance × daily_rate × days_elapsed
        interest = self.balance * daily_rate * Decimal(str(days_elapsed))
        
        # Round to 2 decimal places
        interest = interest.quantize(Decimal('0.01'))
        
        logger.debug(
            f"Interest calculated: Account={self.account_number}, "
            f"Balance=₦{self.balance}, AnnualRate={annual_rate}%, "
            f"Days={days_elapsed}, DaysInYear={days_in_year}, "
            f"Interest=₦{interest}"
        )
        
        return interest
    
    @db_transaction.atomic
    def post_interest(self, processed_by):
        """
        Post calculated interest to account balance
        
        Args:
            processed_by (User): User processing the interest posting
        
        Returns:
            Transaction: Created transaction object, or None if no interest to post
        """
        from core.models import Transaction
        from django.db.models import F
        
        # Lock the account row
        account = SavingsAccount.objects.select_for_update().get(pk=self.pk)
        
        # Calculate interest
        interest = account.calculate_interest()
        
        if interest <= 0:
            logger.info(f"No interest to post for account {account.account_number}")
            return None
        
        logger.info(
            f"Posting interest: Account={account.account_number}, "
            f"Amount=₦{interest}, ProcessedBy={processed_by.email}"
        )
        
        old_balance = account.balance
        
        # Update balance and interest earned
        account.balance = F('balance') + interest
        account.interest_earned = F('interest_earned') + interest
        account.last_interest_date = timezone.now().date()
        account.save(update_fields=['balance', 'interest_earned', 'last_interest_date', 'updated_at'])
        
        # Refresh from database
        account.refresh_from_db()
        
        # Verify the update
        expected_balance = old_balance + interest
        if abs(account.balance - expected_balance) > Decimal('0.01'):
            logger.error(
                f"Balance mismatch after interest posting! "
                f"Expected: ₦{expected_balance}, Actual: ₦{account.balance}, "
                f"Account: {account.account_number}"
            )
            raise ValueError("Interest posting verification failed")
        
        # Create transaction record
        txn = Transaction.objects.create(
            transaction_type='interest_credit',
            amount=interest,
            client=account.client,
            savings_account=account,
            branch=account.branch,
            balance_before=old_balance,
            balance_after=account.balance,
            processed_by=processed_by,
            description=f"Interest credit for {account.account_number}",
            status='completed',
            is_income=False
        )
        
        logger.info(
            f"Interest posted: Account={account.account_number}, "
            f"Amount=₦{interest}, NewBalance=₦{account.balance}, "
            f"TxnRef={txn.transaction_ref}"
        )
        
        return txn
    
    def close_account(self, closed_by, reason=''):
        """
        Close the savings account
        
        Args:
            closed_by (User): User closing the account
            reason (str): Reason for closure
        
        Raises:
            ValueError: If account cannot be closed
        """
        if self.status not in ['active', 'suspended']:
            raise ValueError(f"Cannot close account with status: {self.get_status_display()}")
        
        if self.balance > 0:
            raise ValueError(
                f"Cannot close account with positive balance of ₦{self.balance:,.2f}. "
                "Please withdraw all funds first."
            )
        
        self.status = 'closed'
        self.closed_at = timezone.now()
        self.closed_by = closed_by
        self.date_closed = timezone.now().date()
        
        # Add closure reason to notes
        closure_note = (
            f"Account closed on {timezone.now().strftime('%Y-%m-%d %H:%M')} "
            f"by {closed_by.email}. Reason: {reason}"
        )
        if self.notes:
            self.notes = f"{self.notes}\n\n{closure_note}"
        else:
            self.notes = closure_note
        
        self.save(update_fields=['status', 'closed_at', 'closed_by', 'date_closed', 'notes', 'updated_at'])
        
        logger.info(
            f"Account closed: {self.account_number} by {closed_by.email}, Reason: {reason}"
        )
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def get_transaction_history(self, limit=10):
        """Get recent transactions for this account"""
        return self.transactions.order_by('-transaction_date')[:limit]
    
    def get_balance_history(self, days=30):
        """Get balance history for the last N days"""
        from datetime import timedelta
        
        start_date = timezone.now().date() - timedelta(days=days)
        
        transactions = self.transactions.filter(
            transaction_date__gte=start_date,
            status='completed'
        ).order_by('transaction_date')
        
        balance_history = []
        
        for txn in reversed(list(transactions)):
            balance_history.insert(0, (txn.transaction_date, txn.balance_after))
        
        return balance_history





# =============================================================================
# LOAN MODEL  (rewritten)
# =============================================================================

class Loan(BaseModel):
    """
    Loan Applications and Management

    Changes vs previous version
    ---------------------------
    ADDED
        linked_account              FK → SavingsAccount (the "Linked Account" on Details tab)
        interest_type               flat | reducing_balance  (shown as "Interest Type: Flat")
        apr                         Annual Percentage Rate   (shown on Details tab)
        eir                         Effective Interest Rate  (shown on Details tab)
        loan_sector                 Free-text sector field   (shown on Details tab)
        loan_cycle                  Which loan cycle this is for the client (Summary tab)
        last_payment_amount         Amount of the most recent repayment
        last_payment_date           Date of the most recent repayment
        timely_repayments_pct       Percentage of on-time payments (Summary tab)
        client_signature            Cloudinary image — client signs the loan agreement
        union_leader_name           Name of the group leader signing
        union_leader_signature      Cloudinary image
        union_secretary_name        Name of the group secretary signing
        union_secretary_signature   Cloudinary image
        union_member1_name          …member 1
        union_member1_signature
        union_member2_name          …member 2
        union_member2_signature
        union_member3_name          …member 3
        union_member3_signature
        credit_officer_signature    Signature of the credit / loan officer
    REMOVED
        guarantor_name              legacy inline fields — use Guarantor model
        guarantor_phone
        guarantor_address
        guarantor2_name
        guarantor2_phone
        guarantor2_address
    """

    STATUS_CHOICES = [
        ('pending_fees',      'Pending Fee Payment'),
        ('pending_approval',  'Pending Approval'),
        ('approved',          'Approved'),
        ('rejected',          'Rejected'),
        ('disbursed',         'Disbursed'),
        ('active',            'Active'),
        ('completed',         'Completed'),
        ('overdue',           'Overdue'),
        ('written_off',       'Written Off'),
    ]

    DISBURSEMENT_METHOD_CHOICES = [
        ('bank_transfer', 'Bank Transfer'),
        ('cash',          'Cash'),
        ('mobile_money',  'Mobile Money'),
        ('cheque',        'Cheque'),
    ]

    INTEREST_TYPE_CHOICES = [
        ('flat',              'Flat Rate'),
        ('reducing_balance',  'Reducing Balance'),
    ]

    # =========================================================================
    # IDENTIFIERS
    # =========================================================================

    loan_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated loan number"
    )

    # =========================================================================
    # LOAN PRODUCT — SOURCE OF TRUTH
    # =========================================================================

    loan_product = models.ForeignKey(
        'LoanProduct',
        on_delete=models.PROTECT,
        related_name='loans',
        help_text="Loan product (defines type, rates, fees)"
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='loans'
    )
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='loans'
    )

    created_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='loans_created'
    )
    approved_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_approved'
    )
    disbursed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loans_disbursed'
    )

    # =========================================================================
    # LINKED SAVINGS ACCOUNT  ← NEW
    # =========================================================================

    linked_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_loans',
        help_text="Savings account linked to this loan (shown on Details tab)"
    )

    # =========================================================================
    # PRINCIPAL & DURATION
    # =========================================================================

    principal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1000.00'))]
    )
    duration_months = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(36)]
    )

    # =========================================================================
    # INTEREST & CALCULATIONS
    # =========================================================================

    interest_type = models.CharField(                          # ← NEW
        max_length=20,
        choices=INTEREST_TYPE_CHOICES,
        default='flat',
        help_text="How interest is calculated on this loan"
    )
    monthly_interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0350')
    )
    apr = models.DecimalField(                                 # ← NEW
        max_digits=7,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Annual Percentage Rate (e.g. 80.68)"
    )
    eir = models.DecimalField(                                 # ← NEW
        max_digits=7,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Effective Interest Rate (e.g. 123.18)"
    )
    total_interest = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_repayment = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00')
    )
    installment_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00')
    )
    number_of_installments = models.IntegerField(default=0)

    # =========================================================================
    # LOAN PURPOSE & SECTOR
    # =========================================================================

    purpose = models.CharField(max_length=200)
    purpose_details = models.TextField(blank=True, null=True)
    loan_sector = models.CharField(                            # ← NEW
        max_length=200,
        blank=True,
        help_text="Sector / industry the loan is for (e.g. Agriculture, Retail)"
    )

    # =========================================================================
    # CYCLE TRACKING  ← NEW
    # =========================================================================

    loan_cycle = models.PositiveIntegerField(                 # ← NEW
        default=1,
        help_text="Which loan cycle this is for the client (1st loan = 1, 2nd = 2 …)"
    )

    # =========================================================================
    # FEE BREAKDOWN
    # =========================================================================

    risk_premium_fee = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    rp_income_fee = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    tech_fee = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    loan_form_fee = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('200.00')
    )
    total_upfront_fees = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )

    fees_paid = models.BooleanField(default=False, db_index=True)
    fees_paid_date = models.DateTimeField(null=True, blank=True)
    fees_transaction = models.ForeignKey(
        'Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fee_for_loan'
    )

    # =========================================================================
    # REPAYMENT TRACKING
    # =========================================================================

    amount_paid = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    outstanding_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00'), db_index=True
    )
    amount_disbursed = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )

    # Interest accrued but not yet received (cleared when repayment is posted)
    accrued_interest_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=(
            "Cumulative interest accrued via month-end journals but not yet "
            "received in cash. Cleared against 1820 (not 4010) when repayment arrives."
        )
    )

    # last-payment snapshot  ← NEW
    last_payment_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amount of the most recent repayment"
    )
    last_payment_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date of the most recent repayment"
    )

    # timely-repayment ratio  ← NEW
    timely_repayments_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Percentage of installments paid on or before due date"
    )

    # =========================================================================
    # STATUS
    # =========================================================================

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_fees',
        db_index=True
    )

    # =========================================================================
    # DATES
    # =========================================================================

    application_date      = models.DateField(default=date.today, help_text="Date the loan application was submitted")
    approval_date         = models.DateField(null=True, blank=True, help_text="Official date the loan was approved or rejected")
    disbursement_date     = models.DateTimeField(null=True, blank=True)
    completion_date       = models.DateTimeField(null=True, blank=True)

    first_repayment_date  = models.DateField(null=True, blank=True)
    final_repayment_date  = models.DateField(null=True, blank=True)
    next_repayment_date   = models.DateField(null=True, blank=True, db_index=True)

    # =========================================================================
    # DISBURSEMENT DETAILS
    # =========================================================================

    disbursement_method    = models.CharField(max_length=20, choices=DISBURSEMENT_METHOD_CHOICES, blank=True, null=True)
    bank_name              = models.CharField(max_length=200, blank=True, null=True)
    bank_account_number    = models.CharField(max_length=50,  blank=True, null=True)
    bank_account_name      = models.CharField(max_length=200, blank=True, null=True)
    disbursement_reference = models.CharField(max_length=100, blank=True, null=True)
    disbursement_notes     = models.TextField(blank=True, null=True)
    rejection_reason       = models.TextField(blank=True, null=True)

    # =========================================================================
    # SIGNATURES  ← NEW BLOCK
    # =========================================================================

    # — client
    client_signature = CloudinaryField(
        'client_signature',
        folder='loans/signatures/client',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Client's signature on the loan agreement"
    )

    # — group / union leaders  (only populated for group loans)
    union_leader_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Full name of the group leader"
    )
    union_leader_signature = CloudinaryField(
        'union_leader_signature',
        folder='loans/signatures/union_leader',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Group leader's signature"
    )

    union_secretary_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Full name of the group secretary"
    )
    union_secretary_signature = CloudinaryField(
        'union_secretary_signature',
        folder='loans/signatures/union_secretary',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Group secretary's signature"
    )

    # — up to 3 additional group members
    union_member1_name = models.CharField(max_length=200, blank=True, help_text="Group member 1 name")
    union_member1_signature = CloudinaryField(
        'union_member1_signature',
        folder='loans/signatures/union_member1',
        null=True, blank=True, resource_type='image',
        help_text="Group member 1 signature"
    )

    union_member2_name = models.CharField(max_length=200, blank=True, help_text="Group member 2 name")
    union_member2_signature = CloudinaryField(
        'union_member2_signature',
        folder='loans/signatures/union_member2',
        null=True, blank=True, resource_type='image',
        help_text="Group member 2 signature"
    )

    union_member3_name = models.CharField(max_length=200, blank=True, help_text="Group member 3 name")
    union_member3_signature = CloudinaryField(
        'union_member3_signature',
        folder='loans/signatures/union_member3',
        null=True, blank=True, resource_type='image',
        help_text="Group member 3 signature"
    )

    # — credit officer
    credit_officer_signature = CloudinaryField(
        'credit_officer_signature',
        folder='loans/signatures/credit_officer',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Signature of the credit / loan officer who processed this loan"
    )

    # =========================================================================
    # CUSTOM MANAGER
    # =========================================================================

    objects = LoanManager()

    # =========================================================================
    # META
    # =========================================================================

    class Meta:
        ordering = ['-application_date']
        verbose_name = "Loan"
        verbose_name_plural = "Loans"
        indexes = [
            models.Index(fields=['loan_number']),
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['client', 'status']),
            models.Index(fields=['next_repayment_date', 'status']),
            models.Index(fields=['disbursement_date']),
            models.Index(fields=['loan_cycle']),
            models.Index(fields=['linked_account']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(principal_amount__gte=1000),
                name='loan_principal_minimum'
            ),
            models.CheckConstraint(
                check=models.Q(outstanding_balance__gte=0),
                name='loan_outstanding_positive'
            ),
            models.CheckConstraint(
                check=models.Q(amount_paid__gte=0),
                name='loan_amount_paid_positive'
            ),
            models.CheckConstraint(
                check=models.Q(total_upfront_fees__gte=0),
                name='loan_fees_positive'
            ),
            models.CheckConstraint(
                check=models.Q(loan_cycle__gte=1),
                name='loan_cycle_minimum'
            ),
            models.CheckConstraint(
                check=models.Q(apr__gte=0),
                name='loan_apr_positive'
            ),
            models.CheckConstraint(
                check=models.Q(eir__gte=0),
                name='loan_eir_positive'
            ),
            models.CheckConstraint(
                check=models.Q(timely_repayments_pct__gte=0) & models.Q(timely_repayments_pct__lte=100),
                name='loan_timely_repayments_range'
            ),
            models.UniqueConstraint(
                fields=['loan_number'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_loan_number'
            ),
        ]

    # =========================================================================
    # DUNDER / PROPERTIES
    # =========================================================================

    def __str__(self):
        return f"{self.loan_number} - {self.client.get_full_name()}"

    @property
    def loan_type(self):
        return self.loan_product.loan_type if self.loan_product else 'thrift'

    def get_loan_type_display(self):
        from .models import LOAN_TYPE_CHOICES          # adjust import path as needed
        for code, display in LOAN_TYPE_CHOICES:
            if code == self.loan_type:
                return display
        return self.loan_type.capitalize()

    @property
    def repayment_frequency(self):
        return self.loan_product.repayment_frequency if self.loan_product else 'monthly'

    @property
    def monthly_interest_rate_pct(self):
        """Return the monthly interest rate as a percentage (e.g. 0.035 → 3.50)."""
        return self.monthly_interest_rate * Decimal('100')

    def get_repayment_frequency_display(self):
        """Human-readable repayment frequency label (e.g. 'Daily', 'Monthly')."""
        freq = self.repayment_frequency
        labels = dict(REPAYMENT_FREQUENCY_CHOICES)
        return labels.get(freq, freq.capitalize())

    @property
    def balance(self):
        return self.outstanding_balance

    @property
    def days_overdue(self):
        if self.status == 'overdue' and self.next_repayment_date:
            grace_days = (
                self.loan_product.grace_period_days
                if self.loan_product_id and self.loan_product
                else 0
            )
            overdue_from = self.next_repayment_date + timezone.timedelta(days=grace_days)
            return max((timezone.now().date() - overdue_from).days, 0)
        return 0

    @property
    def payment_progress_percentage(self):
        if self.total_repayment == 0:
            return 0
        return float((self.amount_paid / self.total_repayment) * 100)

    # =========================================================================
    # SAVE  —  auto-generate number, calculate details, set cycle
    # =========================================================================

    def save(self, *args, **kwargs):
        if not self.pk or self._state.adding:
            if not self.loan_number:
                self.loan_number = self.generate_loan_number()

            # auto-set loan_cycle: count previous loans for this client + 1
            if self.client_id:
                from django.db.models import Count
                self.loan_cycle = (
                    Loan.objects.filter(client_id=self.client_id)
                    .exclude(pk=self.pk)
                    .count()
                ) + 1

            self.calculate_loan_details()

        if not self.pk:
            self.outstanding_balance = self.total_repayment

        super().save(*args, **kwargs)

    @staticmethod
    def generate_loan_number():
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_suffix = get_random_string(6, '0123456789')
        loan_number = f"LN{timestamp}{random_suffix}"
        while Loan.objects.filter(loan_number=loan_number).exists():
            random_suffix = get_random_string(6, '0123456789')
            loan_number = f"LN{timestamp}{random_suffix}"
        return loan_number

    # =========================================================================
    # CALCULATIONS
    # =========================================================================

    def calculate_loan_details(self):
        """Calculate interest, installments, fees, APR, EIR, dates."""
        product = self.loan_product
        method  = product.interest_calculation_method if product else 'flat'

        # — echo method onto loan
        if product:
            self.interest_type = method

        monthly_rate = product.monthly_interest_rate if product else Decimal('0.035')
        self.monthly_interest_rate = monthly_rate

        # — installment count by frequency
        # Daily: 20 standard working days per month.
        # Interest calculation uses monthly rate regardless of frequency.
        freq_map = {
            'daily':        self.duration_months * 20,
            'weekly':       self.duration_months * 4,
            'fortnightly':  self.duration_months * 2,
            'monthly':      self.duration_months,
            'yearly':       max(1, self.duration_months // 12),
        }
        n = freq_map.get(self.repayment_frequency, self.duration_months)
        self.number_of_installments = n

        # — interest calculation: flat vs reducing balance
        if method == 'reducing_balance' and n > 0:
            # Period rate: scale the monthly rate to match the payment frequency.
            period_rate_map = {
                'daily':       monthly_rate / 20,
                'weekly':      monthly_rate / 4,
                'fortnightly': monthly_rate / 2,
                'monthly':     monthly_rate,
                'yearly':      monthly_rate * 12,
            }
            period_rate = period_rate_map.get(self.repayment_frequency, monthly_rate)
            rb = InterestCalculator.calculate_reducing_balance_interest(
                principal=self.principal_amount,
                monthly_rate=period_rate,
                months=n,
            )
            self.total_interest     = rb['total_interest']
            self.total_repayment    = rb['total_repayment']
            self.installment_amount = rb['emi']
        else:
            # Flat rate: interest = P × r × T (T in months, rate is monthly)
            calc = InterestCalculator.calculate_flat_interest(
                principal=self.principal_amount,
                monthly_rate=monthly_rate,
                months=self.duration_months,
            )
            self.total_interest  = calc['total_interest']
            self.total_repayment = calc['total_repayment']
            if n > 0:
                self.installment_amount = MoneyCalculator.round_money(
                    self.total_repayment / n
                )
            else:
                self.installment_amount = calc['monthly_installment']

        # — APR  (total cost of credit annualised)
        if self.principal_amount and self.duration_months:
            self.apr = MoneyCalculator.round_money(
                (self.total_interest / self.principal_amount)
                / self.duration_months * 12 * 100
            )

        # — EIR  = ((1 + monthly_rate)^12 - 1) × 100
        monthly = Decimal(str(monthly_rate))
        self.eir = MoneyCalculator.round_money(((1 + monthly) ** 12 - 1) * 100)

        # — fees from product
        if product:
            fees = product.calculate_fees(self.principal_amount)
            self.risk_premium_fee   = fees['risk_premium_fee']
            self.rp_income_fee      = fees['rp_income_fee']
            self.tech_fee           = fees['tech_fee']
            self.loan_form_fee      = fees['loan_form_fee']
            self.total_upfront_fees = fees['total_upfront_fees']

        # — repayment dates (preview only — disburse() recalculates from actual date)
        if not self.first_repayment_date:
            start = self.disbursement_date.date() if self.disbursement_date else timezone.now().date()
            # Apply grace period offset
            grace_days = 0
            try:
                if self.loan_product_id and self.loan_product:
                    grace_days = self.loan_product.grace_period_days or 0
            except Exception:
                pass
            if grace_days:
                import datetime as _dt_preview
                start = start + _dt_preview.timedelta(days=grace_days)
            self.first_repayment_date = self.calculate_next_payment_date(start)
            self.next_repayment_date  = self.first_repayment_date

            from dateutil.relativedelta import relativedelta
            freq = self.repayment_frequency
            if freq == 'daily':
                d = self.first_repayment_date
                for _ in range(n - 1):
                    d = add_one_business_day(d)
                self.final_repayment_date = d
            elif freq == 'weekly':
                self.final_repayment_date = self.first_repayment_date + timezone.timedelta(weeks=n - 1)
            elif freq == 'fortnightly':
                self.final_repayment_date = self.first_repayment_date + timezone.timedelta(weeks=(n - 1) * 2)
            elif freq == 'yearly':
                self.final_repayment_date = self.first_repayment_date + relativedelta(years=n - 1)
            else:
                self.final_repayment_date = self.first_repayment_date + relativedelta(months=n - 1)

    def calculate_next_payment_date(self, from_date):
        from dateutil.relativedelta import relativedelta
        freq = self.repayment_frequency
        if freq == 'daily':
            # Move to the next Mon–Fri business day (skip Sat/Sun)
            return add_one_business_day(from_date)
        elif freq == 'weekly':
            return next_business_day(from_date + timezone.timedelta(weeks=1))
        elif freq == 'fortnightly':
            return next_business_day(from_date + timezone.timedelta(weeks=2))
        elif freq == 'yearly':
            return next_business_day(from_date + relativedelta(years=1))
        return next_business_day(from_date + relativedelta(months=1))

    def get_repayment_schedule(self):
        return generate_repayment_schedule(self)

    # =========================================================================
    # CLEAN
    # =========================================================================

    def clean(self):
        super().clean()
        errors = {}

        # safe access to related objects (may not exist during form validation)
        loan_product = None
        try:
            loan_product = self.loan_product
        except Loan.loan_product.RelatedObjectDoesNotExist:
            pass

        client = None
        try:
            client = self.client
        except Loan.client.RelatedObjectDoesNotExist:
            pass

        if loan_product and self.principal_amount:
            if not loan_product.is_amount_valid(self.principal_amount):
                errors['principal_amount'] = (
                    f"Amount must be between ₦{loan_product.min_principal_amount:,.2f} "
                    f"and ₦{loan_product.max_principal_amount:,.2f}"
                )
            if self.duration_months and not loan_product.is_duration_valid(self.duration_months):
                errors['duration_months'] = (
                    f"Duration must be between {loan_product.min_duration_months} "
                    f"and {loan_product.max_duration_months} months"
                )
            if client:
                is_eligible, reasons = loan_product.check_eligibility(client)
                if not is_eligible:
                    errors['client'] = '; '.join(reasons)

        if client and self.principal_amount:
            can_borrow, message = client.can_borrow(self.principal_amount)
            if not can_borrow:
                errors['principal_amount'] = message

        if self.disbursement_date and self.approval_date:
            disburse_date = self.disbursement_date.date() if hasattr(self.disbursement_date, 'date') else self.disbursement_date
            if disburse_date < self.approval_date:
                errors['disbursement_date'] = "Disbursement date cannot be before approval date"

        # linked_account must belong to the same client
        if self.linked_account_id and client:
            if self.linked_account.client_id != client.id:
                errors['linked_account'] = "Linked savings account must belong to the same client"

        if errors:
            raise ValidationError(errors)

    # =========================================================================
    # WORKFLOW METHODS  (unchanged logic, kept intact)
    # =========================================================================

    @db_transaction.atomic
    def pay_fees(self, processed_by, payment_details='', transaction_date=None):
        """
        Collect upfront fees and record a single 'charges_at_disbursement'
        transaction linked to this loan.
        """
        import datetime as _dt_mod
        if transaction_date is not None:
            if isinstance(transaction_date, _dt_mod.date) and not isinstance(transaction_date, _dt_mod.datetime):
                txn_dt = timezone.make_aware(_dt_mod.datetime.combine(transaction_date, _dt_mod.time.min))
            else:
                txn_dt = transaction_date
        else:
            txn_dt = timezone.now()

        if self.fees_paid:
            return False, "Fees already paid"
        if self.status != 'pending_fees':
            return False, f"Cannot pay fees for loan with status: {self.get_status_display()}"
        if self.total_upfront_fees <= Decimal('0.00'):
            # nothing to collect — just advance status
            self.fees_paid      = True
            self.fees_paid_date = txn_dt
            self.status         = 'pending_approval'
            self.save(update_fields=[
                'fees_paid', 'fees_paid_date', 'status', 'updated_at'
            ])
            return True, "No fees due — status advanced"

        # --- create the fee transaction ---
        txn = Transaction.objects.create(
            transaction_type  = 'charges_at_disbursement',
            amount            = self.total_upfront_fees,
            client            = self.client,
            loan              = self,                          # ← linked
            branch            = self.branch,
            balance_before    = Decimal('0.00'),
            balance_after     = self.total_upfront_fees,
            processed_by      = processed_by,
            description       = f"Upfront fees for {self.loan_number}",
            payment_details   = payment_details,
            status            = 'completed',
            transaction_date  = txn_dt,
        )

        self.fees_paid          = True
        self.fees_paid_date     = txn_dt
        self.fees_transaction   = txn
        self.status             = 'pending_approval'
        self.save(update_fields=[
            'fees_paid', 'fees_paid_date', 'fees_transaction', 'status', 'updated_at'
        ])

        # Create journal entry (Dr Cash / Cr Fee Income accounts)
        try:
            post_loan_upfront_fees_journal(self, processed_by, txn)
            logger.info(f"Journal entry created for upfront fees: {self.loan_number}")
        except Exception as e:
            logger.error(f"Failed to create fee journal for loan {self.loan_number}: {str(e)}")

        return True, "Fees paid successfully"



    @db_transaction.atomic
    def approve(self, approved_by, approval_date=None):
        if self.status != 'pending_approval':
            return False, f"Cannot approve loan with status: {self.get_status_display()}"
        if not self.fees_paid:
            return False, "Fees must be paid before approval"

        self.status      = 'approved'
        self.approved_by = approved_by
        self.approval_date = approval_date if approval_date else timezone.now().date()
        self.save(update_fields=['status', 'approved_by', 'approval_date', 'updated_at'])
        return True, "Loan approved successfully"

    @db_transaction.atomic
    def reject(self, rejected_by, reason='', approval_date=None):
        if self.status not in ['pending_fees', 'pending_approval']:
            return False, f"Cannot reject loan with status: {self.get_status_display()}"

        self.status           = 'rejected'
        self.approved_by      = rejected_by
        self.approval_date    = approval_date if approval_date else timezone.now().date()
        self.rejection_reason = reason
        self.save(update_fields=[
            'status', 'approved_by', 'approval_date', 'rejection_reason', 'updated_at'
        ])
        return True, "Loan rejected"

    @db_transaction.atomic
    def disburse(self, disbursed_by, method='cash', reference='', disbursement_date=None):
        if self.status != 'approved':
            return False, f"Cannot disburse loan with status: {self.get_status_display()}"

        import datetime as _dt_mod
        if disbursement_date is not None:
            if isinstance(disbursement_date, _dt_mod.date) and not isinstance(disbursement_date, _dt_mod.datetime):
                disburse_dt = timezone.make_aware(_dt_mod.datetime.combine(disbursement_date, _dt_mod.time.min))
            else:
                disburse_dt = disbursement_date
        else:
            disburse_dt = timezone.now()

        self.status               = 'active'
        self.disbursed_by         = disbursed_by
        self.disbursement_date    = disburse_dt
        self.disbursement_method  = method
        self.disbursement_reference = reference
        self.amount_disbursed     = self.principal_amount
        self.outstanding_balance  = self.total_repayment

        # Always recalculate from the actual disbursement date.
        # calculate_loan_details() runs at loan creation when disbursement_date
        # is still None, so any previously stored first_repayment_date is wrong.
        grace_days = 0
        try:
            if self.loan_product_id and self.loan_product:
                grace_days = self.loan_product.grace_period_days or 0
        except Exception:
            pass

        schedule_start = disburse_dt.date() + _dt_mod.timedelta(days=grace_days)
        self.first_repayment_date = self.calculate_next_payment_date(schedule_start)
        self.next_repayment_date  = self.first_repayment_date

        # Recalculate final repayment date anchored to first_repayment_date
        from dateutil.relativedelta import relativedelta as _rd_disburse
        n_inst = self.number_of_installments
        freq   = self.repayment_frequency
        if n_inst and n_inst > 0:
            if freq == 'daily':
                _d = self.first_repayment_date
                for _ in range(n_inst - 1):
                    _d = add_one_business_day(_d)
                self.final_repayment_date = _d
            elif freq == 'weekly':
                self.final_repayment_date = self.first_repayment_date + _dt_mod.timedelta(weeks=n_inst - 1)
            elif freq == 'fortnightly':
                self.final_repayment_date = self.first_repayment_date + _dt_mod.timedelta(weeks=(n_inst - 1) * 2)
            elif freq == 'yearly':
                self.final_repayment_date = self.first_repayment_date + _rd_disburse(years=n_inst - 1)
            else:  # monthly
                self.final_repayment_date = self.first_repayment_date + _rd_disburse(months=n_inst - 1)

        self.save()

        # Create transaction record for disbursement
        from core.models import Transaction
        txn = Transaction.objects.create(
            transaction_type='loan_disbursement',
            amount=self.principal_amount,
            client=self.client,
            loan=self,
            branch=self.branch,
            balance_before=Decimal('0.00'),
            balance_after=self.outstanding_balance,
            processed_by=disbursed_by,
            description=f"Loan disbursement: {self.loan_number}",
            status='completed',
            transaction_date=disburse_dt,
        )

        # Persist repayment schedule rows (only if not already created)
        try:
            if not LoanRepaymentSchedule.objects.filter(loan=self).exists():
                schedule_items = generate_repayment_schedule(self)
            else:
                schedule_items = []
            if schedule_items:
                schedule_objects = [
                    LoanRepaymentSchedule(
                        loan=self,
                        installment_number=item['installment_number'],
                        due_date=item['due_date'],
                        principal_amount=item['principal_amount'],
                        interest_amount=item['interest_amount'],
                        total_amount=item['total_amount'],
                        outstanding_amount=item['total_amount'],
                        status='pending',
                    )
                    for item in schedule_items
                ]
                LoanRepaymentSchedule.objects.bulk_create(schedule_objects)
                logger.info(
                    f"Repayment schedule persisted for loan {self.loan_number}: "
                    f"{len(schedule_objects)} installments"
                )
        except Exception as e:
            logger.error(
                f"Failed to persist repayment schedule for loan {self.loan_number}: {str(e)}"
            )

        # Create journal entry (Dr Loan Receivable, Cr Cash)
        try:
            post_loan_disbursement_journal(self, disbursed_by, transaction_obj=txn)
            logger.info(f"Journal entry created for loan disbursement: {self.loan_number}")
        except Exception as e:
            logger.error(f"Failed to create journal entry for loan {self.loan_number}: {str(e)}")

        return True, "Loan disbursed successfully"

    @db_transaction.atomic
    def record_repayment(self, amount, processed_by, description='', transaction_date=None):
        """
        Record a repayment, split into principal + interest,
        update last_payment_* snapshot and timely_repayments_pct.
        """
        import datetime as _dt  # adjust import path

        if self.status not in ['active', 'overdue']:
            raise ValueError(
                f"Cannot record repayment for loan with status: {self.get_status_display()}"
            )

        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValueError("Repayment amount must be greater than zero")
        if amount > self.outstanding_balance:
            raise ValueError(
                f"Amount exceeds outstanding balance of ₦{self.outstanding_balance:,.2f}"
            )

        # --- principal / interest split (schedule-based, then pro-rata fallback) ---
        interest_portion  = Decimal('0.00')
        principal_portion = Decimal('0.00')
        remaining         = amount

        schedule_rows = (
            self.repayment_schedule
            .filter(status__in=['pending', 'partial', 'overdue'])
            .order_by('installment_number')
        )

        if schedule_rows.exists():
            for row in schedule_rows:
                if remaining <= 0:
                    break
                row_int_owed  = row.interest_amount  - min(row.amount_paid, row.interest_amount)
                row_prin_owed = row.principal_amount - max(row.amount_paid - row.interest_amount, Decimal('0.00'))

                int_taken  = min(remaining, row_int_owed)
                interest_portion += int_taken
                remaining -= int_taken

                prin_taken = min(remaining, row_prin_owed)
                principal_portion += prin_taken
                remaining -= prin_taken

            principal_portion += remaining          # any leftover → principal
        else:
            # pro-rata fallback
            interest_ratio    = self.total_interest / self.total_repayment if self.total_repayment else Decimal('0')
            interest_portion  = (amount * interest_ratio).quantize(Decimal('0.01'))
            principal_portion = amount - interest_portion

        # drift guard
        drift = amount - (principal_portion + interest_portion)
        if drift != 0:
            principal_portion += drift

        # --- update loan balances ---
        old_balance = self.outstanding_balance
        self.amount_paid        += amount
        self.outstanding_balance -= amount

        # --- clear accrued interest receivable ---
        # How much of the interest_portion was previously accrued (Dr 1820).
        # The journal will Cr 1820 for this amount instead of Cr 4010 (income)
        # to avoid double-counting.
        accrued_to_clear = min(interest_portion, self.accrued_interest_balance)
        self.accrued_interest_balance = max(
            Decimal('0.00'),
            self.accrued_interest_balance - accrued_to_clear
        )

        # --- last-payment snapshot ---
        self.last_payment_amount = amount
        self.last_payment_date   = timezone.now().date()

        # --- timely-repayments percentage ---
        self._recalculate_timely_repayments_pct()

        # --- advance next_repayment_date ---
        if self.next_repayment_date:
            self.next_repayment_date = self.calculate_next_payment_date(self.next_repayment_date)

        # --- status
        if self.outstanding_balance <= Decimal('0.01'):
            self.outstanding_balance = Decimal('0.00')
            self.status             = 'completed'
            self.completion_date    = timezone.now()
        elif self.next_repayment_date:
            grace_days = (
                self.loan_product.grace_period_days
                if self.loan_product_id and self.loan_product
                else 0
            )
            overdue_threshold = self.next_repayment_date + timezone.timedelta(days=grace_days)
            if overdue_threshold < timezone.now().date():
                self.status = 'overdue'
            else:
                self.status = 'active'
        else:
            self.status = 'active'

        update_fields = [
            'amount_paid', 'outstanding_balance', 'accrued_interest_balance',
            'last_payment_amount', 'last_payment_date', 'timely_repayments_pct',
            'status', 'updated_at',
        ]
        if self.next_repayment_date is not None:
            update_fields.append('next_repayment_date')
        if self.status == 'completed':
            update_fields.append('completion_date')
        self.save(update_fields=update_fields)

        # Resolve transaction datetime (backdate if collection_date supplied)
        txn_dt = transaction_date if transaction_date is not None else timezone.now()
        if isinstance(txn_dt, _dt.date) and not isinstance(txn_dt, _dt.datetime):
            txn_dt = timezone.make_aware(_dt.datetime.combine(txn_dt, _dt.time.min))

        # --- transaction record ---
        txn = Transaction.objects.create(
            transaction_type='loan_repayment',
            amount=amount,
            principal_amount=principal_portion,
            interest_amount=interest_portion,
            client=self.client,
            loan=self,
            branch=self.branch,
            balance_before=old_balance,
            balance_after=self.outstanding_balance,
            processed_by=processed_by,
            description=description or f"Repayment for {self.loan_number}",
            status='completed',
            transaction_date=txn_dt,
        )

        # Create journal entry (Dr Cash, Cr Loan Receivable + Interest accounts)
        # accrued_to_clear drives whether interest credits 1820 or 4010
        try:
            post_loan_repayment_journal(
                loan=self,
                amount=amount,
                principal_portion=principal_portion,
                interest_portion=interest_portion,
                processed_by=processed_by,
                transaction_obj=txn,
                accrued_interest_to_clear=accrued_to_clear,
            )
            logger.info(
                f"Journal entry created for loan repayment: {self.loan_number}, "
                f"Amount=₦{amount}, Principal=₦{principal_portion}, "
                f"Interest=₦{interest_portion} (accrual cleared=₦{accrued_to_clear})"
            )
        except Exception as e:
            logger.error(
                f"Failed to create journal entry for repayment {txn.transaction_ref}: {str(e)}"
            )

        return txn

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _recalculate_timely_repayments_pct(self):
        """
        Walk the repayment schedule and calculate what % of due installments
        were paid on or before their due_date.
        """
        due_rows = self.repayment_schedule.filter(
            due_date__lte=timezone.now().date()
        )
        total_due = due_rows.count()
        if total_due == 0:
            self.timely_repayments_pct = Decimal('0.00')
            return

        on_time = due_rows.filter(status='paid').exclude(
            # exclude rows where paid_date is after due_date
            paid_date__gt=models.F('due_date')
        ).count()

        self.timely_repayments_pct = MoneyCalculator.round_money(
            Decimal(on_time) / Decimal(total_due) * 100
        )

    # =========================================================================
    # QUERY HELPERS
    # =========================================================================

    def get_repayment_schedule_qs(self):
        return self.repayment_schedule.all().order_by('installment_number')

    def get_transaction_history(self):
        return self.transactions.all().order_by('-transaction_date')






# =============================================================================
# LOAN NOTE MODEL  (brand new)
# =============================================================================

class LoanNote(BaseModel):
    """
    Loan Notes

    Maps to the Notes tab visible in the reference screenshots.
    Columns shown: Id | Created By | Created On | Note Type | Note
    """

    NOTE_TYPE_CHOICES = [
        ('loan_transaction_note', 'Loan Transaction Note'),
        ('collection_note',       'Collection Note'),
        ('general',               'General Note'),
        ('follow_up',             'Follow-Up Note'),
        ('approval',              'Approval Note'),
        ('disbursement',          'Disbursement Note'),
        ('restructure',           'Restructure Note'),
        ('other',                 'Other'),
    ]

    # =========================================================================
    # RELATIONSHIP
    # =========================================================================

    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='notes',
        help_text="The loan this note belongs to"
    )

    # =========================================================================
    # CONTENT
    # =========================================================================

    note_type = models.CharField(
        max_length=40,
        choices=NOTE_TYPE_CHOICES,
        default='general',
        db_index=True,
        help_text="Category / type of this note"
    )

    note = models.TextField(
        help_text="The note content"
    )

    # =========================================================================
    # AUDIT
    # =========================================================================

    created_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='loan_notes_created',
        help_text="Staff member who wrote this note"
    )

    # =========================================================================
    # META
    # =========================================================================

    class Meta:
        ordering  = ['-created_at']
        verbose_name = "Loan Note"
        verbose_name_plural = "Loan Notes"
        indexes = [
            models.Index(fields=['loan', '-created_at']),
            models.Index(fields=['note_type']),
            models.Index(fields=['created_by']),
        ]

    def __str__(self):
        return f"{self.get_note_type_display()} on {self.loan.loan_number} ({self.created_at.date()})"


# =============================================================================
# FROM: transaction_accounting_models.py
# =============================================================================


# =============================================================================
# TRANSACTION MODEL
# =============================================================================

class Transaction(BaseModel):
    """
    All Financial Transactions
    """

    TRANSACTION_TYPE_CHOICES = [
        # --- savings ---
        ('deposit',                 'Savings Deposit'),
        ('withdrawal',              'Savings Withdrawal'),
        ('interest_credit',         'Interest Credit'),          # savings interest

        # --- loan ---
        ('loan_disbursement',       'Loan Disbursement'),
        ('loan_repayment',          'Loan Repayment'),
        ('interest_applied',        'Interest Applied'),         # ← NEW  loan interest charge
        ('charges_at_disbursement', 'Charges At Disbursement'),  # ← NEW  bundled upfront fees

        # --- fees (individual lines, still usable) ---
        ('registration_fee',        'Client Registration Fee'),
        ('id_card_fee',             'ID Card Fee'),
        ('membership_card_fee',     'Membership Card Fee'),
        ('loan_insurance_fee',      'Loan Insurance Fee'),
        ('loan_form_fee',           'Loan Form Fee'),
        ('risk_premium',            'Risk Premium Fee'),
        ('rp_income',               'RP Income Fee'),
        ('tech_fee',                'Technology Fee'),
        ('fee',                     'Fee / Charge'),

        # --- other ---
        ('reversal',                'Reversal'),
        ('transfer',                'Transfer'),
    ]

    # -----------------------------------------------------------------------
    # Which types count as income (fees collected INTO the bank)
    # -----------------------------------------------------------------------
    INCOME_TYPES = [
        'registration_fee',
        'id_card_fee',
        'membership_card_fee',
        'loan_insurance_fee',
        'loan_form_fee',
        'risk_premium',
        'rp_income',
        'tech_fee',
        'fee',
        'charges_at_disbursement',   # fees collected are income
        'loan_repayment',            # repayments are inflows
        'deposit',                   # savings deposits are inflows
        'interest_credit',           # interest credited is an inflow to client
    ]

    # -----------------------------------------------------------------------
    # Which types are outflows (money leaving the bank / being charged)
    # Used by the debit_amount / credit_amount properties.
    # -----------------------------------------------------------------------
    OUTFLOW_TYPES = {
        'loan_disbursement',   # bank pays out
        'withdrawal',          # client withdraws
        'interest_applied',    # interest charged against client (bank earns)
        'reversal',            # could go either way — see property logic
    }

    STATUS_CHOICES = [
        ('pending',    'Pending Approval'),
        ('approved',   'Approved'),
        ('completed',  'Completed'),
        ('rejected',   'Rejected'),
        ('failed',     'Failed'),
        ('reversed',   'Reversed'),
    ]

    # =========================================================================
    # IDENTIFIERS
    # =========================================================================

    transaction_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated transaction reference"
    )

    # =========================================================================
    # TRANSACTION DETAILS
    # =========================================================================

    transaction_type = models.CharField(
        max_length=30,
        choices=TRANSACTION_TYPE_CHOICES,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    # --- principal / interest split (populated on loan_repayment) ---
    principal_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        help_text="Principal portion of a repayment"
    )
    interest_amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        help_text="Interest portion of a repayment"
    )

    is_income = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Is this an income transaction?"
    )

    # =========================================================================
    # PAYMENT DETAILS  ← NEW
    # =========================================================================

    payment_details = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "Freeform payment reference shown in the 'Payment Details' column "
            "(e.g. a bank-transfer ref number, 'collection', 'Slo …')"
        )
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='transactions',
        null=True,
        blank=True,
    )
    savings_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transactions'
    )
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transactions'
    )
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='transactions'
    )

    # =========================================================================
    # BALANCE TRACKING
    # =========================================================================

    balance_before = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        help_text="Balance before this transaction"
    )
    balance_after = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        help_text="Balance after this transaction"
    )

    # =========================================================================
    # AUDIT
    # =========================================================================

    processed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='processed_transactions'
    )
    approved_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_transactions'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # =========================================================================
    # REJECTION
    # =========================================================================

    rejection_reason = models.TextField(blank=True)

    # =========================================================================
    # DESCRIPTION
    # =========================================================================

    description = models.TextField(blank=True)
    notes       = models.TextField(blank=True)

    # =========================================================================
    # DATES
    # =========================================================================

    transaction_date = models.DateTimeField(default=timezone.now, db_index=True)

    # =========================================================================
    # REVERSAL SUPPORT
    # =========================================================================

    reversed_transaction = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversals'
    )

    # =========================================================================
    # MANAGER
    # =========================================================================

    objects = TransactionManager()

    # =========================================================================
    # META
    # =========================================================================

    class Meta:
        ordering = ['-transaction_date']
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        indexes = [
            models.Index(fields=['transaction_ref']),
            models.Index(fields=['transaction_type', 'status']),
            models.Index(fields=['is_income', 'status']),
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['client', 'transaction_date']),
            models.Index(fields=['loan', 'transaction_date']),           # ← useful for the Transactions tab
            models.Index(fields=['transaction_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='transaction_amount_positive'
            ),
            models.UniqueConstraint(
                fields=['transaction_ref'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_transaction_ref'
            ),
        ]

    # =========================================================================
    # DUNDER
    # =========================================================================

    def __str__(self):
        return f"{self.transaction_ref} - {self.get_transaction_type_display()} - ₦{self.amount:,.2f}"

    # =========================================================================
    # SAVE
    # =========================================================================

    def save(self, *args, **kwargs):
        # auto-set is_income
        if self.transaction_type in self.INCOME_TYPES:
            self.is_income = True

        # auto-generate ref
        if not self.transaction_ref:
            self.transaction_ref = self.generate_transaction_ref()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_transaction_ref():
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_suffix = get_random_string(6, '0123456789')
        ref = f"TXN{timestamp}{random_suffix}"
        while Transaction.objects.filter(transaction_ref=ref).exists():
            random_suffix = get_random_string(6, '0123456789')
            ref = f"TXN{timestamp}{random_suffix}"
        return ref

    # =========================================================================
    # DEBIT / CREDIT PROPERTIES
    # =========================================================================
    # These mirror the two columns the reference software shows on the loan
    # Transactions tab.
    #
    #   Debit  = money going OUT of the bank  (disbursement, interest charged)
    #   Credit = money coming IN  to the bank (repayment, fees collected)
    #
    # Special case: 'reversal' — if it reverses an outflow it becomes an
    # inflow and vice-versa, so we look at the original transaction.
    # =========================================================================

    @property
    def debit_amount(self):
        """Amount in the Debit column (outflow), or 0."""
        if self.transaction_type == 'reversal' and self.reversed_transaction:
            # a reversal flips the direction of the original
            return self.reversed_transaction.credit_amount
        if self.transaction_type in self.OUTFLOW_TYPES:
            return self.amount
        return Decimal('0.00')

    @property
    def credit_amount(self):
        """Amount in the Credit column (inflow), or 0."""
        if self.transaction_type == 'reversal' and self.reversed_transaction:
            return self.reversed_transaction.debit_amount
        if self.transaction_type not in self.OUTFLOW_TYPES:
            return self.amount
        return Decimal('0.00')

    # =========================================================================
    # CLEAN
    # =========================================================================

    def clean(self):
        super().clean()
        errors = {}

        if self.amount <= 0:
            errors['amount'] = "Amount must be greater than zero"

        if self.transaction_type in ['deposit', 'withdrawal', 'interest_credit']:
            if not self.savings_account:
                errors['savings_account'] = (
                    f"{self.get_transaction_type_display()} requires a savings account"
                )

        if self.transaction_type in [
            'loan_disbursement', 'loan_repayment',
            'interest_applied', 'charges_at_disbursement',
        ]:
            if not self.loan:
                errors['loan'] = (
                    f"{self.get_transaction_type_display()} requires a loan"
                )

        # balance-tracking consistency check
        if self.balance_before is not None and self.balance_after is not None:
            if self.transaction_type in ['deposit', 'loan_disbursement', 'interest_credit']:
                expected = self.balance_before + self.amount
                if abs(self.balance_after - expected) > Decimal('0.01'):
                    errors['balance_after'] = f"Balance mismatch (expected ≈ {expected})"

            elif self.transaction_type in ['withdrawal', 'loan_repayment']:
                expected = self.balance_before - self.amount
                if abs(self.balance_after - expected) > Decimal('0.01'):
                    errors['balance_after'] = f"Balance mismatch (expected ≈ {expected})"

        if errors:
            raise ValidationError(errors)

    # =========================================================================
    # WORKFLOW METHODS
    # =========================================================================

    @db_transaction.atomic
    def approve(self, approved_by):
        if self.status != 'pending':
            raise ValueError(f"Cannot approve transaction with status: {self.get_status_display()}")
        self.status     = 'approved'
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    @db_transaction.atomic
    def complete(self):
        if self.status not in ['pending', 'approved']:
            raise ValueError(f"Cannot complete transaction with status: {self.get_status_display()}")
        self.status = 'completed'
        self.save(update_fields=['status', 'updated_at'])

    @db_transaction.atomic
    def reject(self, rejected_by, reason=''):
        if self.status != 'pending':
            raise ValueError(f"Cannot reject transaction with status: {self.get_status_display()}")
        self.status          = 'rejected'
        self.approved_by     = rejected_by
        self.approved_at     = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=[
            'status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'
        ])

    @db_transaction.atomic
    def reverse(self, reversed_by, reason=''):
        """Reverse this transaction — creates an opposite-direction copy."""
        if self.status != 'completed':
            raise ValueError("Only completed transactions can be reversed")

        reversal_type_map = {
            'deposit':          'withdrawal',
            'withdrawal':       'deposit',
            'loan_disbursement':'loan_repayment',
            'loan_repayment':   'loan_disbursement',
        }
        reversal_type = reversal_type_map.get(self.transaction_type, 'reversal')

        reversal = Transaction.objects.create(
            transaction_type      = reversal_type,
            amount                = self.amount,
            client                = self.client,
            savings_account       = self.savings_account,
            loan                  = self.loan,
            branch                = self.branch,
            processed_by          = reversed_by,
            description           = f"Reversal of {self.transaction_ref}: {reason}",
            reversed_transaction  = self,
            status                = 'completed'
        )

        self.status = 'reversed'
        self.save(update_fields=['status', 'updated_at'])
        return reversal


# =============================================================================
# LOAN REPAYMENT POSTING - TWO-TIER APPROVAL SYSTEM
# =============================================================================

class LoanRepaymentPosting(BaseModel):
    """
    Loan Repayment Posting - Staff submit repayments that require approval

    WORKFLOW:
    1. Staff posts a repayment for one or more loans
    2. Posting status = 'pending'
    3. Manager/Director/Admin reviews and approves or rejects
    4. On approval: Loan.record_repayment() is called, transaction created
    5. On rejection: Nothing happens, posting is marked rejected

    This two-tier system ensures:
    - Accountability: All repayments are tracked before execution
    - Oversight: Managers must approve before loan balances are updated
    - Error prevention: Invalid postings caught before affecting accounts
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('cheque', 'Cheque'),
        ('direct_debit', 'Direct Debit'),
    ]

    # =========================================================================
    # CORE FIELDS
    # =========================================================================

    posting_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated posting reference (e.g., LRP20260204143022ABC123)"
    )

    loan = models.ForeignKey(
        'Loan',
        on_delete=models.PROTECT,
        related_name='repayment_postings',
        help_text="Loan being repaid"
    )

    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='loan_repayment_postings',
        help_text="Client making the repayment"
    )

    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='loan_repayment_postings'
    )

    # =========================================================================
    # AMOUNTS
    # =========================================================================

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Total repayment amount"
    )

    principal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Calculated principal portion (set on approval)"
    )

    interest_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Calculated interest portion (set on approval)"
    )

    # =========================================================================
    # PAYMENT DETAILS
    # =========================================================================

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='cash'
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Transaction reference, receipt number, etc."
    )

    payment_details = models.TextField(
        blank=True,
        help_text="Additional payment information (bank name, mobile number, etc.)"
    )

    payment_date = models.DateField(
        help_text="Date the payment was received"
    )

    # =========================================================================
    # STATUS TRACKING
    # =========================================================================

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    # =========================================================================
    # SUBMISSION TRACKING
    # =========================================================================

    submitted_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='submitted_loan_repayments'
    )

    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    submission_notes = models.TextField(
        blank=True,
        help_text="Notes from staff member submitting the repayment"
    )

    # =========================================================================
    # REVIEW TRACKING
    # =========================================================================

    reviewed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_loan_repayments'
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)

    review_notes = models.TextField(
        blank=True,
        help_text="Notes from reviewer (approval/rejection reason)"
    )

    # =========================================================================
    # TRANSACTION LINK (populated on approval)
    # =========================================================================

    transaction = models.ForeignKey(
        'Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='repayment_posting',
        help_text="Transaction created when this posting was approved"
    )

    class Meta:
        ordering = ['-submitted_at']
        verbose_name = "Loan Repayment Posting"
        verbose_name_plural = "Loan Repayment Postings"
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['loan', 'status']),
            models.Index(fields=['submitted_at']),
            models.Index(fields=['payment_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='loan_repayment_posting_amount_positive'
            ),
        ]

    def __str__(self):
        return f"{self.posting_ref} - {self.loan.loan_number} - ₦{self.amount:,.2f}"

    def save(self, *args, **kwargs):
        """Auto-generate posting reference"""
        if not self.posting_ref:
            self.posting_ref = self.generate_posting_ref()
        if not self.client_id:
            self.client = self.loan.client
        if not self.branch_id:
            self.branch = self.loan.branch
        super().save(*args, **kwargs)

    @staticmethod
    def generate_posting_ref():
        """Generate unique posting reference"""
        from django.utils.crypto import get_random_string
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_suffix = get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        posting_ref = f"LRP{timestamp}{random_suffix}"
        while LoanRepaymentPosting.objects.filter(posting_ref=posting_ref).exists():
            random_suffix = get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
            posting_ref = f"LRP{timestamp}{random_suffix}"
        return posting_ref

    @db_transaction.atomic
    def approve(self, approved_by, transaction_date=None):
        """
        Approve the repayment posting and update the loan

        This method:
        1. Validates the posting can be approved
        2. Calls loan.record_repayment() to update loan balances
        3. Creates a transaction record
        4. Updates posting status and links transaction
        """
        if self.status != 'pending':
            raise ValidationError("Only pending postings can be approved")

        if self.loan.status not in ['active', 'overdue']:
            raise ValidationError(
                f"Cannot approve repayment for loan with status: {self.loan.get_status_display()}"
            )

        if self.amount > self.loan.outstanding_balance:
            raise ValidationError(
                f"Amount (₦{self.amount:,.2f}) exceeds loan outstanding balance "
                f"(₦{self.loan.outstanding_balance:,.2f})"
            )

        # Calculate principal and interest split
        from core.utils.money import MoneyCalculator

        # Use the loan's repayment schedule to determine split
        remaining = self.amount
        interest_portion = Decimal('0.00')
        principal_portion = Decimal('0.00')

        schedule_rows = (
            self.loan.repayment_schedule
            .filter(status__in=['pending', 'partial', 'overdue'])
            .order_by('installment_number')
        )

        if schedule_rows.exists():
            for row in schedule_rows:
                if remaining <= 0:
                    break
                row_int_owed = row.interest_amount - min(row.amount_paid, row.interest_amount)
                row_prin_owed = row.principal_amount - max(
                    row.amount_paid - row.interest_amount, Decimal('0.00')
                )

                int_taken = min(remaining, row_int_owed)
                interest_portion += int_taken
                remaining -= int_taken

                prin_taken = min(remaining, row_prin_owed)
                principal_portion += prin_taken
                remaining -= prin_taken

            principal_portion += remaining  # leftover goes to principal
        else:
            # Pro-rata fallback
            if self.loan.total_repayment > 0:
                interest_ratio = self.loan.total_interest / self.loan.total_repayment
            else:
                interest_ratio = Decimal('0')
            interest_portion = MoneyCalculator.round_money(self.amount * interest_ratio)
            principal_portion = self.amount - interest_portion

        # Store calculated amounts
        self.principal_amount = principal_portion
        self.interest_amount = interest_portion

        # Record repayment on the loan (updates balances, schedule, creates transaction & journal)
        effective_date = transaction_date if transaction_date is not None else self.payment_date
        txn = self.loan.record_repayment(
            amount=self.amount,
            processed_by=approved_by,
            description=f"Repayment posting {self.posting_ref}",
            transaction_date=effective_date,
        )

        # Update posting status and link the transaction created by record_repayment
        self.status = 'approved'
        self.reviewed_by = approved_by
        self.reviewed_at = timezone.now()
        self.transaction = txn
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'transaction',
            'principal_amount', 'interest_amount', 'updated_at'
        ])

    @db_transaction.atomic
    def reject(self, rejected_by, reason=''):
        """Reject the repayment posting"""
        if self.status != 'pending':
            raise ValidationError("Only pending postings can be rejected")

        self.status = 'rejected'
        self.reviewed_by = rejected_by
        self.reviewed_at = timezone.now()
        self.review_notes = reason
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'
        ])


# =============================================================================
# SAVINGS TRANSACTION POSTING MODELS
# =============================================================================

class SavingsDepositPosting(BaseModel):
    posting_type = 'deposit'  # used by templates to distinguish posting type

    """
    Savings Deposit Posting - Staff submit deposits that require approval

    WORKFLOW:
    1. Staff posts a deposit for a savings account
    2. Posting status = 'pending'
    3. Manager/Director/Admin reviews and approves or rejects
    4. On approval: SavingsAccount.deposit() is called, transaction created
    5. On rejection: Nothing happens, posting is marked rejected

    This two-tier system ensures:
    - Accountability: All deposits are tracked before execution
    - Oversight: Managers must approve before account balances are updated
    - Error prevention: Invalid postings caught before affecting accounts
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('cheque', 'Cheque'),
        ('direct_debit', 'Direct Debit'),
    ]

    # =========================================================================
    # CORE FIELDS
    # =========================================================================

    posting_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated posting reference (e.g., SDP20260205143022ABC123)"
    )

    savings_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.PROTECT,
        related_name='deposit_postings',
        help_text="Savings account receiving deposit"
    )

    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='savings_deposit_postings',
        help_text="Client making the deposit"
    )

    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='savings_deposit_postings'
    )

    # =========================================================================
    # AMOUNT
    # =========================================================================

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Deposit amount"
    )

    # =========================================================================
    # PAYMENT DETAILS
    # =========================================================================

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='cash'
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Transaction reference, receipt number, etc."
    )

    payment_details = models.TextField(
        blank=True,
        help_text="Additional payment information"
    )

    payment_date = models.DateField(
        help_text="Date the payment was received"
    )

    # =========================================================================
    # STATUS TRACKING
    # =========================================================================

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    # =========================================================================
    # SUBMISSION TRACKING
    # =========================================================================

    submitted_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='submitted_savings_deposits'
    )

    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    submission_notes = models.TextField(
        blank=True,
        help_text="Notes from staff member submitting the deposit"
    )

    # =========================================================================
    # REVIEW TRACKING
    # =========================================================================

    reviewed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_savings_deposits'
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)

    review_notes = models.TextField(
        blank=True,
        help_text="Notes from reviewer (approval/rejection reason)"
    )

    # =========================================================================
    # TRANSACTION LINK (populated on approval)
    # =========================================================================

    transaction = models.ForeignKey(
        'Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deposit_posting',
        help_text="Transaction created when this posting was approved"
    )

    class Meta:
        ordering = ['-submitted_at']
        verbose_name = "Savings Deposit Posting"
        verbose_name_plural = "Savings Deposit Postings"
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['savings_account', 'status']),
            models.Index(fields=['submitted_at']),
            models.Index(fields=['payment_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='savings_deposit_posting_amount_positive'
            ),
        ]

    def __str__(self):
        return f"{self.posting_ref} - {self.savings_account.account_number} - ₦{self.amount:,.2f}"

    def save(self, *args, **kwargs):
        """Auto-generate posting reference"""
        if not self.posting_ref:
            self.posting_ref = self.generate_posting_ref()
        if not self.client_id:
            self.client = self.savings_account.client
        if not self.branch_id:
            self.branch = self.savings_account.branch
        super().save(*args, **kwargs)

    @staticmethod
    def generate_posting_ref():
        """Generate unique posting reference: SDP + YYYYMMDDHHMMSSxxxxxx"""
        from django.utils.crypto import get_random_string
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_suffix = get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        posting_ref = f"SDP{timestamp}{random_suffix}"
        while SavingsDepositPosting.objects.filter(posting_ref=posting_ref).exists():
            random_suffix = get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
            posting_ref = f"SDP{timestamp}{random_suffix}"
        return posting_ref

    @db_transaction.atomic
    def approve(self, approved_by, transaction_date=None):
        """
        Approve the deposit posting and update the account

        This method:
        1. Validates the posting can be approved
        2. Calls savings_account.deposit() to update balance
        3. Creates a transaction record (done inside deposit())
        4. Updates posting status and links transaction

        Args:
            approved_by: User approving the posting
            transaction_date: Date to record on the Transaction and JournalEntry.
                              Defaults to self.payment_date if not provided.
        """
        if self.status != 'pending':
            raise ValidationError("Only pending postings can be approved")

        if self.savings_account.status not in ['active', 'pending']:
            raise ValidationError(
                f"Cannot approve deposit for account with status: "
                f"{self.savings_account.get_status_display()}"
            )

        # Validate against product limits
        if self.savings_account.savings_product:
            if self.amount < self.savings_account.savings_product.min_deposit_amount:
                raise ValidationError(
                    f"Amount (₦{self.amount:,.2f}) is below minimum deposit amount "
                    f"(₦{self.savings_account.savings_product.min_deposit_amount:,.2f})"
                )

        effective_date = transaction_date if transaction_date is not None else self.payment_date

        # Call account's deposit method (creates transaction internally)
        try:
            txn = self.savings_account.deposit(
                amount=self.amount,
                processed_by=approved_by,
                description=f"Deposit posting {self.posting_ref}",
                transaction_date=effective_date,
            )
        except ValueError as e:
            raise ValidationError(str(e))

        # Update posting status
        self.status = 'approved'
        self.reviewed_by = approved_by
        self.reviewed_at = timezone.now()
        self.transaction = txn
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'transaction', 'updated_at'
        ])

    @db_transaction.atomic
    def reject(self, rejected_by, reason=''):
        """Reject the deposit posting"""
        if self.status != 'pending':
            raise ValidationError("Only pending postings can be rejected")

        self.status = 'rejected'
        self.reviewed_by = rejected_by
        self.reviewed_at = timezone.now()
        self.review_notes = reason
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'
        ])


class SavingsWithdrawalPosting(BaseModel):
    posting_type = 'withdrawal'  # used by templates to distinguish posting type

    """
    Savings Withdrawal Posting - Staff submit withdrawals that require approval

    WORKFLOW:
    1. Staff posts a withdrawal for a savings account
    2. Posting status = 'pending'
    3. Manager/Director/Admin reviews and approves or rejects
    4. On approval: SavingsAccount.withdraw() is called, transaction created
    5. On rejection: Nothing happens, posting is marked rejected

    Additional validations:
    - Check minimum balance requirements
    - Check withdrawal limits from product
    - Check fixed deposit maturity dates
    - Calculate early withdrawal penalties if applicable
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('cheque', 'Cheque'),
    ]

    # =========================================================================
    # CORE FIELDS
    # =========================================================================

    posting_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated posting reference (e.g., SWP20260205143022ABC123)"
    )

    savings_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.PROTECT,
        related_name='withdrawal_postings',
        help_text="Savings account for withdrawal"
    )

    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='savings_withdrawal_postings',
        help_text="Client making the withdrawal"
    )

    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='savings_withdrawal_postings'
    )

    # =========================================================================
    # AMOUNT
    # =========================================================================

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Withdrawal amount"
    )

    # =========================================================================
    # PENALTY TRACKING (for early withdrawal from fixed deposits)
    # =========================================================================

    penalty_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Penalty amount for early withdrawal (calculated on approval)"
    )

    is_early_withdrawal = models.BooleanField(
        default=False,
        help_text="Is this an early withdrawal from fixed deposit?"
    )

    # =========================================================================
    # PAYMENT DETAILS
    # =========================================================================

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='cash'
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Transaction reference, receipt number, etc."
    )

    payment_details = models.TextField(
        blank=True,
        help_text="Additional payment information"
    )

    withdrawal_date = models.DateField(
        help_text="Date of withdrawal"
    )

    # =========================================================================
    # STATUS TRACKING
    # =========================================================================

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    # =========================================================================
    # SUBMISSION TRACKING
    # =========================================================================

    submitted_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='submitted_savings_withdrawals'
    )

    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    submission_notes = models.TextField(
        blank=True,
        help_text="Notes from staff member submitting the withdrawal"
    )

    # =========================================================================
    # REVIEW TRACKING
    # =========================================================================

    reviewed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_savings_withdrawals'
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)

    review_notes = models.TextField(
        blank=True,
        help_text="Notes from reviewer (approval/rejection reason)"
    )

    # =========================================================================
    # TRANSACTION LINK (populated on approval)
    # =========================================================================

    transaction = models.ForeignKey(
        'Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='withdrawal_posting',
        help_text="Transaction created when this posting was approved"
    )

    class Meta:
        ordering = ['-submitted_at']
        verbose_name = "Savings Withdrawal Posting"
        verbose_name_plural = "Savings Withdrawal Postings"
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['savings_account', 'status']),
            models.Index(fields=['submitted_at']),
            models.Index(fields=['withdrawal_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='savings_withdrawal_posting_amount_positive'
            ),
        ]

    def __str__(self):
        return f"{self.posting_ref} - {self.savings_account.account_number} - ₦{self.amount:,.2f}"

    def save(self, *args, **kwargs):
        """Auto-generate posting reference"""
        if not self.posting_ref:
            self.posting_ref = self.generate_posting_ref()
        if not self.client_id:
            self.client = self.savings_account.client
        if not self.branch_id:
            self.branch = self.savings_account.branch
        super().save(*args, **kwargs)

    @staticmethod
    def generate_posting_ref():
        """Generate unique posting reference: SWP + YYYYMMDDHHMMSSxxxxxx"""
        from django.utils.crypto import get_random_string
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_suffix = get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        posting_ref = f"SWP{timestamp}{random_suffix}"
        while SavingsWithdrawalPosting.objects.filter(posting_ref=posting_ref).exists():
            random_suffix = get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')
            posting_ref = f"SWP{timestamp}{random_suffix}"
        return posting_ref

    @db_transaction.atomic
    def approve(self, approved_by, transaction_date=None):
        """
        Approve the withdrawal posting and update the account

        This method:
        1. Validates the withdrawal can be approved
        2. Checks all withdrawal rules (balance, limits, maturity)
        3. Calls savings_account.withdraw() to update balance
        4. Creates a transaction record (done inside withdraw())
        5. Updates posting status and links transaction

        Args:
            approved_by: User approving the posting
            transaction_date: Date to record on the Transaction and JournalEntry.
                              Defaults to self.withdrawal_date if not provided.
        """
        if self.status != 'pending':
            raise ValidationError("Only pending postings can be approved")

        if self.savings_account.status != 'active':
            raise ValidationError(
                f"Cannot approve withdrawal for account with status: "
                f"{self.savings_account.get_status_display()}"
            )

        # Check if withdrawal is allowed (includes all validations)
        can_withdraw, message = self.savings_account.can_withdraw(self.amount)
        if not can_withdraw:
            raise ValidationError(message)

        # Check for early withdrawal penalty
        if (self.savings_account.is_fixed_deposit and
            self.savings_account.maturity_date and
            timezone.now().date() < self.savings_account.maturity_date):

            self.is_early_withdrawal = True

            if self.savings_account.savings_product.early_withdrawal_penalty_rate > 0:
                penalty_rate = self.savings_account.savings_product.early_withdrawal_penalty_rate
                self.penalty_amount = self.amount * (penalty_rate / Decimal('100'))

        effective_date = transaction_date if transaction_date is not None else self.withdrawal_date

        # Call account's withdraw method (creates transaction internally)
        try:
            txn = self.savings_account.withdraw(
                amount=self.amount,
                processed_by=approved_by,
                description=f"Withdrawal posting {self.posting_ref}",
                transaction_date=effective_date,
            )
        except ValueError as e:
            raise ValidationError(str(e))

        # Update posting status
        self.status = 'approved'
        self.reviewed_by = approved_by
        self.reviewed_at = timezone.now()
        self.transaction = txn
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'transaction',
            'penalty_amount', 'is_early_withdrawal', 'updated_at'
        ])

    @db_transaction.atomic
    def reject(self, rejected_by, reason=''):
        """Reject the withdrawal posting"""
        if self.status != 'pending':
            raise ValidationError("Only pending postings can be rejected")

        self.status = 'rejected'
        self.reviewed_by = rejected_by
        self.reviewed_at = timezone.now()
        self.review_notes = reason
        self.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'
        ])


# =============================================================================
# ACCOUNTING SYSTEM - COMPLETE
# =============================================================================

class AccountType(BaseModel):
    """
    Account Type Classification
    
    Five main types:
    - Asset
    - Liability
    - Equity
    - Income
    - Expense
    """
    
    # Constants
    ASSET = 'asset'
    LIABILITY = 'liability'
    EQUITY = 'equity'
    INCOME = 'income'
    EXPENSE = 'expense'
    
    TYPE_CHOICES = [
        (ASSET, 'Asset'),
        (LIABILITY, 'Liability'),
        (EQUITY, 'Equity'),
        (INCOME, 'Income'),
        (EXPENSE, 'Expense'),
    ]
    
    NORMAL_BALANCE_CHOICES = [
        ('debit', 'Debit'),
        ('credit', 'Credit'),
    ]
    
    name = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        unique=True,
        help_text="Account type classification"
    )
    normal_balance = models.CharField(
        max_length=10,
        choices=NORMAL_BALANCE_CHOICES,
        help_text="Normal balance side (debit or credit)"
    )
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Account Type"
        verbose_name_plural = "Account Types"
        ordering = ['name']

    def __str__(self):
        return f"{self.get_name_display()} ({self.normal_balance})"


class AccountCategory(BaseModel):
    """
    Account Categories - Sub-classification
    
    Examples:
    - Assets > Current Assets
    - Assets > Non-Current Assets
    - Liabilities > Current Liabilities
    """
    
    name = models.CharField(max_length=100, help_text="Category name")
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        related_name='categories'
    )
    code_prefix = models.CharField(
        max_length=3,
        unique=True,
        help_text="Code prefix (e.g., '1' for Assets, '182' for Loan Receivables)"
    )
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Account Category"
        verbose_name_plural = "Account Categories"
        ordering = ['code_prefix']

    def __str__(self):
        return f"{self.code_prefix} - {self.name}"


class ChartOfAccounts(BaseModel):
    """
    Chart of Accounts (COA) - All GL accounts
    
    Examples:
    - 14: Cash In Hand
    - 100: Ekondo Bank
    - 182: Loan Receivable
    - 186: Savings Deposits
    - 400: Interest Income
    """
    
    gl_code = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        help_text="GL Code (e.g., '14', '182', '400')"
    )
    account_name = models.CharField(
        max_length=200,
        help_text="Account name"
    )
    
    # Classification
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        related_name='accounts'
    )
    account_category = models.ForeignKey(
        AccountCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='accounts'
    )
    
    # Hierarchy
    parent_account = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sub_accounts',
        help_text="Parent account for hierarchical structure"
    )
    
    # Branch-specific
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gl_accounts',
        help_text="Leave blank for system-wide accounts"
    )
    
    # Properties
    currency = models.CharField(max_length=3, default='NGN')
    is_control_account = models.BooleanField(
        default=False,
        help_text="Is this a control/summary account?"
    )
    is_active = models.BooleanField(default=True)
    allows_manual_entries = models.BooleanField(
        default=True,
        help_text="Can manual journal entries be posted?"
    )
    
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Chart of Account"
        verbose_name_plural = "Chart of Accounts"
        ordering = ['gl_code']
        indexes = [
            models.Index(fields=['gl_code']),
            models.Index(fields=['account_type']),
            models.Index(fields=['is_active']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['gl_code'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_gl_code'
            ),
        ]

    def __str__(self):
        return f"{self.gl_code} - {self.account_name}"

    def get_balance(self, as_of_date=None):
        """
        Calculate current balance
        
        Returns balance based on normal balance type:
        - Debit accounts: Debits - Credits
        - Credit accounts: Credits - Debits
        """
        from django.db.models import Sum, Q
        
        query = Q(account=self, journal_entry__status='posted')
        if as_of_date:
            query &= Q(journal_entry__posting_date__lte=as_of_date)
        
        lines = JournalEntryLine.objects.filter(query)
        debits = lines.aggregate(total=Sum('debit_amount'))['total'] or Decimal('0.00')
        credits = lines.aggregate(total=Sum('credit_amount'))['total'] or Decimal('0.00')
        
        if self.account_type.normal_balance == 'debit':
            return debits - credits
        else:
            return credits - debits

    def get_balance_display(self, as_of_date=None):
        """Get balance formatted with currency"""
        balance = self.get_balance(as_of_date)
        return MoneyCalculator.format_currency(balance)


class JournalEntry(BaseModel):
    """
    Journal Entry Header - Double-entry bookkeeping
    
    Every financial transaction creates a journal entry with:
    - At least 2 lines (debit and credit)
    - Total debits MUST equal total credits
    """
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('posted', 'Posted'),
        ('reversed', 'Reversed'),
        ('rejected', 'Rejected'),
    ]
    
    ENTRY_TYPE_CHOICES = [
        ('manual', 'Manual Entry'),
        ('automatic', 'System Generated'),
        ('loan_disbursement', 'Loan Disbursement'),
        ('loan_repayment', 'Loan Repayment'),
        ('savings_deposit', 'Savings Deposit'),
        ('savings_withdrawal', 'Savings Withdrawal'),
        ('fee_collection', 'Fee Collection'),
        ('reversal', 'Reversal Entry'),
        ('adjustment', 'Adjustment Entry'),
        ('insurance_payout', 'Insurance Payout'),
        ('interbranch_transfer', 'Inter-Branch Transfer'),
    ]
    
    # =========================================================================
    # IDENTIFIERS
    # =========================================================================
    
    journal_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique journal number"
    )
    
    # =========================================================================
    # ENTRY DETAILS
    # =========================================================================
    
    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPE_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )
    
    # =========================================================================
    # DATES
    # =========================================================================
    
    transaction_date = models.DateField(
        help_text="Date of the transaction",
        db_index=True
    )
    posting_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when journal was posted (locked)"
    )
    
    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='journal_entries'
    )
    
    # Links to source transactions
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries',
        help_text="Source transaction (if system-generated)"
    )
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries'
    )
    savings_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries'
    )
    
    # =========================================================================
    # DESCRIPTION
    # =========================================================================
    
    description = models.TextField(help_text="Journal entry description/narration")
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="External reference"
    )
    
    # =========================================================================
    # AUDIT
    # =========================================================================
    
    created_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='created_journals'
    )
    posted_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='posted_journals'
    )
    approved_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_journals'
    )
    
    # =========================================================================
    # REVERSAL
    # =========================================================================
    
    reversed_entry = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversals',
        help_text="Original entry that this reversal applies to"
    )
    
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"
        ordering = ['-transaction_date', '-journal_number']
        indexes = [
            models.Index(fields=['journal_number']),
            models.Index(fields=['transaction_date']),
            models.Index(fields=['status']),
            models.Index(fields=['entry_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['journal_number'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_journal_number'
            ),
        ]

    def __str__(self):
        return f"{self.journal_number} - {self.transaction_date}"

    def save(self, *args, **kwargs):
        if not self.journal_number:
            self.journal_number = self._generate_journal_number()
        super().save(*args, **kwargs)

    def _generate_journal_number(self):
        """Generate unique journal number: JE-YYYYMMDD-XXXXXX using transaction_date"""
        if self.transaction_date:
            import datetime as _dt_mod
            if isinstance(self.transaction_date, _dt_mod.datetime):
                date_str = timezone.localdate(self.transaction_date).strftime('%Y%m%d')
            else:
                date_str = self.transaction_date.strftime('%Y%m%d')
        else:
            date_str = timezone.now().strftime('%Y%m%d')
        random_suffix = get_random_string(6, '0123456789')
        journal_number = f"JE-{date_str}-{random_suffix}"

        while JournalEntry.objects.filter(journal_number=journal_number).exists():
            random_suffix = get_random_string(6, '0123456789')
            journal_number = f"JE-{date_str}-{random_suffix}"

        return journal_number

    def get_total_debits(self):
        """Calculate total debit amount"""
        from django.db.models import Sum
        total = self.lines.aggregate(total=Sum('debit_amount'))['total']
        return total or Decimal('0.00')

    def get_total_credits(self):
        """Calculate total credit amount"""
        from django.db.models import Sum
        total = self.lines.aggregate(total=Sum('credit_amount'))['total']
        return total or Decimal('0.00')

    def is_balanced(self):
        """Check if debits equal credits"""
        debits = self.get_total_debits()
        credits = self.get_total_credits()
        return abs(debits - credits) < Decimal('0.01')

    @db_transaction.atomic
    def post(self, posted_by):
        """
        Post the journal entry (lock it)
        
        Validates:
        - Journal is balanced
        - Has at least 2 lines
        """
        if self.status not in ['draft', 'pending']:
            raise ValueError(f"Cannot post journal with status: {self.get_status_display()}")
        
        if not self.is_balanced():
            raise ValueError(
                f"Journal is not balanced. Debits: {self.get_total_debits()}, "
                f"Credits: {self.get_total_credits()}"
            )
        
        if self.lines.count() < 2:
            raise ValueError("Journal must have at least 2 lines")
        
        self.status = 'posted'
        self.posted_by = posted_by
        self.posting_date = timezone.now().date()
        self.posted_at = timezone.now()
        self.save(update_fields=['status', 'posted_by', 'posting_date', 'posted_at', 'updated_at'])

    @db_transaction.atomic
    def reverse(self, reversed_by, reason=''):
        """Create a reversal journal entry"""
        if self.status != 'posted':
            raise ValueError("Only posted journals can be reversed")
        
        reversal = JournalEntry.objects.create(
            entry_type='reversal',
            transaction_date=timezone.now().date(),
            branch=self.branch,
            description=f"Reversal of {self.journal_number}: {reason}",
            created_by=reversed_by,
            reversed_entry=self,
            status='draft'
        )
        
        # Create opposite lines
        for line in self.lines.all():
            JournalEntryLine.objects.create(
                journal_entry=reversal,
                account=line.account,
                debit_amount=line.credit_amount,  # Swap
                credit_amount=line.debit_amount,  # Swap
                description=f"Reversal: {line.description}",
                client=line.client
            )
        
        # Post reversal immediately
        reversal.post(reversed_by)
        
        # Mark original as reversed
        self.status = 'reversed'
        self.save(update_fields=['status', 'updated_at'])
        
        return reversal


class JournalEntryLine(BaseModel):
    """
    Journal Entry Line - Individual debit/credit lines
    
    Rules:
    - Each line must have EITHER debit OR credit (not both)
    - Total debits must equal total credits per journal
    """
    
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name='journal_lines'
    )
    
    # Amounts (only one should have value)
    debit_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Debit amount (leave 0 if credit)"
    )
    credit_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Credit amount (leave 0 if debit)"
    )
    
    description = models.TextField(blank=True)
    
    # Optional client reference
    client = models.ForeignKey(
        'Client',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_lines',
        help_text="Client reference (optional)"
    )

    class Meta:
        verbose_name = "Journal Entry Line"
        verbose_name_plural = "Journal Entry Lines"
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                check=models.Q(debit_amount__gte=0),
                name='journalline_debit_positive'
            ),
            models.CheckConstraint(
                check=models.Q(credit_amount__gte=0),
                name='journalline_credit_positive'
            ),
        ]

    def __str__(self):
        if self.debit_amount > 0:
            return f"{self.account.gl_code} - Dr: ₦{self.debit_amount:,.2f}"
        else:
            return f"{self.account.gl_code} - Cr: ₦{self.credit_amount:,.2f}"

    def clean(self):
        """Validate that only one of debit or credit has value"""
        super().clean()
        debit  = self.debit_amount  or Decimal('0.00')
        credit = self.credit_amount or Decimal('0.00')

        if debit > 0 and credit > 0:
            raise ValidationError("A line cannot have both debit and credit amounts")

        if debit == 0 and credit == 0:
            raise ValidationError("A line must have either a debit or credit amount")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# =============================================================================
# FROM: supporting_models.py
# =============================================================================

# =============================================================================
# =============================================================================
class Notification(BaseModel):
    """
    User Notifications
    
    ENHANCEMENTS:
    - Inherits from BaseModel
    - Read/unread tracking
    - Urgency levels
    - Related object references
    """
    
    NOTIFICATION_TYPE_CHOICES = [
        ('client_registered', 'New Client Registered'),
        ('client_approved', 'Client Approved'),
        ('client_rejected', 'Client Rejected'),
        ('loan_applied', 'Loan Application Submitted'),
        ('repayment_posted', 'Repayment Pending Approval'),
        ('loan_fees_paid', 'Loan Fees Paid'),
        ('loan_approved', 'Loan Approved'),
        ('loan_rejected', 'Loan Rejected'),
        ('loan_disbursed', 'Loan Disbursed'),
        ('loan_overdue', 'Loan Overdue'),
        ('loan_completed', 'Loan Completed'),
        ('savings_created', 'Savings Account Created'),
        ('savings_approved', 'Savings Account Approved'),
        ('deposit_made', 'Deposit Made'),
        ('withdrawal_made', 'Withdrawal Made'),
        ('deposit_pending', 'Deposit Pending Approval'),
        ('withdrawal_pending', 'Withdrawal Pending Approval'),
        ('transaction_approved', 'Transaction Approved'),
        ('transaction_rejected', 'Transaction Rejected'),
        ('staff_created', 'Staff Account Created'),
        ('group_created', 'Group Created'),
        ('system_alert', 'System Alert'),
        ('assignment_request_pending', 'Assignment Request Pending'),
        ('assignment_request_approved', 'Assignment Request Approved'),
        ('assignment_request_rejected', 'Assignment Request Rejected'),
        ('branch_changed', 'Branch Assignment Updated'),
        ('group_assigned', 'Group Assignment Updated'),
        ('group_removed', 'Removed from Group'),
        ('group_unassigned', 'Group Unassigned from Staff'),
        ('client_unassigned', 'Client Unassigned'),
        ('clients_assigned', 'Multiple Clients Assigned'),
        # Automated background job notifications
        ('savings_maturity',  'Fixed Deposit Maturing'),
        ('loan_penalty_applied', 'Automatic Penalty Applied'),
        # Inter-branch transfers
        ('transfer_requested',       'Transfer Requested'),
        ('transfer_approved',        'Transfer Approved'),
        ('transfer_rejected',        'Transfer Rejected'),
        ('transfer_completed',       'Transfer Completed'),
        # Insurance claims
        ('insurance_claim_filed',    'Insurance Claim Filed'),
        ('insurance_claim_approved', 'Insurance Claim Approved'),
        ('insurance_claim_rejected', 'Insurance Claim Rejected'),
        ('insurance_claim_paid',     'Insurance Claim Paid'),
    ]

    user = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPE_CHOICES,
        db_index=True
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Optional related objects
    related_client = models.ForeignKey(
        'Client',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='related_notifications'
    )
    related_loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    related_savings = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    
    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_urgent = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['is_urgent', 'is_read']),
        ]

    def __str__(self):
        return f"{self.title} - {self.user.get_full_name()}"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def mark_as_unread(self):
        """Mark notification as unread"""
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(update_fields=['is_read', 'read_at'])


# =============================================================================
# GUARANTOR MODEL  (rewritten — now keyed to Loan, not Client)
# =============================================================================

class Guarantor(BaseModel):
    """
    Loan Guarantors

    Created / added when staff create a loan — NOT at client registration.

    Changes vs previous version
    ---------------------------
    CHANGED   client  →  loan  (FK target)
    ADDED     guarantor_type   (internal / external)
    ADDED     branch           (FK — guarantor's branch, for reporting)
    ADDED     guarantee_amount (the amount they are guaranteeing)
    """

    GUARANTOR_TYPE_CHOICES = [
        ('internal', 'Internal'),   # existing client in the system
        ('external', 'External'),   # someone outside the system
    ]

    # =========================================================================
    # RELATIONSHIP  — loan, not client
    # =========================================================================

    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='guarantors',
        help_text="The loan this guarantor is guaranteeing"
    )

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================

    guarantor_type = models.CharField(
        max_length=20,
        choices=GUARANTOR_TYPE_CHOICES,
        default='external',
        help_text="Internal = existing client; External = outside person"
    )

    # if the guarantor happens to be an existing client, link them
    linked_client = models.ForeignKey(
        'Client',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='guarantor_records',
        help_text="Linked client record (only for Internal guarantors)"
    )

    branch = models.ForeignKey(
        'Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='guarantors',
        help_text="Branch associated with the guarantor"
    )

    # =========================================================================
    # GUARANTEE AMOUNT
    # =========================================================================

    guarantee_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Amount this guarantor is guaranteeing"
    )

    # =========================================================================
    # PERSONAL INFORMATION
    # =========================================================================

    name = models.CharField(max_length=255)

    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$')
    phone       = models.CharField(validators=[phone_regex], max_length=17)
    email       = models.EmailField(blank=True)

    relationship = models.CharField(
        max_length=100,
        help_text="Relationship to the loan client"
    )
    address = models.TextField()

    # =========================================================================
    # EMPLOYMENT
    # =========================================================================

    occupation     = models.CharField(max_length=100, blank=True)
    employer       = models.CharField(max_length=100, blank=True)
    monthly_income = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    # =========================================================================
    # IDENTIFICATION
    # =========================================================================

    id_type   = models.CharField(max_length=50, blank=True)
    id_number = models.CharField(max_length=50, blank=True)

    id_card_front = CloudinaryField(
        'id_card_front',
        folder='guarantors/id_cards/front',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Front of the guarantor's ID card"
    )
    id_card_back = CloudinaryField(
        'id_card_back',
        folder='guarantors/id_cards/back',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Back of the guarantor's ID card"
    )
    signature = CloudinaryField(
        'signature',
        folder='guarantors/signatures',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Guarantor's signature image"
    )

    # =========================================================================
    # NOTES
    # =========================================================================

    notes = models.TextField(blank=True)

    # =========================================================================
    # META
    # =========================================================================

    class Meta:
        ordering = ['created_at']
        verbose_name = "Guarantor"
        verbose_name_plural = "Guarantors"
        indexes = [
            models.Index(fields=['loan']),
            models.Index(fields=['guarantor_type']),
            models.Index(fields=['branch']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(guarantee_amount__gte=0),
                name='guarantor_amount_positive'
            ),
        ]

    def __str__(self):
        return f"Guarantor: {self.name} → {self.loan.loan_number}"

    # =========================================================================
    # CLEAN
    # =========================================================================

    def clean(self):
        super().clean()
        errors = {}

        # Internal guarantor must have a linked_client
        if self.guarantor_type == 'internal' and not self.linked_client_id:
            errors['linked_client'] = "An Internal guarantor must be linked to an existing client"

        # External guarantor must NOT have a linked_client
        if self.guarantor_type == 'external' and self.linked_client_id:
            errors['linked_client'] = "An External guarantor should not be linked to a client"

        if errors:
            raise ValidationError(errors)


# =============================================================================
# COLLATERAL MODEL  (brand new)
# =============================================================================

class Collateral(BaseModel):
    """
    Loan Collateral

    Maps to the "Collateral" section visible under the Security tab in the
    reference screenshots (Type / Description / Value).

    Supports document upload (e.g. photos of the collateral, receipts).
    """

    COLLATERAL_TYPE_CHOICES = [
        ('land',            'Land'),
        ('building',        'Building / Property'),
        ('vehicle',         'Vehicle'),
        ('equipment',       'Equipment / Machinery'),
        ('inventory',       'Inventory / Stock'),
        ('bank_guarantee',  'Bank Guarantee'),
        ('insurance_policy','Insurance Policy'),
        ('other',           'Other'),
    ]

    STATUS_CHOICES = [
        ('pending',    'Pending Verification'),
        ('verified',   'Verified'),
        ('rejected',   'Rejected'),
        ('released',   'Released'),
    ]

    # =========================================================================
    # RELATIONSHIP
    # =========================================================================

    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='collaterals',
        help_text="The loan this collateral secures"
    )

    # =========================================================================
    # CLASSIFICATION
    # =========================================================================

    collateral_type = models.CharField(
        max_length=30,
        choices=COLLATERAL_TYPE_CHOICES,
        help_text="Type / category of the collateral"
    )

    # =========================================================================
    # DETAILS
    # =========================================================================

    description = models.TextField(
        help_text="Description of the collateral item"
    )

    value = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Estimated / appraised value of the collateral"
    )

    # =========================================================================
    # OWNER INFO  (may differ from the loan client — e.g. spouse)
    # =========================================================================

    owner_name    = models.CharField(max_length=200, blank=True, help_text="Name of the collateral owner")
    owner_phone   = models.CharField(max_length=17,  blank=True, help_text="Owner phone number")
    owner_address = models.TextField(blank=True,                  help_text="Owner address")

    # =========================================================================
    # LOCATION  (for physical collateral)
    # =========================================================================

    location = models.TextField(
        blank=True,
        help_text="Physical location / address of the collateral"
    )

    # =========================================================================
    # DOCUMENTS
    # =========================================================================

    document = CloudinaryField(
        'collateral_document',
        folder='loans/collateral/documents',
        null=True,
        blank=True,
        resource_type='raw',
        help_text="Supporting document (receipt, title deed, etc.)"
    )
    photo = CloudinaryField(
        'collateral_photo',
        folder='loans/collateral/photos',
        null=True,
        blank=True,
        resource_type='image',
        help_text="Photo of the collateral item"
    )

    # =========================================================================
    # STATUS & VERIFICATION
    # =========================================================================

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    verified_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_collaterals',
        help_text="Staff who verified this collateral"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    # =========================================================================
    # NOTES
    # =========================================================================

    notes = models.TextField(blank=True)

    # =========================================================================
    # META
    # =========================================================================

    class Meta:
        ordering  = ['created_at']
        verbose_name = "Collateral"
        verbose_name_plural = "Collaterals"
        indexes = [
            models.Index(fields=['loan']),
            models.Index(fields=['collateral_type']),
            models.Index(fields=['status']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(value__gte=0),
                name='collateral_value_positive'
            ),
        ]

    def __str__(self):
        return f"{self.get_collateral_type_display()} — ₦{self.value:,.2f} ({self.loan.loan_number})"

    # =========================================================================
    # CLEAN
    # =========================================================================

    def clean(self):
        super().clean()
        errors = {}

        if self.value <= 0:
            errors['value'] = "Collateral value must be greater than zero"

        if errors:
            raise ValidationError(errors)
        


# =============================================================================
# NEXT OF KIN MODEL
# =============================================================================

class NextOfKin(BaseModel):
    """
    Client Next of Kin
    
    ENHANCEMENTS:
    - Inherits from BaseModel
    - One-to-one relationship with Client
    """
    
    client = models.OneToOneField(
        'Client',
        on_delete=models.CASCADE,
        related_name='next_of_kin'
    )
    
    # Personal Information
    name = models.CharField(max_length=255)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$')
    phone = models.CharField(validators=[phone_regex], max_length=17)
    email = models.EmailField(blank=True)
    relationship = models.CharField(max_length=100)
    address = models.TextField()
    
    # Employment
    occupation = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=100, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Next of Kin"
        verbose_name_plural = "Next of Kin"

    def __str__(self):
        return f"NOK: {self.name} for {self.client.full_name}"


# =============================================================================
# ASSIGNMENT REQUEST MODEL
# =============================================================================

class AssignmentRequest(BaseModel, ApprovalWorkflowMixin):
    """
    Assignment Requests - Pending assignments awaiting approval
    
    ENHANCEMENTS:
    - Inherits from BaseModel and ApprovalWorkflowMixin
    - Comprehensive workflow tracking
    - JSON data storage for flexibility
    """
    
    ASSIGNMENT_TYPE_CHOICES = [
        ('client_to_staff', 'Assign Client to Staff'),
        ('client_to_branch', 'Assign Client to Branch'),
        ('client_to_group', 'Assign Client to Group'),
        ('group_to_staff', 'Assign Group to Staff'),
        ('group_to_branch', 'Assign Group to Branch'),
        ('bulk_clients_to_staff', 'Bulk Assign Clients to Staff'),
        ('bulk_clients_to_branch', 'Bulk Assign Clients to Branch'),
        ('bulk_clients_to_group', 'Bulk Assign Clients to Group'),
        ('unassign_client_from_staff', 'Unassign Client from Staff'),
        ('unassign_client_from_branch', 'Unassign Client from Branch'),
        ('unassign_client_from_group', 'Unassign Client from Group'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Assignment Type
    assignment_type = models.CharField(
        max_length=50,
        choices=ASSIGNMENT_TYPE_CHOICES,
        help_text="Type of assignment being requested"
    )
    
    # Status (inherited from ApprovalWorkflowMixin but we override choices)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    # Requester Information
    requested_by = models.ForeignKey(
        'User',
        on_delete=models.CASCADE,
        related_name='assignment_requests_created',
        help_text="User who created this assignment request"
    )
    
    # Branch for isolation
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignment_requests',
        help_text="Branch of the requester (for filtering)"
    )
    
    # Assignment Details (JSON)
    assignment_data = models.JSONField(
        help_text="JSON data containing assignment details"
    )
    
    # Description
    description = models.TextField(
        help_text="Human-readable description of the assignment request"
    )
    reason = models.TextField(
        blank=True,
        help_text="Reason for the assignment (optional)"
    )
    
    # Target References
    target_staff = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignment_requests_as_target_staff',
        limit_choices_to={'user_role__in': ['staff', 'manager']}
    )
    target_branch = models.ForeignKey(
        'Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignment_requests_as_target_branch'
    )
    target_group = models.ForeignKey(
        'ClientGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignment_requests_as_target_group'
    )
    
    # Affected entities count
    affected_count = models.IntegerField(
        default=1,
        help_text="Number of clients/members affected"
    )
    
    # Review Information (inherited from ApprovalWorkflowMixin)
    reviewed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignment_requests_reviewed'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    
    # Execution Information
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_result = models.JSONField(null=True, blank=True)
    
    # Expiration
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Assignment Request"
        verbose_name_plural = "Assignment Requests"
        indexes = [
            models.Index(fields=['status', 'requested_by']),
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['assignment_type', 'status']),
        ]

    def __str__(self):
        return f"{self.get_assignment_type_display()} - {self.status}"
    
    def can_be_approved_by(self, user):
        """Check if user can approve this request"""
        if self.status != 'pending':
            return False
        
        if user == self.requested_by:
            return False
        
        if user.user_role in ['admin', 'director', 'hr']:
            return True

        if user.user_role == 'manager':
            return self.branch == user.branch

        return False
    
    @db_transaction.atomic
    def approve_request(self, approved_by, notes=''):
        """Approve the assignment request"""
        if not self.can_be_approved_by(approved_by):
            raise ValueError("User cannot approve this request")
        
        self.status = 'approved'
        self.reviewed_by = approved_by
        self.reviewed_at = timezone.now()
        self.review_notes = notes
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])
    
    @db_transaction.atomic
    def reject_request(self, rejected_by, notes=''):
        """Reject the assignment request"""
        if not self.can_be_approved_by(rejected_by):
            raise ValueError("User cannot reject this request")
        
        self.status = 'rejected'
        self.reviewed_by = rejected_by
        self.reviewed_at = timezone.now()
        self.review_notes = notes
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])
    
    def cancel(self):
        """Cancel the request"""
        if self.status != 'pending':
            raise ValueError("Can only cancel pending requests")
        
        self.status = 'cancelled'
        self.save(update_fields=['status', 'updated_at'])
    
    def mark_executed(self, result):
        """Mark as executed"""
        self.executed_at = timezone.now()
        self.execution_result = result
        self.save(update_fields=['executed_at', 'execution_result', 'updated_at'])


# =============================================================================
# LOAN REPAYMENT SCHEDULE MODEL
# =============================================================================

class LoanRepaymentSchedule(BaseModel):
    """
    Loan Repayment Schedule - Individual installments
    
    ENHANCEMENTS:
    - Inherits from BaseModel
    - Auto-calculation from loan details
    - Payment tracking
    - Penalty support
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('waived', 'Waived'),
    ]
    
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='repayment_schedule'
    )
    
    # Installment Details
    installment_number = models.IntegerField(
        help_text="Installment sequence number"
    )
    due_date = models.DateField(db_index=True)
    
    # Amounts
    principal_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    interest_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # Payment Tracking
    amount_paid = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    outstanding_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    # Payment Date
    paid_date = models.DateField(null=True, blank=True)
    
    # Penalty
    penalty_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['loan', 'installment_number']
        verbose_name = "Loan Repayment Schedule"
        verbose_name_plural = "Loan Repayment Schedules"
        indexes = [
            models.Index(fields=['loan', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount_paid__lte=models.F('total_amount') + models.F('penalty_amount')),
                name='schedule_amount_paid_valid'
            ),
            models.UniqueConstraint(
                fields=['loan', 'installment_number'],
                name='unique_loan_installment'
            ),
        ]

    def __str__(self):
        return f"{self.loan.loan_number} - Installment {self.installment_number}"
    
    def save(self, *args, **kwargs):
        # Calculate outstanding
        self.outstanding_amount = (self.total_amount + self.penalty_amount) - self.amount_paid
        
        # Update status
        if self.amount_paid >= (self.total_amount + self.penalty_amount):
            self.status = 'paid'
            if not self.paid_date:
                self.paid_date = timezone.now().date()
        elif self.amount_paid > 0:
            self.status = 'partial'
        elif self.due_date < timezone.now().date():
            self.status = 'overdue'
        else:
            self.status = 'pending'
        
        super().save(*args, **kwargs)
    
    @db_transaction.atomic
    def record_payment(self, amount, payment_date=None):
        """Record payment for this installment"""
        amount = Decimal(str(amount))
        
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        
        if amount > self.outstanding_amount:
            raise ValueError(f"Payment exceeds outstanding amount of ₦{self.outstanding_amount:,.2f}")
        
        self.amount_paid += amount
        self.paid_date = payment_date or timezone.now().date()
        self.save()
    
    def calculate_penalty(self, penalty_rate=Decimal('0.01')):
        """Calculate penalty for overdue installment"""
        if self.status == 'overdue':
            days_overdue = (timezone.now().date() - self.due_date).days
            if days_overdue > 0:
                penalty = self.outstanding_amount * penalty_rate * days_overdue / 30
                self.penalty_amount = max(penalty, Decimal('0.00'))
                self.save(update_fields=['penalty_amount'])
    
    @property
    def is_overdue(self):
        """Check if installment is overdue"""
        return self.status == 'overdue' and self.outstanding_amount > 0
    
    @property
    def days_overdue(self):
        """Calculate days overdue"""
        if self.is_overdue:
            return (timezone.now().date() - self.due_date).days
        return 0


# =============================================================================
# LOAN PENALTY MODEL (OPTIONAL)
# =============================================================================

class LoanPenalty(BaseModel):
    """
    Loan Penalties - Track penalties separately
    
    ENHANCEMENTS:
    - Inherits from BaseModel
    - Flexible penalty types
    - Payment tracking
    """
    
    PENALTY_TYPE_CHOICES = [
        ('late_payment', 'Late Payment'),
        ('missed_payment', 'Missed Payment'),
        ('early_settlement', 'Early Settlement'),
        ('other', 'Other'),
    ]
    
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='penalties'
    )
    
    penalty_type = models.CharField(
        max_length=20,
        choices=PENALTY_TYPE_CHOICES
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    reason = models.TextField()
    
    # Payment
    is_paid = models.BooleanField(default=False)
    is_waived = models.BooleanField(default=False)
    paid_date = models.DateField(null=True, blank=True)
    waived_date = models.DateField(null=True, blank=True)
    waived_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='waived_penalties'
    )
    waiver_reason = models.TextField(blank=True)
    
    # Audit
    created_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_penalties'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Loan Penalty"
        verbose_name_plural = "Loan Penalties"

    def __str__(self):
        return f"Penalty: ₦{self.amount:,.2f} for {self.loan.loan_number}"
    
    @db_transaction.atomic
    def waive(self, waived_by, reason=''):
        """Waive this penalty"""
        if self.is_paid:
            raise ValueError("Cannot waive a paid penalty")
        
        if self.is_waived:
            raise ValueError("Penalty already waived")
        
        self.is_waived = True
        self.waived_by = waived_by
        self.waived_date = timezone.now().date()
        self.waiver_reason = reason
        self.save()
    
    @db_transaction.atomic
    def mark_paid(self):
        """Mark penalty as paid"""
        if self.is_waived:
            raise ValueError("Cannot pay a waived penalty")
        
        self.is_paid = True
        self.paid_date = timezone.now().date()
        self.save()





# =============================================================================
# GROUP COLLECTION MODELS
# =============================================================================

class GroupCollectionSession(BaseModel):
    """
    Records a group collection session where staff collects from multiple clients
    
    Workflow:
    1. Staff creates session and enters collections
    2. Session is pending approval
    3. Manager approves or rejects
    4. If approved, all collections are processed
    
    Status Flow: pending → approved/rejected
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    group = models.ForeignKey(
        'ClientGroup',
        on_delete=models.CASCADE,
        related_name='collection_sessions',
        help_text='The client group this collection is for'
    )
    
    collected_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='collection_sessions',
        help_text='Staff member who collected the payments'
    )
    
    collection_date = models.DateField(
        help_text='Date when collections were made'
    )
    
    total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Total amount collected in this session'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    notes = models.TextField(
        blank=True,
        help_text='Additional notes about the collection session'
    )
    
    # Approval fields
    approved_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='approved_collection_sessions',
        null=True,
        blank=True
    )
    
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Rejection fields
    rejected_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='rejected_collection_sessions',
        null=True,
        blank=True
    )
    
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-collection_date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'collected_by']),
            models.Index(fields=['collection_date']),
            models.Index(fields=['group', 'collection_date']),
        ]
    
    def __str__(self):
        return f"{self.group.name} - {self.collection_date} - ₦{self.total_amount:,.2f}"
    
    @property
    def item_count(self):
        """Number of collections in this session"""
        return self.items.count()
    
    @property
    def can_be_edited(self):
        """Can this session still be edited?"""
        return self.status == 'pending'


class GroupCollectionItem(BaseModel):
    """
    Individual collection item within a group collection session
    
    Each item represents one loan payment collected during the session
    """
    
    session = models.ForeignKey(
        'GroupCollectionSession',
        on_delete=models.CASCADE,
        related_name='items',
        help_text='The collection session this item belongs to'
    )
    
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.PROTECT,
        related_name='group_collection_items',
        help_text='The loan being paid'
    )
    
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Amount collected for this loan'
    )
    
    notes = models.CharField(
        max_length=255,
        blank=True,
        help_text='Notes for this specific collection'
    )
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['session', 'loan']),
        ]
    
    def __str__(self):
        return f"{self.loan.loan_number} - ₦{self.amount:,.2f}"


# =============================================================================
# GROUP SAVINGS COLLECTION MODELS (for future use)
# =============================================================================

class GroupSavingsCollectionSession(BaseModel):
    """
    Similar to GroupCollectionSession but for savings deposits
    
    Workflow is identical:
    1. Staff collects savings from group members
    2. Submits for approval
    3. Manager approves
    4. Savings are credited to client accounts
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    group = models.ForeignKey(
        'ClientGroup',
        on_delete=models.CASCADE,
        related_name='savings_collection_sessions'
    )
    
    collected_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='savings_collection_sessions'
    )
    
    collection_date = models.DateField()
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    notes = models.TextField(blank=True)
    
    # Approval fields
    approved_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='approved_savings_sessions',
        null=True,
        blank=True
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Rejection fields
    rejected_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='rejected_savings_sessions',
        null=True,
        blank=True
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-collection_date', '-created_at']
    
    def __str__(self):
        return f"Savings: {self.group.name} - {self.collection_date}"


class GroupSavingsCollectionItem(BaseModel):
    """Individual savings deposit within a group savings collection session"""
    
    session = models.ForeignKey(
        'GroupSavingsCollectionSession',
        on_delete=models.CASCADE,
        related_name='items'
    )
    
    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='group_savings_items'
    )
    
    savings_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.PROTECT,
        related_name='group_collection_items',
        help_text='The savings account to credit'
    )
    
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.client.get_full_name()} - ₦{self.amount:,.2f}"


# =============================================================================
# COMBINED GROUP COLLECTION MODELS
# =============================================================================

class GroupCombinedSession(BaseModel):
    """
    A single collection session that captures both loan repayments and savings
    deposits for group members in one visit.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    group = models.ForeignKey(
        'ClientGroup',
        on_delete=models.CASCADE,
        related_name='combined_sessions'
    )
    collected_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='combined_collection_sessions'
    )
    collection_date = models.DateField()
    total_loan_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_savings_amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='cash')
    payment_reference = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        'User', on_delete=models.PROTECT,
        related_name='approved_combined_sessions',
        null=True, blank=True
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        'User', on_delete=models.PROTECT,
        related_name='rejected_combined_sessions',
        null=True, blank=True
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-collection_date', '-created_at']

    def __str__(self):
        return f"Combined: {self.group.name} - {self.collection_date} - ₦{self.total_amount:,.2f}"

    def get_status_display_class(self):
        mapping = {
            'pending': 'bg-yellow-100 text-yellow-800',
            'approved': 'bg-green-100 text-green-800',
            'rejected': 'bg-red-100 text-red-800',
        }
        return mapping.get(self.status, 'bg-gray-100 text-gray-800')


class GroupCombinedLoanItem(BaseModel):
    """Individual loan repayment within a combined session."""
    session = models.ForeignKey(
        'GroupCombinedSession',
        on_delete=models.CASCADE,
        related_name='loan_items'
    )
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.PROTECT,
        related_name='combined_collection_items'
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='combined_loan_items'
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.client.get_full_name()} - Loan ₦{self.amount:,.2f}"


class GroupCombinedSavingsItem(BaseModel):
    """Individual savings deposit within a combined session."""
    session = models.ForeignKey(
        'GroupCombinedSession',
        on_delete=models.CASCADE,
        related_name='savings_items'
    )
    savings_account = models.ForeignKey(
        'SavingsAccount',
        on_delete=models.PROTECT,
        related_name='combined_collection_items'
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='combined_savings_items'
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.client.get_full_name()} - Savings ₦{self.amount:,.2f}"


# =============================================================================
# FOLLOW-UP TASK MODEL
# =============================================================================

class FollowUpTask(BaseModel):
    """
    Follow-up tasks for overdue loans
    
    Tracks systematic collection efforts
    """
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    FOLLOW_UP_TYPE_CHOICES = [
        ('phone_call', 'Phone Call'),
        ('sms', 'SMS'),
        ('visit', 'Client Visit'),
        ('email', 'Email'),
        ('whatsapp', 'WhatsApp'),
        ('meeting', 'Office Meeting'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='followup_tasks'
    )
    
    follow_up_type = models.CharField(
        max_length=20,
        choices=FOLLOW_UP_TYPE_CHOICES
    )
    
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    assigned_to = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='assigned_followups'
    )
    
    created_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='created_followups'
    )
    
    due_date = models.DateField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(
        help_text='Details about what needs to be done'
    )
    
    outcome = models.TextField(
        blank=True,
        help_text='What happened when the follow-up was completed'
    )
    
    class Meta:
        ordering = ['due_date', '-priority']
        indexes = [
            models.Index(fields=['status', 'assigned_to']),
            models.Index(fields=['due_date', 'status']),
        ]
    
    def __str__(self):
        return f"{self.get_follow_up_type_display()} - {self.loan.loan_number}"
    
    @property
    def is_overdue(self):
        """Is this task overdue?"""
        from django.utils import timezone
        return self.status == 'pending' and self.due_date < timezone.now().date()


# =============================================================================
# PAYMENT PROMISE MODEL
# =============================================================================

class PaymentPromise(BaseModel):
    """
    Track client payment promises
    
    Helps understand client behavior and follow up appropriately
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('kept', 'Promise Kept'),
        ('broken', 'Promise Broken'),
        ('partial', 'Partially Kept'),
    ]
    
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='payment_promises'
    )
    
    promised_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Amount client promised to pay'
    )
    
    promise_date = models.DateField(
        db_index=True,
        help_text='Date client promised to pay'
    )
    
    actual_amount_paid = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Actual amount paid (updated when payment received)'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    recorded_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='recorded_promises'
    )
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-promise_date']
    
    def __str__(self):
        return f"₦{self.promised_amount:,.2f} on {self.promise_date}"
    
    def update_status(self):
        """Update status based on actual payment"""
        if self.actual_amount_paid == 0:
            self.status = 'broken' if self.promise_date < timezone.now().date() else 'pending'
        elif self.actual_amount_paid >= self.promised_amount:
            self.status = 'kept'
        else:
            self.status = 'partial'
        self.save(update_fields=['status', 'updated_at'])


# =============================================================================
# LOAN RESTRUCTURE REQUEST MODEL
# =============================================================================

class LoanRestructureRequest(BaseModel, ApprovalWorkflowMixin):
    """
    Loan restructuring requests
    
    Requires approval from senior management
    """
    
    RESTRUCTURE_TYPE_CHOICES = [
        ('extend_duration', 'Extend Duration'),
        ('reduce_installment', 'Reduce Installment'),
        ('payment_holiday', 'Payment Holiday'),
        ('capitalize_arrears', 'Capitalize Arrears'),
    ]
    
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.CASCADE,
        related_name='restructure_requests'
    )
    
    restructure_type = models.CharField(
        max_length=30,
        choices=RESTRUCTURE_TYPE_CHOICES
    )
    
    # Current loan terms
    current_duration = models.IntegerField(
        help_text='Current loan duration in months'
    )
    current_installment = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        help_text='Current installment amount'
    )
    
    # Proposed terms
    proposed_duration = models.IntegerField(
        null=True,
        blank=True,
        help_text='Proposed loan duration in months'
    )
    proposed_installment = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Proposed installment amount'
    )
    
    reason = models.TextField(
        help_text='Reason for restructuring request'
    )
    
    requested_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='restructure_requests'
    )
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Restructure: {self.loan.loan_number} - {self.get_restructure_type_display()}"


# =============================================================================
# BANK / CASH RECONCILIATION
# =============================================================================

class BankReconciliation(BaseModel):
    """
    Bank / Cash Reconciliation Session.

    Tracks matching of GL journal lines against physical bank statement
    lines to identify discrepancies.  No journal entries are auto-posted
    here — correcting journals must be created manually via the journal
    entry view.
    """

    STATUS_CHOICES = [
        ('draft',       'Draft'),
        ('in_progress', 'In Progress'),
        ('completed',   'Completed'),
    ]

    recon_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated reference, e.g. RECON-20250101-1010"
    )
    gl_account = models.ForeignKey(
        'ChartOfAccounts',
        on_delete=models.PROTECT,
        related_name='reconciliations',
        limit_choices_to={'is_active': True},
        help_text="GL account being reconciled (e.g. 1010, 1020)"
    )
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='reconciliations'
    )
    period_start = models.DateField(help_text="Start of the reconciliation period")
    period_end = models.DateField(help_text="End of the reconciliation period")
    opening_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="GL balance at period_start"
    )
    bank_statement_closing_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Closing balance per bank statement"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='created_reconciliations'
    )
    completed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_reconciliations'
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-period_end', '-created_at']
        verbose_name = "Bank Reconciliation"
        verbose_name_plural = "Bank Reconciliations"

    def __str__(self):
        return f"{self.recon_ref} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.recon_ref:
            self.recon_ref = self._generate_recon_ref()
        super().save(*args, **kwargs)

    def _generate_recon_ref(self):
        from django.utils import timezone as tz
        date_str = tz.now().strftime('%Y%m%d')
        gl_code = self.gl_account.gl_code if self.gl_account_id else 'XXXX'
        base = f"RECON-{date_str}-{gl_code}"
        ref = base
        suffix = 1
        while BankReconciliation.objects.filter(recon_ref=ref).exists():
            ref = f"{base}-{suffix}"
            suffix += 1
        return ref

    def get_gl_closing_balance(self):
        """Calculate GL closing balance for the reconciliation period."""
        from django.db.models import Sum as _Sum
        lines = JournalEntryLine.objects.filter(
            account=self.gl_account,
            journal_entry__status='posted',
            journal_entry__transaction_date__lte=self.period_end,
        )
        total_debits  = lines.aggregate(t=_Sum('debit_amount'))['t']  or Decimal('0.00')
        total_credits = lines.aggregate(t=_Sum('credit_amount'))['t'] or Decimal('0.00')
        return self.opening_balance + total_debits - total_credits

    def get_difference(self):
        """GL closing balance minus bank statement closing balance."""
        return self.get_gl_closing_balance() - self.bank_statement_closing_balance

    def is_complete_eligible(self):
        """Can only mark complete when no unmatched bank statement lines remain."""
        return not self.lines.filter(status='unmatched').exists()


class BankStatementLine(BaseModel):
    """
    A single line from a physical bank statement entered manually.
    Matched to a JournalEntryLine to confirm the GL agrees with the bank.
    """

    STATUS_CHOICES = [
        ('unmatched', 'Unmatched'),
        ('matched',   'Matched'),
        ('disputed',  'Disputed'),
    ]

    reconciliation = models.ForeignKey(
        BankReconciliation,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    line_date = models.DateField()
    description = models.CharField(max_length=300)
    reference = models.CharField(max_length=100, blank=True)
    debit_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Money leaving the bank account"
    )
    credit_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Money entering the bank account"
    )
    matched_gl_line = models.ForeignKey(
        'JournalEntryLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_statement_matches',
        help_text="Matched GL journal line"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='unmatched',
        db_index=True
    )
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['line_date', 'id']
        verbose_name = "Bank Statement Line"
        verbose_name_plural = "Bank Statement Lines"
        constraints = [
            models.UniqueConstraint(
                fields=['matched_gl_line'],
                condition=models.Q(matched_gl_line__isnull=False),
                name='unique_gl_line_match'
            ),
        ]

    def __str__(self):
        return f"{self.line_date} | {self.description[:40]} | {self.status}"

    def clean(self):
        super().clean()
        debit  = self.debit_amount  or Decimal('0.00')
        credit = self.credit_amount or Decimal('0.00')
        if debit > 0 and credit > 0:
            raise ValidationError(
                "A bank statement line cannot have both a debit and credit amount."
            )
        if debit == 0 and credit == 0:
            raise ValidationError(
                "A bank statement line must have either a debit or credit amount."
            )


# =============================================================================
# LOAN INSURANCE CLAIMS
# =============================================================================

class LoanInsuranceClaim(BaseModel):
    """
    Insurance claim filed against a loan where insurance fees were collected.

    Status flow: submitted → under_review → approved → paid (or rejected).

    On approval + payout recording, a journal entry clears the loan receivable:
        Dr 1010 Cash In Hand              [payout_amount]
        Cr 1810 Loan Receivable           [min(payout, outstanding)]
        Cr 1820 Interest Receivable       [remainder, if any]
    """

    CLAIM_TYPE_CHOICES = [
        ('death',            'Death of Borrower'),
        ('disability',       'Permanent Disability'),
        ('fire',             'Fire / Property Damage'),
        ('theft',            'Theft / Burglary'),
        ('natural_disaster', 'Natural Disaster'),
        ('other',            'Other'),
    ]

    STATUS_CHOICES = [
        ('submitted',    'Submitted'),
        ('under_review', 'Under Review'),
        ('approved',     'Approved'),
        ('rejected',     'Rejected'),
        ('paid',         'Paid Out'),
    ]

    claim_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated, e.g. CLAIM-LN2025001-001"
    )
    loan = models.ForeignKey(
        'Loan',
        on_delete=models.PROTECT,
        related_name='insurance_claims'
    )
    claim_type = models.CharField(max_length=30, choices=CLAIM_TYPE_CHOICES)
    event_date = models.DateField(help_text="Date the insured event occurred")
    claim_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Amount being claimed (defaults to loan outstanding balance)"
    )
    payout_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Actual payout received from insurer"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='submitted',
        db_index=True
    )
    description = models.TextField(help_text="Details about the insured event")
    document_references = models.TextField(
        blank=True,
        help_text="Notes about supporting documents submitted"
    )
    filed_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='insurance_claims_filed'
    )
    reviewed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='insurance_claims_reviewed'
    )
    review_notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='insurance_claims_paid'
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    payout_journal = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='insurance_payouts',
        help_text="Journal entry posted when payout is recorded"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Loan Insurance Claim"
        verbose_name_plural = "Loan Insurance Claims"

    def __str__(self):
        return f"{self.claim_ref} — {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.claim_ref:
            self.claim_ref = self._generate_claim_ref()
        super().save(*args, **kwargs)

    def _generate_claim_ref(self):
        loan_num = self.loan.loan_number if self.loan_id else 'UNKNOWN'
        base = f"CLAIM-{loan_num}"
        count = LoanInsuranceClaim.objects.filter(loan_id=self.loan_id).count() + 1
        ref = f"{base}-{count:03d}"
        while LoanInsuranceClaim.objects.filter(claim_ref=ref).exists():
            count += 1
            ref = f"{base}-{count:03d}"
        return ref


# =============================================================================
# INTER-BRANCH TRANSFER
# =============================================================================

class InterBranchTransfer(BaseModel):
    """
    Cash transfer between two branches.

    Two journal entries are posted during the lifecycle:
      1. On approval (at source branch):
            Dr 1950 Interbranch Transfer Clearing   [amount]
            Cr 1010 Cash In Hand                    [amount]
      2. On completion (at destination branch):
            Dr 1010 Cash In Hand                    [amount]
            Cr 1950 Interbranch Transfer Clearing   [amount]
    """

    STATUS_CHOICES = [
        ('pending',   'Pending Approval'),
        ('approved',  'Approved — In Transit'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected',  'Rejected'),
    ]

    transfer_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Auto-generated, e.g. TRF-20250101-001"
    )
    from_branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='outgoing_transfers'
    )
    to_branch = models.ForeignKey(
        'Branch',
        on_delete=models.PROTECT,
        related_name='incoming_transfers'
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        help_text="Amount to transfer"
    )
    purpose = models.CharField(max_length=300)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    requested_by = models.ForeignKey(
        'User',
        on_delete=models.PROTECT,
        related_name='transfers_requested'
    )
    approved_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers_completed',
        help_text="Person confirming receipt at destination branch"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers_rejected'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    source_journal = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_source',
        help_text="Journal posted at source branch on approval"
    )
    destination_journal = models.ForeignKey(
        'JournalEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_destination',
        help_text="Journal posted at destination branch on completion"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Inter-Branch Transfer"
        verbose_name_plural = "Inter-Branch Transfers"
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gte=Decimal('1.00')),
                name='transfer_amount_positive'
            ),
        ]

    def __str__(self):
        return f"{self.transfer_ref}: {self.from_branch} → {self.to_branch}"

    def clean(self):
        super().clean()
        if self.from_branch_id and self.to_branch_id:
            if self.from_branch_id == self.to_branch_id:
                raise ValidationError(
                    "Source and destination branch cannot be the same."
                )

    def save(self, *args, **kwargs):
        if not self.transfer_ref:
            self.transfer_ref = self._generate_transfer_ref()
        super().save(*args, **kwargs)

    def _generate_transfer_ref(self):
        from django.utils import timezone as tz
        date_str = tz.now().strftime('%Y%m%d')
        base = f"TRF-{date_str}"
        count = InterBranchTransfer.objects.filter(
            transfer_ref__startswith=base
        ).count() + 1
        ref = f"{base}-{count:03d}"
        while InterBranchTransfer.objects.filter(transfer_ref=ref).exists():
            count += 1
            ref = f"{base}-{count:03d}"
        return ref



