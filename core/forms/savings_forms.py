"""
Savings Forms
=============

Forms for savings account management and transaction posting
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from core.models import (
    SavingsAccount, SavingsProduct, Client, Branch,
    SavingsDepositPosting, SavingsWithdrawalPosting
)
from datetime import date

# CSS Classes for form widgets (matching loan forms)
TEXT_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
SELECT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
TEXTAREA_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
CHECKBOX_CLASS = 'h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded'


# =============================================================================
# SAVINGS ACCOUNT FORMS
# =============================================================================

class SavingsAccountForm(forms.ModelForm):
    """Form for creating/updating savings accounts"""

    class Meta:
        model = SavingsAccount
        fields = [
            'client', 'savings_product', 'branch', 'notes'
        ]
        widgets = {
            'client': forms.Select(attrs={'class': SELECT_CLASS}),
            'savings_product': forms.Select(attrs={'class': SELECT_CLASS}),
            'branch': forms.Select(attrs={'class': SELECT_CLASS}),
            'notes': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Optional notes about this account'
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)

            # Filter clients by permission
            if checker.is_staff():
                self.fields['client'].queryset = Client.objects.filter(
                    assigned_staff=user,
                    is_active=True
                )
            elif checker.is_manager():
                self.fields['client'].queryset = Client.objects.filter(
                    branch=user.branch,
                    is_active=True
                )
            else:
                self.fields['client'].queryset = Client.objects.filter(is_active=True)

            # Branch filtering
            if checker.is_staff() or checker.is_manager():
                self.fields['branch'].queryset = Branch.objects.filter(id=user.branch_id)
                self.fields['branch'].initial = user.branch_id
            else:
                self.fields['branch'].queryset = Branch.objects.filter(is_active=True)

        # Filter savings products to active only
        self.fields['savings_product'].queryset = SavingsProduct.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get('client')
        savings_product = cleaned_data.get('savings_product')

        if not all([client, savings_product]):
            return cleaned_data

        # Check client status
        if not client.is_active:
            self.add_error('client', "Client must be active to open a savings account")

        # Check for duplicate accounts of same type
        if not self.instance.pk:  # Only for new accounts
            existing = SavingsAccount.objects.filter(
                client=client,
                savings_product=savings_product,
                status__in=['pending', 'active']
            ).exists()

            if existing:
                self.add_error('savings_product',
                    f"Client already has an active {savings_product.name} account"
                )

        return cleaned_data


class SavingsAccountSearchForm(forms.Form):
    """Form for searching/filtering savings accounts"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Search by account number, client name, or ID...'
        })
    )

    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All Statuses')] + SavingsAccount.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': SELECT_CLASS})
    )

    savings_product = forms.ModelChoiceField(
        queryset=SavingsProduct.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        empty_label='All Products'
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        empty_label='All Branches'
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        }),
        label='Opened From'
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        }),
        label='Opened To'
    )


class SavingsAccountApprovalForm(forms.Form):
    """Form for approving or rejecting savings account applications"""

    DECISION_CHOICES = [
        ('approve', 'Approve Account'),
        ('reject', 'Reject Account'),
    ]

    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': CHECKBOX_CLASS})
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Optional notes about this decision'
        })
    )

    def __init__(self, *args, **kwargs):
        self.account = kwargs.pop('account', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get('decision')

        if not self.account:
            raise ValidationError("Account instance is required")

        if self.account.status != 'pending':
            raise ValidationError(
                f"Cannot process account with status: {self.account.get_status_display()}"
            )

        if decision == 'reject':
            notes = cleaned_data.get('notes')
            if not notes or len(notes.strip()) < 10:
                self.add_error('notes',
                    "Please provide a reason for rejection (minimum 10 characters)")

        return cleaned_data


# =============================================================================
# DEPOSIT POSTING FORMS
# =============================================================================

class SavingsDepositPostingForm(forms.ModelForm):
    """Form for staff to post a single savings deposit"""

    class Meta:
        model = SavingsDepositPosting
        fields = [
            'savings_account', 'amount', 'payment_method', 'payment_reference',
            'payment_details', 'payment_date', 'submission_notes'
        ]
        widgets = {
            'savings_account': forms.Select(attrs={'class': SELECT_CLASS}),
            'amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '₦ 0.00',
                'step': '0.01',
                'id': 'id_amount'
            }),
            'payment_method': forms.Select(attrs={'class': SELECT_CLASS}),
            'payment_reference': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Receipt number, transaction ID, etc.'
            }),
            'payment_details': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Additional payment information'
            }),
            'payment_date': forms.DateInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'type': 'date'
            }),
            'submission_notes': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Notes about this deposit'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)

            # Filter accounts to active only
            base_queryset = SavingsAccount.objects.filter(
                status__in=['active', 'pending']
            ).select_related('client', 'branch', 'savings_product')

            if checker.is_staff():
                self.fields['savings_account'].queryset = base_queryset.filter(
                    client__assigned_staff=user
                )
            elif checker.is_manager():
                self.fields['savings_account'].queryset = base_queryset.filter(
                    branch=user.branch
                )
            else:
                self.fields['savings_account'].queryset = base_queryset

        # Set default payment date to today
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.now().date()

    def clean(self):
        cleaned_data = super().clean()
        account = cleaned_data.get('savings_account')
        amount = cleaned_data.get('amount')

        if not account or not amount:
            return cleaned_data

        # Validate account status
        if account.status not in ['active', 'pending']:
            self.add_error('savings_account',
                f"Cannot post deposit for account with status: {account.get_status_display()}"
            )

        # Validate amount
        if amount <= 0:
            self.add_error('amount', "Amount must be greater than zero")

        # Validate against product minimum
        if account.savings_product:
            if amount < account.savings_product.min_deposit_amount:
                self.add_error('amount',
                    f"Minimum deposit amount is ₦{account.savings_product.min_deposit_amount:,.2f}"
                )

        return cleaned_data


