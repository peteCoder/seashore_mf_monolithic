"""
Base Models and Mixins for Seashore Microfinance
=================================================

Provides:
- Soft delete functionality
- Common timestamp fields
- UUID primary keys
- Audit trail support
"""

from django.db import models
from django.utils import timezone
import uuid


class SoftDeleteManager(models.Manager):
    """Manager that excludes soft-deleted records by default"""
    
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class BaseModel(models.Model):
    """
    Base model with common fields and soft delete support
    
    Features:
    - UUID primary key
    - Timestamp tracking (created, updated, deleted)
    - Soft delete functionality
    - Two managers: objects (non-deleted), all_objects (including deleted)
    """
    
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When this record was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this record was last updated"
    )
    deleted_at = models.DateTimeField(
        null=True, 
        blank=True, 
        db_index=True,
        help_text="When this record was soft-deleted (null = not deleted)"
    )
    
    # Managers
    objects = SoftDeleteManager()
    all_objects = models.Manager()  # Access deleted records
    
    class Meta:
        abstract = True
        ordering = ['-created_at']
    
    def delete(self, using=None, keep_parents=False, hard=False):
        """
        Soft delete by default, unless hard=True
        
        Usage:
            instance.delete()  # Soft delete
            instance.delete(hard=True)  # Hard delete
        """
        if hard:
            super().delete(using=using, keep_parents=keep_parents)
        else:
            self.deleted_at = timezone.now()
            self.save(update_fields=['deleted_at'])
    
    def hard_delete(self):
        """Permanently delete from database"""
        super().delete()
    
    def restore(self):
        """Restore a soft-deleted record"""
        if self.deleted_at:
            self.deleted_at = None
            self.save(update_fields=['deleted_at'])
    
    @property
    def is_deleted(self):
        """Check if record is soft-deleted"""
        return self.deleted_at is not None


class AuditedModel(BaseModel):
    """
    Base model with audit trail support
    
    Tracks who created and who last modified the record
    """
    
    created_by = models.ForeignKey(
        'core.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_created',
        help_text="User who created this record"
    )
    
    updated_by = models.ForeignKey(
        'core.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_updated',
        help_text="User who last updated this record"
    )
    
    class Meta:
        abstract = True


class ApprovalWorkflowMixin(models.Model):
    """
    Mixin for models requiring approval workflow
    
    Provides common approval fields and methods
    """
    
    APPROVAL_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default='draft',
        db_index=True
    )
    
    approved_by = models.ForeignKey(
        'core.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_approved',
        help_text="User who approved this record"
    )
    
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this record was approved"
    )
    
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection"
    )
    
    class Meta:
        abstract = True
    
    def submit_for_approval(self):
        """Submit for approval"""
        if self.approval_status != 'draft':
            raise ValueError(f"Cannot submit for approval from status: {self.approval_status}")
        self.approval_status = 'pending'
        self.save(update_fields=['approval_status'])
    
    def approve(self, approved_by):
        """Approve the record"""
        if self.approval_status != 'pending':
            raise ValueError(f"Cannot approve from status: {self.approval_status}")
        self.approval_status = 'approved'
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.save(update_fields=['approval_status', 'approved_by', 'approved_at'])
    
    def reject(self, rejected_by, reason=''):
        """Reject the record"""
        if self.approval_status != 'pending':
            raise ValueError(f"Cannot reject from status: {self.approval_status}")
        self.approval_status = 'rejected'
        self.approved_by = rejected_by
        self.approved_at = timezone.now()
        self.rejection_reason = reason
        self.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'rejection_reason'])
    
    @property
    def is_approved(self):
        """Check if record is approved"""
        return self.approval_status == 'approved'
    
    @property
    def is_pending(self):
        """Check if record is pending approval"""
        return self.approval_status == 'pending'


class StatusTrackingMixin(models.Model):
    """
    Mixin for models with status tracking
    
    Provides common status fields
    """
    
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Is this record active?"
    )
    
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this record was deactivated"
    )
    
    deactivated_by = models.ForeignKey(
        'core.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_deactivated',
        help_text="User who deactivated this record"
    )
    
    deactivation_reason = models.TextField(
        blank=True,
        help_text="Reason for deactivation"
    )
    
    class Meta:
        abstract = True
    
    def activate(self):
        """Activate the record"""
        self.is_active = True
        self.deactivated_at = None
        self.deactivated_by = None
        self.deactivation_reason = ''
        self.save(update_fields=['is_active', 'deactivated_at', 'deactivated_by', 'deactivation_reason'])
    
    def deactivate(self, deactivated_by=None, reason=''):
        """Deactivate the record"""
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.deactivated_by = deactivated_by
        self.deactivation_reason = reason
        self.save(update_fields=['is_active', 'deactivated_at', 'deactivated_by', 'deactivation_reason'])
