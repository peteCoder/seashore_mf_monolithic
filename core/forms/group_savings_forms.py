"""
Group Savings Forms
===================
Forms for creating and managing GroupSavingsAccount and GroupSavingsPosting.
"""

from django import forms
from django.utils import timezone

from core.models import GroupSavingsAccount, GroupSavingsPosting, GroupSavingsWithdrawal, SavingsProduct, ClientGroup


class GroupSavingsAccountForm(forms.ModelForm):
    """
    Manual creation form — savings_product is auto-assigned to the Group Savings product.
    Only used when creating an account for a group that doesn't have one yet.
    """
    class Meta:
        model = GroupSavingsAccount
        fields = ['group']
        widgets = {
            'group': forms.Select(attrs={
                'class': (
                    'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
                    'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 '
                    'transition-colors'
                ),
            }),
        }

    def __init__(self, *args, user=None, group=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Groups that already have a pending or active savings account are excluded
        already_have_account = GroupSavingsAccount.objects.filter(
            status__in=['pending', 'active']
        ).values_list('group_id', flat=True)

        if group:
            self.fields['group'].initial = group
            self.fields['group'].widget = forms.HiddenInput()
        elif user and hasattr(user, 'branch') and user.user_role in ('staff', 'manager'):
            self.fields['group'].queryset = ClientGroup.objects.filter(
                branch=user.branch, status='active'
            ).exclude(id__in=already_have_account)
        else:
            self.fields['group'].queryset = ClientGroup.objects.filter(
                status='active'
            ).exclude(id__in=already_have_account)

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get('group')
        if group:
            if GroupSavingsAccount.objects.filter(
                group=group, status__in=['pending', 'active']
            ).exists():
                raise forms.ValidationError(
                    'This group already has a savings account.'
                )
            if not SavingsProduct.objects.filter(product_type='group_savings', is_active=True).exists():
                raise forms.ValidationError(
                    'No active Group Savings product is configured. '
                    'Please create one under Savings Products first.'
                )
        return cleaned


class GroupSavingsPostingForm(forms.Form):
    collection_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
        initial=timezone.now().date,
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-textarea', 'placeholder': 'Optional notes…'}),
    )
    total_amount = forms.DecimalField(
        max_digits=15, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-input', 'readonly': 'readonly', 'step': '0.01'}),
        required=False,
    )


class GroupSavingsWithdrawalForm(forms.ModelForm):
    class Meta:
        model = GroupSavingsWithdrawal
        fields = ['amount', 'withdrawal_date', 'purpose', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': (
                    'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
                    'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors'
                ),
                'step': '0.01', 'min': '0.01', 'placeholder': '0.00',
            }),
            'withdrawal_date': forms.DateInput(attrs={
                'type': 'date',
                'class': (
                    'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
                    'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors'
                ),
            }),
            'purpose': forms.TextInput(attrs={
                'class': (
                    'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
                    'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors'
                ),
                'placeholder': 'e.g. Group investment, emergency fund disbursement…',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': (
                    'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
                    'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors'
                ),
                'placeholder': 'Additional details (optional)…',
            }),
        }


class GroupSavingsWithdrawalApproveForm(forms.Form):
    DECISION_CHOICES = [
        ('approve', 'Approve'),
        ('reject',  'Reject'),
    ]
    decision = forms.ChoiceField(choices=DECISION_CHOICES, widget=forms.RadioSelect)
    transaction_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': (
            'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
            'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
            'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors'
        )}),
        help_text='Defaults to withdrawal date if left blank.',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': (
                'w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2.5 '
                'text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
                'focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-colors'
            ),
            'placeholder': 'Reason for rejection (required when rejecting)…',
        }),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'reject' and not cleaned.get('notes'):
            raise forms.ValidationError('Please provide a reason for rejection.')
        return cleaned


class GroupSavingsPostingApproveForm(forms.Form):
    DECISION_CHOICES = [
        ('approve', 'Approve'),
        ('reject',  'Reject'),
    ]
    decision = forms.ChoiceField(choices=DECISION_CHOICES, widget=forms.RadioSelect)
    transaction_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
        help_text='Defaults to collection date if left blank.',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-textarea', 'placeholder': 'Reason for rejection (required when rejecting)…'}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'reject' and not cleaned.get('notes'):
            raise forms.ValidationError('Please provide a reason for rejection.')
        return cleaned
