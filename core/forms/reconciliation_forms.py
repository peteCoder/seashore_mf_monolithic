"""
Bank Reconciliation Forms
=========================
"""
from django import forms
from core.models import BankReconciliation, BankStatementLine, ChartOfAccounts, Branch

TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class BankReconciliationCreateForm(forms.ModelForm):
    """Create a new bank reconciliation session."""

    class Meta:
        model = BankReconciliation
        fields = [
            'gl_account', 'branch', 'period_start', 'period_end',
            'opening_balance', 'bank_statement_closing_balance', 'notes',
        ]
        widgets = {
            'gl_account': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'branch': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'period_start': forms.DateInput(attrs={'type': 'date', 'class': TAILWIND_INPUT}),
            'period_end': forms.DateInput(attrs={'type': 'date', 'class': TAILWIND_INPUT}),
            'opening_balance': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT, 'step': '0.01', 'placeholder': '0.00',
            }),
            'bank_statement_closing_balance': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT, 'step': '0.01', 'placeholder': '0.00',
            }),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': TAILWIND_TEXTAREA}),
        }
        labels = {
            'bank_statement_closing_balance': 'Bank Statement Closing Balance',
            'opening_balance': 'Opening Balance (GL at period start)',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show cash-type GL accounts
        self.fields['gl_account'].queryset = ChartOfAccounts.objects.filter(
            gl_code__in=['1010', '1020'],
            is_active=True,
        )
        # Limit branches for managers
        if user is not None:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)
            if checker.is_manager() and hasattr(user, 'branch') and user.branch:
                self.fields['branch'].queryset = Branch.objects.filter(
                    id=user.branch.id, is_active=True
                )
            else:
                self.fields['branch'].queryset = Branch.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('period_start')
        end = cleaned.get('period_end')
        if start and end and start > end:
            raise forms.ValidationError("Period start must be on or before period end.")
        return cleaned


class BankStatementLineForm(forms.ModelForm):
    """Add a single bank statement line to a reconciliation."""

    class Meta:
        model = BankStatementLine
        fields = ['line_date', 'description', 'reference', 'debit_amount', 'credit_amount', 'notes']
        widgets = {
            'line_date': forms.DateInput(attrs={'type': 'date', 'class': TAILWIND_INPUT}),
            'description': forms.TextInput(attrs={'class': TAILWIND_INPUT, 'placeholder': 'Bank narration'}),
            'reference': forms.TextInput(attrs={'class': TAILWIND_INPUT, 'placeholder': 'Bank reference (optional)'}),
            'debit_amount': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT, 'step': '0.01', 'min': '0', 'placeholder': '0.00',
            }),
            'credit_amount': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT, 'step': '0.01', 'min': '0', 'placeholder': '0.00',
            }),
            'notes': forms.TextInput(attrs={'class': TAILWIND_INPUT, 'placeholder': 'Notes (optional)'}),
        }

    def clean(self):
        cleaned = super().clean()
        debit  = cleaned.get('debit_amount')  or 0
        credit = cleaned.get('credit_amount') or 0
        if debit > 0 and credit > 0:
            raise forms.ValidationError("A line cannot have both a debit and a credit amount.")
        if debit == 0 and credit == 0:
            raise forms.ValidationError("A line must have either a debit or a credit amount.")
        return cleaned


class MatchingForm(forms.Form):
    """Match a bank statement line to a GL journal line."""
    bank_line_id = forms.UUIDField(widget=forms.HiddenInput())
    gl_line_id   = forms.UUIDField(widget=forms.HiddenInput())
