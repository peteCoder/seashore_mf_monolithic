"""
Client Forms
============

Forms for client registration and management with multi-tab step-by-step structure
"""

from django import forms
from django.core.exceptions import ValidationError
from core.models import Client, Branch, ClientGroup
from datetime import date


# CSS Classes for form widgets
TEXT_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
SELECT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
TEXTAREA_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
FILE_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'


class ClientCreateForm(forms.ModelForm):
    """
    Comprehensive client registration form

    This form includes all fields from the Client model organized into sections:
    - Personal Information
    - Contact & Address
    - Identification & Documents
    - Employment & Business
    - Banking & Emergency Contact
    """

    class Meta:
        model = Client
        fields = [
            # Personal Information (Tab 1)
            'first_name', 'last_name', 'nickname', 'email', 'phone', 'alternate_phone',
            'date_of_birth', 'gender', 'marital_status', 'number_of_dependents',
            'education_level',

            # Contact & Address (Tab 2)
            'address', 'city', 'state', 'postal_code', 'country', 'landmark',
            'location', 'residential_status', 'union_location',

            # Identification & Documents (Tab 3)
            'id_type', 'id_number', 'bvn',
            'profile_picture', 'id_card_front', 'id_card_back', 'signature',

            # Employment & Business (Tab 4)
            'occupation', 'employer', 'monthly_income',
            'business_name', 'business_type', 'business_location', 'years_in_business',
            'business_type_2', 'business_address', 'business_landmark',

            # Banking & Emergency Contact (Tab 5)
            'account_number', 'bank_name',
            'emergency_contact_name', 'emergency_contact_phone',
            'emergency_contact_relationship', 'emergency_contact_address',

            # Branch & Group Assignment
            'branch', 'group', 'group_role',

            # Origin
            'origin_channel',
        ]

        widgets = {
            # Personal Information (Tab 1)
            'first_name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter first name',
                'required': True,
            }),
            'last_name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter last name',
                'required': True,
            }),
            'nickname': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter nickname (optional)',
            }),
            'email': forms.EmailInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter email address',
                'required': True,
            }),
            'phone': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '+234XXXXXXXXXX',
                'required': True,
            }),
            'alternate_phone': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '+234XXXXXXXXXX (optional)',
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'type': 'date',
                'required': True,
            }),
            'gender': forms.Select(attrs={
                'class': SELECT_CLASS,
                'required': True,
            }),
            'marital_status': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'number_of_dependents': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Number of dependents',
                'min': 0,
            }),
            'education_level': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),

            # Contact & Address (Tab 2)
            'address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Enter residential address',
                'required': True,
            }),
            'city': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter city',
                'required': True,
            }),
            'state': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter state',
                'required': True,
            }),
            'postal_code': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter postal code (optional)',
            }),
            'country': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'value': 'Nigeria',
            }),
            'landmark': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Nearest landmark',
            }),
            'location': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'residential_status': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'union_location': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Union location (if applicable)',
            }),

            # Identification & Documents (Tab 3)
            'id_type': forms.Select(attrs={
                'class': SELECT_CLASS,
                'required': True,
            }),
            'id_number': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter ID number',
                'required': True,
            }),
            'bvn': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter BVN (11 digits)',
                'maxlength': 11,
            }),
            'profile_picture': forms.FileInput(attrs={
                'class': FILE_INPUT_CLASS,
                'accept': 'image/*',
            }),
            'id_card_front': forms.FileInput(attrs={
                'class': FILE_INPUT_CLASS,
                'accept': 'image/*',
            }),
            'id_card_back': forms.FileInput(attrs={
                'class': FILE_INPUT_CLASS,
                'accept': 'image/*',
            }),
            'signature': forms.FileInput(attrs={
                'class': FILE_INPUT_CLASS,
                'accept': 'image/*',
            }),

            # Employment & Business (Tab 4)
            'occupation': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter occupation',
            }),
            'employer': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter employer name',
            }),
            'monthly_income': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter monthly income',
                'step': '0.01',
                'min': 0,
            }),
            'business_name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter business name',
            }),
            'business_type': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter business type',
            }),
            'business_location': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Enter business location',
            }),
            'years_in_business': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Years in business',
                'min': 0,
            }),
            'business_type_2': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Secondary business type (optional)',
            }),
            'business_address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Business premises address',
            }),
            'business_landmark': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Nearest landmark to business',
            }),

            # Banking & Emergency Contact (Tab 5)
            'account_number': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter account number',
            }),
            'bank_name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter bank name',
            }),
            'emergency_contact_name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Emergency contact name',
            }),
            'emergency_contact_phone': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '+234XXXXXXXXXX',
            }),
            'emergency_contact_relationship': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Relationship to client',
            }),
            'emergency_contact_address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Emergency contact address',
            }),

            # Branch & Group Assignment
            'branch': forms.Select(attrs={
                'class': SELECT_CLASS,
                'required': True,
            }),
            'group': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'group_role': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),

            # Origin
            'origin_channel': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
        }

    def __init__(self, *args, **kwargs):
        """Initialize form with dynamic querysets"""
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filter branches based on user permissions
        if user:
            if user.user_role == 'staff':
                # Staff can only see their own branch
                self.fields['branch'].queryset = Branch.objects.filter(id=user.branch_id)
                self.fields['branch'].initial = user.branch
            elif user.user_role == 'manager':
                # Managers can see their branch
                self.fields['branch'].queryset = Branch.objects.filter(id=user.branch_id)
                self.fields['branch'].initial = user.branch
            else:
                # Directors and Admins can see all branches
                self.fields['branch'].queryset = Branch.objects.filter(is_active=True)

        # Filter active groups only
        self.fields['group'].queryset = ClientGroup.objects.filter(is_active=True)
        self.fields['group'].empty_label = "Select a group (optional)"

        # Profile picture and signature are required when creating a new client
        if not (self.instance and self.instance.pk):
            self.fields['profile_picture'].required = True
            self.fields['signature'].required = True

    def clean_email(self):
        """Validate email uniqueness"""
        email = self.cleaned_data.get('email')

        # Check if email already exists (excluding current instance if updating)
        queryset = Client.objects.filter(email=email)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise ValidationError("A client with this email already exists.")

        return email

    def clean_phone(self):
        """Validate phone number"""
        phone = self.cleaned_data.get('phone')

        if phone:
            # Remove spaces and special characters
            phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

            # Basic validation
            if not phone.startswith('+'):
                # Add +234 if not present
                if phone.startswith('0'):
                    phone = '+234' + phone[1:]
                else:
                    phone = '+234' + phone

        return phone

    def clean_date_of_birth(self):
        """Validate date of birth - client must be at least 18 years old"""
        dob = self.cleaned_data.get('date_of_birth')

        if dob:
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

            if age < 18:
                raise ValidationError("Client must be at least 18 years old.")

            if age > 100:
                raise ValidationError("Please enter a valid date of birth.")

        return dob

    def clean_bvn(self):
        """Validate BVN format"""
        bvn = self.cleaned_data.get('bvn')

        if bvn and len(bvn) != 11:
            raise ValidationError("BVN must be exactly 11 digits.")

        if bvn and not bvn.isdigit():
            raise ValidationError("BVN must contain only digits.")

        return bvn

    def clean(self):
        """Additional cross-field validation"""
        cleaned_data = super().clean()

        # If group is selected, group_role is required
        group = cleaned_data.get('group')
        group_role = cleaned_data.get('group_role')

        if group and not group_role:
            self.add_error('group_role', "Group role is required when a group is selected.")

        return cleaned_data


