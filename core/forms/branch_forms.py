"""
Branch Forms
============

Forms for branch management
"""

from django import forms
from django.core.exceptions import ValidationError
from core.models import Branch, User


# CSS Classes for form widgets
TEXT_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
SELECT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
TEXTAREA_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'


class BranchCreateForm(forms.ModelForm):
    """
    Form for creating new branches
    """

    class Meta:
        model = Branch
        fields = [
            'name', 'code', 'address', 'city', 'state',
            'phone', 'email', 'manager'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter branch name',
                'required': True,
            }),
            'code': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter branch code (e.g., MB01, IKJ)',
                'required': True,
            }),
            'address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Enter branch address',
                'required': True,
            }),
            'city': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter city',
            }),
            'state': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter state',
                'required': True,
            }),
            'phone': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '+234XXXXXXXXXX',
                'required': True,
            }),
            'email': forms.EmailInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Enter branch email',
                'required': True,
            }),
            'manager': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
        }

    def __init__(self, *args, **kwargs):
        """Initialize form with manager queryset"""
        super().__init__(*args, **kwargs)

        # Filter managers who are active and don't manage another branch
        self.fields['manager'].queryset = User.objects.filter(
            user_role='manager',
            is_active=True
        )
        self.fields['manager'].empty_label = "Select a manager (optional)"

    def clean_code(self):
        """Validate branch code uniqueness"""
        code = self.cleaned_data.get('code')

        if code:
            # Convert to uppercase
            code = code.upper()

            # Check uniqueness (excluding current instance if updating)
            queryset = Branch.objects.filter(code=code)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise ValidationError("A branch with this code already exists.")

        return code

    def clean_email(self):
        """Validate email uniqueness"""
        email = self.cleaned_data.get('email')

        if email:
            # Check uniqueness (excluding current instance if updating)
            queryset = Branch.objects.filter(email=email)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise ValidationError("A branch with this email already exists.")

        return email

    def clean_phone(self):
        """Validate and normalize phone number"""
        phone = self.cleaned_data.get('phone')

        if phone:
            # Remove spaces and special characters
            phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

            # Add +234 if not present
            if not phone.startswith('+'):
                if phone.startswith('0'):
                    phone = '+234' + phone[1:]
                else:
                    phone = '+234' + phone

        return phone


class BranchUpdateForm(BranchCreateForm):
    """
    Form for updating existing branches
    Inherits all fields from BranchCreateForm
    """

    class Meta(BranchCreateForm.Meta):
        pass

    def __init__(self, *args, **kwargs):
        """Initialize update form"""
        super().__init__(*args, **kwargs)

        # Make code field read-only for existing branches
        if self.instance and self.instance.pk:
            self.fields['code'].disabled = True
            self.fields['code'].help_text = "Branch code cannot be changed"


class BranchSearchForm(forms.Form):
    """
    Form for searching and filtering branches
    """

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
            'placeholder': 'Search by name, code, city, or state...',
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

    state = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 focus:ring-2 focus:ring-primary-200',
            'placeholder': 'Filter by state',
        })
    )
