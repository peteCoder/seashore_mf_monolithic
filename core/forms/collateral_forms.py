"""
Collateral Forms
================
Forms for adding, editing, verifying, and releasing loan collaterals.
"""

from django import forms
from core.models import Collateral


class CollateralForm(forms.ModelForm):
    """Add or edit a collateral item."""

    class Meta:
        model = Collateral
        fields = [
            'collateral_type', 'description', 'value',
            'owner_name', 'owner_phone', 'owner_address',
            'location', 'notes',
        ]
        widgets = {
            'collateral_type': forms.Select(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Describe the collateral item in detail',
            }),
            'value': forms.NumberInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'min': '0.01',
                'step': '0.01',
            }),
            'owner_name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Full name of collateral owner',
            }),
            'owner_phone': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': '+234...',
            }),
            'owner_address': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            }),
            'location': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
                'placeholder': 'Physical location of the collateral',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            }),
        }


class CollateralVerifyForm(forms.Form):
    """Verify or reject a collateral item."""

    DECISION_CHOICES = [
        ('verify', 'Verify — Collateral is valid and acceptable'),
        ('reject', 'Reject — Collateral does not meet requirements'),
    ]

    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'mr-2'}),
        label='Decision',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Verification notes (optional)',
        }),
        label='Notes',
    )


class CollateralReleaseForm(forms.Form):
    """Release a verified collateral item back to the owner."""

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            'placeholder': 'Release notes (e.g. loan fully repaid, collateral returned to owner)',
        }),
        label='Release Notes',
    )
