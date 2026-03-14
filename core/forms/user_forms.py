"""
User Management Forms
=====================

Forms for managing users, staff assignments, and user profiles
"""

from django import forms
from core.models import User, Branch


# =============================================================================
# TAILWIND CSS CLASSES
# =============================================================================

INPUT_CLASS = (
    "w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 "
    "focus:ring-2 focus:ring-primary-500 focus:border-primary-500 "
    "bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
)

SELECT_CLASS = (
    "w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 "
    "focus:ring-2 focus:ring-primary-500 focus:border-primary-500 "
    "bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
)

TEXTAREA_CLASS = (
    "w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 "
    "focus:ring-2 focus:ring-primary-500 focus:border-primary-500 "
    "bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
)


# =============================================================================
# USER UPDATE FORM (For Admins/Directors to edit other users)
# =============================================================================

class UserCreateForm(forms.ModelForm):
    """
    Form for admins/directors to create new staff users.
    employee_id (Staff ID) is required and pre-populated with the next
    auto-generated value; the admin can override it.
    """
    employee_id = forms.CharField(
        label='Staff ID',
        required=True,
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASS,
            'placeholder': 'e.g., EMP001',
        }),
        help_text='Unique Staff ID used to log in. Auto-generated — you may change it.',
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASS,
            'placeholder': 'Enter password...',
        })
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASS,
            'placeholder': 'Confirm password...',
        })
    )

    class Meta:
        model = User
        fields = [
            'employee_id', 'first_name', 'last_name', 'email', 'phone',
            'user_role', 'branch', 'designation', 'department',
            'address',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Enter first name...',
            }),
            'last_name': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Enter last name...',
            }),
            'email': forms.EmailInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'user@example.com',
            }),
            'phone': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': '+234...',
            }),
            'user_role': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'branch': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'designation': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'e.g., Loan Officer, Branch Manager',
            }),
            'department': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Enter address...',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
        self.fields['phone'].required = True
        self.fields['user_role'].required = True
        self.fields['branch'].required = True
        self.fields['designation'].required = False
        self.fields['department'].required = False
        self.fields['address'].required = False
        self.fields['branch'].queryset = Branch.objects.filter(is_active=True).order_by('name')

    def clean_employee_id(self):
        employee_id = self.cleaned_data.get('employee_id', '').strip().upper()
        if not employee_id:
            raise forms.ValidationError("Staff ID is required.")
        qs = User.objects.filter(employee_id=employee_id)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with this Staff ID already exists.")
        return employee_id

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        if password1 and len(password1) < 8:
            raise forms.ValidationError("Password must be at least 8 characters long")
        return password2

    def clean_email(self):
        email = self.cleaned_data.get('email')
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with this email already exists")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.is_active = True
        user.is_approved = True
        user.is_staff = True
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    """
    Form for admins/directors to update user information.
    Includes employee_id (Staff ID) so it can be corrected if needed.
    """

    class Meta:
        model = User
        fields = [
            'employee_id',
            'first_name',
            'last_name',
            'email',
            'phone',
            'user_role',
            'branch',
            'is_active',
            'address',
            'profile_picture',
        ]
        widgets = {
            'employee_id': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'e.g., EMP001',
            }),
            'first_name': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Enter first name...',
            }),
            'last_name': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Enter last name...',
            }),
            'email': forms.EmailInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'user@example.com',
            }),
            'phone': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': '+234...',
            }),
            'user_role': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'branch': forms.Select(attrs={
                'class': SELECT_CLASS,
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'w-4 h-4 text-primary-600 bg-gray-100 border-gray-300 rounded focus:ring-primary-500',
            }),
            'address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Enter address...',
            }),
            'profile_picture': forms.ClearableFileInput(attrs={
                'class': 'block w-full text-sm text-gray-500 dark:text-gray-400 '
                         'file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 '
                         'file:text-sm file:font-semibold file:bg-primary-50 file:text-primary-700 '
                         'dark:file:bg-primary-900 dark:file:text-primary-300 '
                         'hover:file:bg-primary-100 dark:hover:file:bg-primary-800',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee_id'].required = True
        self.fields['employee_id'].label = 'Staff ID'
        self.fields['employee_id'].help_text = 'Unique Staff ID used to log in.'
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
        self.fields['phone'].required = True
        self.fields['user_role'].required = True
        self.fields['branch'].required = True
        self.fields['address'].required = False
        self.fields['profile_picture'].required = False

    def clean_employee_id(self):
        employee_id = self.cleaned_data.get('employee_id', '').strip().upper()
        if not employee_id:
            raise forms.ValidationError("Staff ID is required.")
        qs = User.objects.filter(employee_id=employee_id)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with this Staff ID already exists.")
        return employee_id


# =============================================================================
# USER PROFILE UPDATE FORM (For users to edit their own profiles)
# =============================================================================

class UserProfileUpdateForm(forms.ModelForm):
    """
    Form for users to update their own profile information
    Excludes sensitive fields like email, names, role, branch
    """

    class Meta:
        model = User
        fields = [
            'phone',
            'address',
            'profile_picture',
        ]
        widgets = {
            'phone': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': '+234...',
            }),
            'address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Enter your address...',
            }),
            'profile_picture': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-gray-900 dark:text-gray-300 '
                         'border border-gray-300 dark:border-gray-600 rounded-lg cursor-pointer '
                         'bg-gray-50 dark:bg-gray-700 focus:outline-none',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = True
        self.fields['address'].required = False
        self.fields['profile_picture'].required = False


# =============================================================================
# ASSIGN BRANCH FORM
# =============================================================================

class AssignBranchForm(forms.Form):
    """
    Form for assigning a user to a branch
    """

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True).order_by('name'),
        required=True,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        label='Branch',
        help_text='Select the branch to assign this user to'
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Add any notes about this assignment (optional)...',
        }),
        label='Assignment Notes'
    )


# =============================================================================
# USER SEARCH FORM
# =============================================================================

class UserSearchForm(forms.Form):
    """
    Form for searching and filtering users
    """

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASS,
            'placeholder': 'Search by name, Staff ID, email, or phone...',
        }),
        label='Search'
    )

    role = forms.ChoiceField(
        required=False,
        choices=[('', 'All Roles')] + User.ROLE_CHOICES,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        label='Role'
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True).order_by('name'),
        required=False,
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        label='Branch',
        empty_label='All Branches'
    )

    status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Status'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        widget=forms.Select(attrs={
            'class': SELECT_CLASS,
        }),
        label='Status'
    )


# =============================================================================
# ADMIN CHANGE PASSWORD FORM
# =============================================================================

class AdminChangePasswordForm(forms.Form):
    """
    Allows an admin/director to set a new password for any staff member.
    No old-password confirmation required — this is an admin override.
    """
    password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASS,
            'placeholder': 'Enter new password...',
            'autocomplete': 'new-password',
        })
    )
    password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASS,
            'placeholder': 'Confirm new password...',
            'autocomplete': 'new-password',
        })
    )

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match.")
        if password1 and len(password1) < 8:
            raise forms.ValidationError("Password must be at least 8 characters long.")
        return password2
