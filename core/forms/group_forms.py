"""
Client Group Forms
==================

Forms for managing client groups and group memberships
"""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from core.models import ClientGroup, Client, Branch, User, GroupMembershipRequest

# CSS Classes for form widgets
TEXT_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
SELECT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
TEXTAREA_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
CHECKBOX_CLASS = 'w-4 h-4 text-primary-600 bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 rounded focus:ring-primary-500'
SELECT_MULTIPLE_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'


# =============================================================================
# CLIENT GROUP FORM
# =============================================================================

class ClientGroupForm(forms.ModelForm):
    """Form for creating/updating client groups"""

    class Meta:
        model = ClientGroup
        fields = [
            'name', 'description', 'group_type', 'branch', 'loan_officer',
            'meeting_day', 'meeting_frequency', 'meeting_time', 'meeting_location',
            'max_members'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Sunrise Savings Group',
            }),
            'description': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Describe the group purpose and activities',
            }),
            'group_type': forms.Select(attrs={'class': SELECT_CLASS}),
            'branch': forms.Select(attrs={'class': SELECT_CLASS}),
            'loan_officer': forms.Select(attrs={'class': SELECT_CLASS}),
            'meeting_day': forms.Select(attrs={'class': SELECT_CLASS}),
            'meeting_frequency': forms.Select(attrs={'class': SELECT_CLASS}),
            'meeting_time': forms.TimeInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'type': 'time',
            }),
            'meeting_location': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Community Hall, Main Street',
            }),
            'max_members': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Leave empty for unlimited',
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Will be set to the User instance when the field must be locked to one person
        self.locked_loan_officer = None

        if user:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)

            # ── Branch dropdown ───────────────────────────────────────────
            if checker.is_staff():
                self.fields['branch'].queryset = Branch.objects.filter(id=user.branch_id)
                self.fields['branch'].initial = user.branch_id
            elif checker.is_manager():
                self.fields['branch'].queryset = Branch.objects.filter(id=user.branch_id)
            else:
                self.fields['branch'].queryset = Branch.objects.filter(is_active=True)

            # ── Loan officer dropdown ─────────────────────────────────────
            if checker.is_staff():
                # Loan officers see only themselves — locked, cannot be changed
                self.fields['loan_officer'].queryset = User.objects.filter(pk=user.pk)
                self.fields['loan_officer'].initial = user.pk
                self.fields['loan_officer'].required = True
                self.locked_loan_officer = user  # signals template to render read-only

            elif checker.is_manager():
                # Managers see all active loan officers (staff) in their own branch
                self.fields['loan_officer'].queryset = (
                    User.objects
                    .filter(branch_id=user.branch_id, user_role='staff', is_active=True)
                    .order_by('first_name', 'last_name')
                )

            else:
                # Admin / Director see all active loan officers across every branch
                self.fields['loan_officer'].queryset = (
                    User.objects
                    .filter(user_role='staff', is_active=True)
                    .select_related('branch')
                    .order_by('branch__name', 'first_name', 'last_name')
                )

    def clean_loan_officer(self):
        """When the field is locked (staff user), always return the locked user."""
        if self.locked_loan_officer is not None:
            return self.locked_loan_officer
        return self.cleaned_data.get('loan_officer')

    def clean_name(self):
        """Validate name uniqueness"""
        name = self.cleaned_data.get('name')
        if name:
            name = name.title()
            queryset = ClientGroup.objects.filter(name=name)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError("A group with this name already exists.")
        return name

    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()

        # Validate loan officer is from same branch
        branch = cleaned_data.get('branch')
        loan_officer = cleaned_data.get('loan_officer')

        if branch and loan_officer:
            if loan_officer.branch_id != branch.id:
                raise ValidationError({
                    'loan_officer': "Loan officer must be from the same branch as the group."
                })

        # Validate max_members
        max_members = cleaned_data.get('max_members')
        if max_members is not None and max_members < 2:
            raise ValidationError({
                'max_members': "Maximum members must be at least 2."
            })

        return cleaned_data


# =============================================================================
# CLIENT GROUP SEARCH FORM
# =============================================================================

