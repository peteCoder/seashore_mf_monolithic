"""
Payment Promise Forms
=====================
"""

from django import forms
from django.utils import timezone
from core.models import PaymentPromise


TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class PaymentPromiseForm(forms.ModelForm):
    """Create or edit a payment promise."""

    class Meta:
        model = PaymentPromise
        fields = ['promised_amount', 'promise_date', 'notes']
        widgets = {
            'promised_amount': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT,
                'min': '0.01',
                'step': '0.01',
                'placeholder': '0.00',
            }),
            'promise_date': forms.DateInput(attrs={
                'class': TAILWIND_INPUT,
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': TAILWIND_TEXTAREA,
                'placeholder': 'Any notes about this promise (e.g. how the client communicated it)',
            }),
        }

    def clean_promise_date(self):
        promise_date = self.cleaned_data.get('promise_date')
        if promise_date and promise_date < timezone.now().date():
            raise forms.ValidationError('Promise date cannot be in the past.')
        return promise_date


class PaymentPromiseStatusForm(forms.Form):
    """Update the status of a payment promise."""

    STATUS_CHOICES = [
        ('kept', 'Promise Kept — client paid the full amount'),
        ('partial', 'Partially Kept — client paid part of the amount'),
        ('broken', 'Promise Broken — client did not pay'),
    ]

    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'mr-2'}),
        label='Outcome',
    )
    actual_amount_paid = forms.DecimalField(
        min_value=0,
        decimal_places=2,
        max_digits=15,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': TAILWIND_INPUT,
            'min': '0',
            'step': '0.01',
            'placeholder': '0.00',
        }),
        label='Actual Amount Paid',
        help_text='Leave blank if nothing was paid.',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Additional notes about the outcome',
        }),
        label='Notes',
    )
