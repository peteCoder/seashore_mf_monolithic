"""
Accounting Forms
================

Forms for accounting module including reports, journal entries, and chart of accounts management
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from datetime import date, timedelta

from core.models import (
    ChartOfAccounts, JournalEntry, JournalEntryLine,
    Branch, Client, AccountType
)


# =============================================================================
# BASE DATE RANGE FORM
# =============================================================================

class DateRangeForm(forms.Form):
    """Base form for date filtering in reports"""

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='From Date'
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='To Date'
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        # Set defaults if not provided
        if not date_to:
            cleaned_data['date_to'] = timezone.now().date()

        if not date_from:
            # Default to start of current month
            today = timezone.now().date()
            cleaned_data['date_from'] = date(today.year, today.month, 1)

        # Validate date range
        if cleaned_data.get('date_from') and cleaned_data.get('date_to'):
            if cleaned_data['date_from'] > cleaned_data['date_to']:
                raise ValidationError('From Date cannot be after To Date')

        return cleaned_data


# =============================================================================
# TRIAL BALANCE FORM
# =============================================================================

class TrialBalanceForm(DateRangeForm):
    """Form for Trial Balance report parameters"""

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        empty_label='All Branches',
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    account_type = forms.ChoiceField(
        choices=[('', 'All Account Types')] + list(AccountType.TYPE_CHOICES),
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    show_zero_balances = forms.ChoiceField(
        choices=[('no', 'No'), ('yes', 'Yes')],
        required=False,
        initial='no',
        label='Show Zero Balances',
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    def clean_show_zero_balances(self):
        return self.cleaned_data.get('show_zero_balances') == 'yes'


# =============================================================================
# PROFIT & LOSS FORM
# =============================================================================

class ProfitLossForm(DateRangeForm):
    """Form for Profit & Loss Statement parameters"""

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        empty_label='All Branches',
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    comparison_period = forms.ChoiceField(
        choices=[
            ('', 'No Comparison'),
            ('previous_month', 'Previous Month'),
            ('previous_quarter', 'Previous Quarter'),
            ('previous_year', 'Previous Year'),
        ],
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='Compare With'
    )

    show_percentages = forms.BooleanField(
        required=False,
        initial=True,
        label='Show Percentages',
        widget=forms.CheckboxInput(
            attrs={
                'class': 'rounded border-gray-300 text-amber-600 shadow-sm focus:border-amber-500 focus:ring-amber-500'
            }
        )
    )


# =============================================================================
# BALANCE SHEET FORM
# =============================================================================

class BalanceSheetForm(forms.Form):
    """Form for Balance Sheet parameters"""

    as_of_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='As of Date'
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        empty_label='All Branches',
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    comparison_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='Compare With Date'
    )

    def clean(self):
        cleaned_data = super().clean()

        # Default as_of_date to today
        if not cleaned_data.get('as_of_date'):
            cleaned_data['as_of_date'] = timezone.now().date()

        # Validate comparison date
        if cleaned_data.get('comparison_date') and cleaned_data.get('as_of_date'):
            if cleaned_data['comparison_date'] >= cleaned_data['as_of_date']:
                raise ValidationError('Comparison date must be before the as-of date')

        return cleaned_data


# =============================================================================
# GENERAL LEDGER FORM
# =============================================================================

class GeneralLedgerForm(DateRangeForm):
    """Form for General Ledger report parameters"""

    account = forms.ModelChoiceField(
        queryset=ChartOfAccounts.objects.filter(is_active=True).order_by('gl_code'),
        required=True,
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='Account'
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        empty_label='All Branches',
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    show_running_balance = forms.BooleanField(
        required=False,
        initial=True,
        label='Show Running Balance',
        widget=forms.CheckboxInput(
            attrs={
                'class': 'rounded border-gray-300 text-amber-600 shadow-sm focus:border-amber-500 focus:ring-amber-500'
            }
        )
    )


# =============================================================================
# JOURNAL ENTRY SEARCH FORM
# =============================================================================

class JournalEntrySearchForm(DateRangeForm):
    """Form for filtering journal entries"""

    journal_number = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                'placeholder': 'JE-XXXXXX'
            }
        ),
        label='Journal Number'
    )

    entry_type = forms.ChoiceField(
        choices=[
            ('', 'All Types'),
            ('loan_disbursement', 'Loan Disbursement'),
            ('loan_repayment', 'Loan Repayment'),
            ('savings_deposit', 'Savings Deposit'),
            ('savings_withdrawal', 'Savings Withdrawal'),
            ('fee_collection', 'Fee Collection'),
            ('manual_entry', 'Manual Entry'),
            ('reversal', 'Reversal'),
        ],
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    status = forms.ChoiceField(
        choices=[
            ('', 'All Statuses'),
            ('draft', 'Draft'),
            ('pending', 'Pending Approval'),
            ('posted', 'Posted'),
            ('reversed', 'Reversed'),
        ],
        required=False,
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )

    branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        empty_label='All Branches',
        widget=forms.Select(
            attrs={
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        )
    )


# =============================================================================
# MANUAL JOURNAL ENTRY FORM
# =============================================================================

class JournalEntryForm(forms.ModelForm):
    """Form for creating manual journal entries"""

    class Meta:
        model = JournalEntry
        fields = ['entry_type', 'transaction_date', 'branch', 'description', 'reference_number']
        widgets = {
            'entry_type': forms.Select(
                choices=[
                    ('manual_entry', 'Manual Entry'),
                    ('adjustment', 'Adjustment'),
                    ('correction', 'Correction'),
                ],
                attrs={
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
                }
            ),
            'transaction_date': forms.DateInput(
                attrs={
                    'type': 'date',
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
                }
            ),
            'branch': forms.Select(
                attrs={
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'rows': 3,
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                    'placeholder': 'Enter journal entry description...'
                }
            ),
            'reference_number': forms.TextInput(
                attrs={
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                    'placeholder': 'External reference (optional)'
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default date to today
        if not self.instance.pk:
            self.fields['transaction_date'].initial = timezone.now().date()


class JournalEntryLineForm(forms.ModelForm):
    """Form for journal entry lines (used in formset)"""

    class Meta:
        model = JournalEntryLine
        fields = ['account', 'debit_amount', 'credit_amount', 'description', 'client']
        widgets = {
            'account': forms.Select(
                attrs={
                    'class': 'account-select block w-full rounded-md border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
                }
            ),
            'debit_amount': forms.NumberInput(
                attrs={
                    'step': '0.01',
                    'min': '0',
                    'class': 'debit-input block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                    'placeholder': '0.00'
                }
            ),
            'credit_amount': forms.NumberInput(
                attrs={
                    'step': '0.01',
                    'min': '0',
                    'class': 'credit-input block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                    'placeholder': '0.00'
                }
            ),
            'description': forms.TextInput(
                attrs={
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                    'placeholder': 'Line description (optional)'
                }
            ),
            'client': forms.Select(
                attrs={
                    'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # debit_amount and credit_amount are DecimalField without blank=True on the model,
        # so Django makes them required=True by default. We need required=False here because
        # each line only ever fills ONE of the two fields (the other stays empty).
        # The clean() method below enforces that exactly one is non-zero.
        self.fields['debit_amount'].required = False
        self.fields['credit_amount'].required = False

    def clean(self):
        cleaned_data = super().clean()
        debit = cleaned_data.get('debit_amount') or Decimal('0')
        credit = cleaned_data.get('credit_amount') or Decimal('0')

        # Validate only debit OR credit
        if debit > 0 and credit > 0:
            raise ValidationError('Line cannot have both debit and credit amounts')

        if debit == 0 and credit == 0:
            raise ValidationError('Line must have either debit or credit amount')

        # Write normalised values back so the model instance never receives None
        cleaned_data['debit_amount'] = debit
        cleaned_data['credit_amount'] = credit
        return cleaned_data


# Create formset for journal entry lines
from django.forms import inlineformset_factory

JournalEntryLineFormSet = inlineformset_factory(
    JournalEntry,
    JournalEntryLine,
    form=JournalEntryLineForm,
    extra=2,
    min_num=2,
    max_num=2,
    validate_min=False,
    can_delete=False,
)


# =============================================================================
# OPENING BALANCE FORM
# =============================================================================

class OpeningBalanceForm(forms.Form):
    """Post an opening balance to a COA account via a 2-line journal entry."""

    _FIELD_CSS = (
        'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm '
        'focus:border-amber-500 focus:ring-amber-500 sm:text-sm '
        'dark:bg-gray-700 dark:border-gray-600 dark:text-white'
    )

    amount = forms.DecimalField(
        label='Opening Balance Amount (₦)',
        min_value=Decimal('0.01'),
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': _FIELD_CSS,
            'step': '0.01',
            'placeholder': '0.00',
        }),
    )

    as_of_date = forms.DateField(
        label='As-of Date',
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': _FIELD_CSS,
        }),
    )

    offsetting_account = forms.ModelChoiceField(
        label='Offsetting Account (other side of entry)',
        queryset=ChartOfAccounts.objects.filter(is_active=True).order_by('gl_code'),
        help_text='Typically an Equity or Capital account (e.g. "Opening Balance Equity").',
        widget=forms.Select(attrs={'class': _FIELD_CSS}),
    )

    branch = forms.ModelChoiceField(
        label='Branch',
        queryset=Branch.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': _FIELD_CSS}),
    )

    description = forms.CharField(
        label='Description / Narration',
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': _FIELD_CSS,
            'placeholder': 'e.g. Opening balance as at 01 Jan 2026',
        }),
    )

    def __init__(self, *args, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        if account:
            # Pre-fill description and exclude self from offsetting choices
            self.fields['description'].initial = f'Opening balance — {account.account_name}'
            self.fields['offsetting_account'].queryset = (
                ChartOfAccounts.objects.filter(is_active=True)
                .exclude(pk=account.pk)
                .order_by('gl_code')
            )
            if account.branch:
                self.fields['branch'].initial = account.branch


# =============================================================================
# JOURNAL REVERSAL FORM
# =============================================================================

class JournalReversalForm(forms.Form):
    """Form for reversing a posted journal entry"""

    reversal_reason = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                'rows': 4,
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white',
                'placeholder': 'Explain why this journal entry is being reversed...'
            }
        ),
        label='Reversal Reason',
        min_length=10
    )

    reversal_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'block w-full px-3 py-2 rounded-md border border-gray-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-white'
            }
        ),
        label='Reversal Date',
        help_text='Leave blank to use today\'s date'
    )

    def clean_reversal_date(self):
        reversal_date = self.cleaned_data.get('reversal_date')
        if not reversal_date:
            return timezone.now().date()
        return reversal_date
