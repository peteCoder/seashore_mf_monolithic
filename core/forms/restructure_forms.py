"""
Loan Restructure Forms
======================
"""

from django import forms
from core.models import LoanRestructureRequest


TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class LoanRestructureRequestForm(forms.ModelForm):
    """Submit a restructure request for a loan."""

    class Meta:
        model = LoanRestructureRequest
        fields = ['restructure_type', 'proposed_duration', 'proposed_installment', 'reason']
        widgets = {
            'restructure_type': forms.Select(attrs={
                'class': TAILWIND_INPUT,
                'id': 'id_restructure_type',
            }),
            'proposed_duration': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT,
                'min': '1',
                'placeholder': 'New duration in months',
            }),
            'proposed_installment': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT,
                'min': '0.01',
                'step': '0.01',
                'placeholder': '0.00',
            }),
            'reason': forms.Textarea(attrs={
                'rows': 4,
                'class': TAILWIND_TEXTAREA,
                'placeholder': 'Explain the reason for this restructure request',
            }),
        }
        labels = {
            'proposed_duration': 'Proposed New Duration (months)',
            'proposed_installment': 'Proposed New Installment Amount (₦)',
        }

    def clean(self):
        cleaned = super().clean()
        restructure_type = cleaned.get('restructure_type')
        proposed_duration = cleaned.get('proposed_duration')
        proposed_installment = cleaned.get('proposed_installment')

        if restructure_type == 'extend_duration' and not proposed_duration:
            self.add_error('proposed_duration', 'Required for "Extend Duration" requests.')

        if restructure_type == 'reduce_installment' and not proposed_installment:
            self.add_error('proposed_installment', 'Required for "Reduce Installment" requests.')

        if restructure_type == 'payment_holiday' and not proposed_duration:
            self.add_error('proposed_duration', 'Enter the number of months for the payment holiday.')

        return cleaned


class LoanRestructureReviewForm(forms.Form):
    """Approve or reject a restructure request."""

    DECISION_CHOICES = [
        ('approve', 'Approve — Apply the restructure to the loan'),
        ('reject', 'Reject — Do not change the loan terms'),
    ]

    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'mr-2'}),
        label='Decision',
    )
    review_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Notes about this decision (required if rejecting)',
        }),
        label='Review Notes',
    )

    def clean(self):
        cleaned = super().clean()
        decision = cleaned.get('decision')
        notes = cleaned.get('review_notes', '').strip()
        if decision == 'reject' and not notes:
            self.add_error('review_notes', 'Please explain why this request is being rejected.')
        return cleaned
