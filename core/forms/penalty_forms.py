"""
Loan Penalty Forms
==================
"""

from django import forms
from core.models import LoanPenalty


TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class LoanPenaltyForm(forms.ModelForm):
    """Create a new penalty record for a loan."""

    class Meta:
        model = LoanPenalty
        fields = ['penalty_type', 'amount', 'reason']
        widgets = {
            'penalty_type': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'amount': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT,
                'min': '0.01',
                'step': '0.01',
                'placeholder': '0.00',
            }),
            'reason': forms.Textarea(attrs={
                'rows': 3,
                'class': TAILWIND_TEXTAREA,
                'placeholder': 'Reason for the penalty (e.g. missed payment on DD/MM/YYYY)',
            }),
        }


class LoanPenaltyWaiveForm(forms.Form):
    """Waive a loan penalty with a reason."""

    waiver_reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Reason for waiving this penalty',
        }),
        label='Waiver Reason',
        help_text='Explain why this penalty is being waived.',
    )
