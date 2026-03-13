"""
Loan Insurance Claim Forms
==========================
"""
from django import forms
from decimal import Decimal
from core.models import LoanInsuranceClaim

TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class InsuranceClaimFileForm(forms.ModelForm):
    """File a new insurance claim against a loan."""

    class Meta:
        model = LoanInsuranceClaim
        fields = ['claim_type', 'event_date', 'claim_amount', 'description', 'document_references']
        widgets = {
            'claim_type': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'event_date': forms.DateInput(attrs={'type': 'date', 'class': TAILWIND_INPUT}),
            'claim_amount': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT, 'step': '0.01', 'min': '0.01', 'placeholder': '0.00',
            }),
            'description': forms.Textarea(attrs={
                'rows': 4, 'class': TAILWIND_TEXTAREA,
                'placeholder': 'Describe the insured event in detail',
            }),
            'document_references': forms.Textarea(attrs={
                'rows': 3, 'class': TAILWIND_TEXTAREA,
                'placeholder': 'List supporting documents (e.g. death certificate ref, police report no.)',
            }),
        }
        labels = {
            'document_references': 'Supporting Documents (references/notes)',
        }


class InsuranceClaimReviewForm(forms.Form):
    """Approve or reject an insurance claim."""

    DECISION_CHOICES = [
        ('approve', 'Approve — Proceed to payout'),
        ('reject',  'Reject — Close the claim'),
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
        if cleaned.get('decision') == 'reject':
            if not cleaned.get('review_notes', '').strip():
                self.add_error('review_notes', 'Please explain why this claim is being rejected.')
        return cleaned


class InsuranceClaimPayoutForm(forms.Form):
    """Record the actual payout received from the insurer."""

    payout_amount = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': TAILWIND_INPUT, 'step': '0.01', 'placeholder': '0.00',
        }),
        label='Payout Amount Received (₦)',
    )
    payout_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Payment reference or additional notes',
        }),
        label='Payout Notes',
    )