class BulkSavingsDepositPostingForm(forms.Form):
    """Form for posting multiple deposits at once (bulk collection)"""

    payment_method = forms.ChoiceField(
        choices=SavingsDepositPosting.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': SELECT_CLASS})
    )

    payment_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        }),
        initial=timezone.now().date()
    )

    payment_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Optional: Batch reference'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)


# =============================================================================
# WITHDRAWAL POSTING FORMS
# =============================================================================

class SavingsWithdrawalPostingForm(forms.ModelForm):
    """Form for staff to post a single savings withdrawal"""

    class Meta:
        model = SavingsWithdrawalPosting
        fields = [
            'savings_account', 'amount', 'payment_method', 'payment_reference',
            'payment_details', 'withdrawal_date', 'submission_notes'
        ]
        widgets = {
            'savings_account': forms.Select(attrs={'class': SELECT_CLASS}),
            'amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '₦ 0.00',
                'step': '0.01',
                'id': 'id_amount'
            }),
            'payment_method': forms.Select(attrs={'class': SELECT_CLASS}),
            'payment_reference': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Receipt number, transaction ID, etc.'
            }),
            'payment_details': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Additional payment information'
            }),
            'withdrawal_date': forms.DateInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'type': 'date'
            }),
            'submission_notes': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Notes about this withdrawal'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)

            # Filter accounts to active only
            base_queryset = SavingsAccount.objects.filter(
                status='active'
            ).select_related('client', 'branch', 'savings_product')

            if checker.is_staff():
                self.fields['savings_account'].queryset = base_queryset.filter(
                    client__assigned_staff=user
                )
            elif checker.is_manager():
                self.fields['savings_account'].queryset = base_queryset.filter(
                    branch=user.branch
                )
            else:
                self.fields['savings_account'].queryset = base_queryset

        # Set default withdrawal date to today
        if not self.instance.pk:
            self.fields['withdrawal_date'].initial = timezone.now().date()

    def clean(self):
        cleaned_data = super().clean()
        account = cleaned_data.get('savings_account')
        amount = cleaned_data.get('amount')

        if not account or not amount:
            return cleaned_data

        # Validate account status
        if account.status != 'active':
            self.add_error('savings_account',
                f"Cannot post withdrawal for account with status: {account.get_status_display()}"
            )

        # Validate amount
        if amount <= 0:
            self.add_error('amount', "Amount must be greater than zero")

        # Check if withdrawal is allowed (basic check)
        can_withdraw, message = account.can_withdraw(amount)
        if not can_withdraw:
            self.add_error('amount', message)

        return cleaned_data


class BulkSavingsWithdrawalPostingForm(forms.Form):
    """Form for posting multiple withdrawals at once"""

    payment_method = forms.ChoiceField(
        choices=SavingsWithdrawalPosting.PAYMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': SELECT_CLASS})
    )

    withdrawal_date = forms.DateField(
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        }),
        initial=timezone.now().date()
    )

    payment_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Optional: Batch reference'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)


# =============================================================================
# TRANSACTION APPROVAL FORMS
# =============================================================================

class ApproveSavingsTransactionForm(forms.Form):
    """Form for approving or rejecting a savings transaction posting"""

    DECISION_CHOICES = [
        ('approve', 'Approve Transaction'),
        ('reject', 'Reject Transaction'),
    ]

    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': CHECKBOX_CLASS})
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Optional notes about this decision'
        })
    )

    def __init__(self, *args, **kwargs):
        self.posting = kwargs.pop('posting', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get('decision')

        if not self.posting:
            raise ValidationError("Posting instance is required")

        if self.posting.status != 'pending':
            raise ValidationError(
                f"Cannot process posting with status: {self.posting.get_status_display()}"
            )

        if decision == 'reject':
            notes = cleaned_data.get('notes')
            if not notes or len(notes.strip()) < 10:
                self.add_error('notes',
                    "Please provide a reason for rejection (minimum 10 characters)")

        return cleaned_data