class ClientGroupSearchForm(forms.Form):
    """Form for searching and filtering client groups"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Search by name or code...',
        })
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        empty_label="All Branches"
    )

    group_type = forms.ChoiceField(
        choices=[('', 'All Types')] + ClientGroup.GROUP_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        })
    )

    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + ClientGroup.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        })
    )

    loan_officer = forms.ModelChoiceField(
        queryset=User.objects.filter(
            user_role__in=['staff', 'manager', 'director'],
            is_active=True
        ),
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        empty_label="All Loan Officers"
    )


# =============================================================================
# ADD MEMBER FORM
# =============================================================================

class AddMemberForm(forms.Form):
    """Form for adding a single member to a group"""

    client = forms.ModelChoiceField(
        queryset=Client.objects.none(),
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        help_text="Select a client to add to this group"
    )

    group_role = forms.ChoiceField(
        choices=Client.GROUP_ROLE_CHOICES,
        initial='member',
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        help_text="Role of this member within the group"
    )

    def __init__(self, *args, **kwargs):
        group = kwargs.pop('group', None)
        super().__init__(*args, **kwargs)

        if group:
            # Only show active, approved clients from the same branch who don't belong to any group
            self.fields['client'].queryset = Client.objects.filter(
                branch=group.branch,
                is_active=True,
                approval_status='approved',
                group__isnull=True  # Only clients not in any group
            ).order_by('first_name', 'last_name')

    def clean_client(self):
        """Validate client can be added to group"""
        client = self.cleaned_data.get('client')

        if client and client.group:
            raise ValidationError(f"{client.full_name} already belongs to a group.")

        return client


# =============================================================================
# BULK ADD MEMBERS FORM
# =============================================================================

class BulkAddMembersForm(forms.Form):
    """Form for adding multiple members to a group at once"""

    clients = forms.ModelMultipleChoiceField(
        queryset=Client.objects.none(),
        widget=forms.SelectMultiple(attrs={
            'class': SELECT_MULTIPLE_CLASS,
            'size': '10',
        }),
        help_text="Hold Ctrl/Cmd to select multiple clients"
    )

    default_role = forms.ChoiceField(
        choices=Client.GROUP_ROLE_CHOICES,
        initial='member',
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        help_text="Default role for all selected members (can be changed later)"
    )

    def __init__(self, *args, **kwargs):
        group = kwargs.pop('group', None)
        super().__init__(*args, **kwargs)
        self.group = group

        if group:
            # Clients who already have a pending request for any group are
            # not yet active members (Client.group is still NULL) but should
            # not be selectable again until the request is resolved.
            pending_client_ids = GroupMembershipRequest.objects.filter(
                status='pending'
            ).values_list('client_id', flat=True)

            self.fields['clients'].queryset = Client.objects.filter(
                branch=group.branch,
                is_active=True,
                approval_status='approved',
                group__isnull=True,          # not an active member of any group
            ).exclude(
                id__in=pending_client_ids,   # no outstanding pending request
            ).order_by('first_name', 'last_name')

    def clean_clients(self):
        """Validate clients can be added to group"""
        clients = self.cleaned_data.get('clients')

        if not clients:
            raise ValidationError("Please select at least one client.")

        client_ids = [c.id for c in clients]

        # Guard: client already has an active group membership
        clients_with_groups = [c for c in clients if c.group]
        if clients_with_groups:
            names = ', '.join([c.full_name for c in clients_with_groups])
            raise ValidationError(
                f"The following clients already belong to a group: {names}"
            )

        # Guard: client already has a pending membership request for any group
        pending = (
            GroupMembershipRequest.objects
            .filter(client_id__in=client_ids, status='pending')
            .select_related('client', 'group')
        )
        if pending.exists():
            names = ', '.join(
                f"{p.client.full_name} (pending for {p.group.name})"
                for p in pending
            )
            raise ValidationError(
                f"The following clients already have a pending membership request: {names}"
            )

        return clients


# =============================================================================
# UPDATE MEMBER ROLE FORM
# =============================================================================

class UpdateMemberRoleForm(forms.ModelForm):
    """Form for updating a member's role within a group"""

    class Meta:
        model = Client
        fields = ['group_role']

        widgets = {
            'group_role': forms.Select(attrs={
                'class': SELECT_CLASS,
            })
        }


# =============================================================================
# APPROVE GROUP FORM
# =============================================================================

class ApproveGroupForm(forms.Form):
    """Form for approving/rejecting a group"""

    decision = forms.ChoiceField(
        choices=[
            ('approve', 'Approve Group'),
            ('reject', 'Reject Group'),
        ],
        widget=forms.RadioSelect(attrs={
            'class': 'w-4 h-4 text-primary-600',
        }),
        initial='approve'
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Add any notes or comments about this approval...',
        }),
        help_text="Optional notes about the approval/rejection"
    )


# =============================================================================
# APPROVE MEMBER FORM (for pending members)
# =============================================================================

class ApproveMemberForm(forms.Form):
    """Form for approving a pending member addition"""

    decision = forms.ChoiceField(
        choices=[
            ('approve', 'Approve Member'),
            ('reject', 'Reject Member'),
        ],
        widget=forms.RadioSelect(attrs={
            'class': 'w-4 h-4 text-primary-600',
        }),
        initial='approve'
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Add any notes or comments...',
        }),
        help_text="Optional notes about the approval/rejection"
    )


# =============================================================================
# BULK APPROVE MEMBERS FORM
# =============================================================================

class BulkApproveMembersForm(forms.Form):
    """Form for bulk approving/rejecting pending members"""

    action = forms.ChoiceField(
        choices=[
            ('approve', 'Approve Selected Members'),
            ('reject', 'Reject Selected Members'),
        ],
        widget=forms.RadioSelect(attrs={
            'class': 'w-4 h-4 text-primary-600',
        }),
        initial='approve'
    )

    member_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Add any notes about this bulk action...',
        })
    )