class ClientUpdateForm(ClientCreateForm):
    """
    Form for updating existing client information
    Inherits all fields from ClientCreateForm
    """

    class Meta(ClientCreateForm.Meta):
        pass

    def __init__(self, *args, **kwargs):
        """Initialize update form"""
        super().__init__(*args, **kwargs)

        # Make some fields read-only for existing clients
        if self.instance and self.instance.pk:
            # Don't allow changing the branch of an existing client directly
            # (should use reassignment request)
            self.fields['branch'].disabled = True


class ClientSearchForm(forms.Form):
    """
    Form for searching and filtering clients
    """

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
            'placeholder': 'Search by name, email, phone, or client ID...',
        })
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        empty_label="All Branches",
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
        })
    )

    status = forms.ChoiceField(
        choices=[
            ('', 'All Status'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        required=False,
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
        })
    )

    approval_status = forms.ChoiceField(
        choices=[
            ('', 'All Approvals'),
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        required=False,
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
        })
    )



class ClientApprovalForm(forms.Form):
    """
    Form for approving/rejecting client applications.
    When approving, also collects the registration fee payment details.
    """

    action = forms.ChoiceField(
        choices=[
            ('approve', 'Approve'),
            ('reject', 'Reject'),
        ],
        widget=forms.RadioSelect(attrs={
            'class': 'mr-2',
        })
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
            'rows': 4,
            'placeholder': 'Add notes for approval/rejection (optional)...',
        })
    )

    # --- Registration fee payment fields (shown only when action = 'approve') ---
    payment_method = forms.ChoiceField(
        choices=[
            ('', '— Select payment method —'),
            ('cash', 'Cash'),
            ('bank_transfer', 'Bank Transfer'),
            ('mobile_money', 'Mobile Money'),
            ('pos', 'POS'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        label='Payment Method',
    )

    fee_reference = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Reference / receipt number (optional)',
        }),
        label='Reference Number',
    )

    def __init__(self, *args, fee_already_paid=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._fee_already_paid = fee_already_paid

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        notes = cleaned_data.get('notes')
        payment_method = cleaned_data.get('payment_method')

        # Require notes for rejection
        if action == 'reject' and not notes:
            self.add_error('notes', "Please provide a reason for rejection.")

        # Require payment method when approving and fee not yet paid
        if action == 'approve' and not self._fee_already_paid and not payment_method:
            self.add_error('payment_method', 'Please select a payment method for the registration fee.')

        return cleaned_data


class AssignStaffForm(forms.Form):
    """
    Form for assigning staff to a client
    """

    staff = forms.ModelChoiceField(
        queryset=None,
        required=True,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        label='Assign Staff Officer',
        help_text='Select a staff member to assign to this client'
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 4,
            'placeholder': 'Add notes about this assignment (optional)...',
        }),
        label='Assignment Notes'
    )

    def __init__(self, *args, **kwargs):
        branch = kwargs.pop('branch', None)
        super().__init__(*args, **kwargs)

        if branch:
            # Only show staff members from the same branch
            from core.models import User
            self.fields['staff'].queryset = User.objects.filter(
                user_role='staff',
                branch=branch,
                is_active=True
            ).order_by('first_name', 'last_name')


class RegistrationFeePaymentForm(forms.Form):
    """
    Form for confirming registration fee payment
    """

    payment_method = forms.ChoiceField(
        choices=[
            ('cash', 'Cash'),
            ('bank_transfer', 'Bank Transfer'),
            ('mobile_money', 'Mobile Money'),
            ('pos', 'POS'),
        ],
        required=True,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        label='Payment Method'
    )

    reference_number = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Enter reference/receipt number (optional)...',
        }),
        label='Reference Number',
        help_text='Transaction reference or receipt number (if applicable)'
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Add any additional notes about this payment (optional)...',
        }),
        label='Payment Notes'
    )