"""
Product Forms
=============

Forms for managing loan and savings products
"""

from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from core.models import LoanProduct, SavingsProduct, ChartOfAccounts

# Rate fields stored as decimal fractions in the DB (0.035 = 3.5%).
# The form displays and accepts them as percentages (3.5) and converts on save.
_DECIMAL_PCT_FIELDS = [
    'monthly_interest_rate',
    'risk_premium_rate',
    'rp_income_rate',
    'tech_fee_rate',
    'early_repayment_penalty_rate',
]

# Amount fields where users may type comma thousand-separators (e.g. 1,000,000).
_AMOUNT_FIELDS = [
    'min_principal_amount', 'max_principal_amount', 'loan_form_fee_amount',
]


# CSS Classes for form widgets
TEXT_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
SELECT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
TEXTAREA_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
CHECKBOX_CLASS = 'w-4 h-4 text-primary-600 bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 rounded focus:ring-primary-500'


# =============================================================================
# LOAN PRODUCT FORMS
# =============================================================================

class LoanProductForm(forms.ModelForm):
    """Form for creating/updating loan products"""

    class Meta:
        model = LoanProduct
        fields = [
            'code', 'name', 'description', 'loan_type', 'gl_code',
            'monthly_interest_rate', 'annual_interest_rate', 'interest_calculation_method',
            'risk_premium_enabled', 'risk_premium_rate', 'risk_premium_calculation',
            'rp_income_enabled', 'rp_income_rate', 'rp_income_calculation',
            'tech_fee_enabled', 'tech_fee_rate', 'tech_fee_calculation',
            'loan_form_fee_enabled', 'loan_form_fee_amount',
            'min_principal_amount', 'max_principal_amount',
            'min_duration_months', 'max_duration_months',
            'allow_early_repayment', 'early_repayment_penalty_rate', 'grace_period_days',
            'repayment_frequency',
            'required_guarantors',
            'min_client_age', 'max_client_age',
            'loan_maintenance_fee_enabled', 'loan_maintenance_fee_amount',
        ]

        widgets = {
            'code': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., THR-STD, BUS-001',
            }),
            'name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Thrift Loan - Standard',
            }),
            'description': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Product description and features',
            }),
            'loan_type': forms.Select(attrs={'class': SELECT_CLASS}),
            # gl_code — overridden as ChoiceField in __init__; no widget entry needed here
            'monthly_interest_rate': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '3.50',
            }),
            'annual_interest_rate': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '42.00',
            }),
            'interest_calculation_method': forms.Select(attrs={'class': SELECT_CLASS}),
            'risk_premium_enabled': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
            'risk_premium_rate': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '1.50',
            }),
            'risk_premium_calculation': forms.Select(attrs={'class': SELECT_CLASS}),
            'rp_income_enabled': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
            'rp_income_rate': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '1.50',
            }),
            'rp_income_calculation': forms.Select(attrs={'class': SELECT_CLASS}),
            'tech_fee_enabled': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
            'tech_fee_rate': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '1.50',
            }),
            'tech_fee_calculation': forms.Select(attrs={'class': SELECT_CLASS}),
            'loan_form_fee_enabled': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
            'loan_form_fee_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'min_principal_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'max_principal_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'min_duration_months': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
            }),
            'max_duration_months': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
            }),
            'allow_early_repayment': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
            'early_repayment_penalty_rate': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '0.00',
            }),
            'grace_period_days': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
            }),
            'repayment_frequency': forms.Select(attrs={'class': SELECT_CLASS}),
            'required_guarantors': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'min': '0',
                'step': '1',
            }),
            'min_client_age': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'min': '18',
                'step': '1',
            }),
            'max_client_age': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'min': '18',
                'step': '1',
            }),
            'loan_maintenance_fee_enabled': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
            'loan_maintenance_fee_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '200.00',
            }),
        }

    # Override gl_code as a ChoiceField so users pick from the Chart of Accounts
    gl_code = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        label='GL Account',
        help_text='The general ledger account this loan product posts income/balances to.',
    )

    def __init__(self, *args, **kwargs):
        # Strip commas from amount fields before Django parses them
        # (users sometimes type "1,000,000" with thousand separators).
        if args:
            data = args[0]
            if hasattr(data, 'copy'):
                data = data.copy()
                for fname in _AMOUNT_FIELDS:
                    if fname in data:
                        data[fname] = str(data[fname]).replace(',', '')
                args = (data,) + args[1:]

        super().__init__(*args, **kwargs)

        # Build dropdown choices from active ChartOfAccounts records
        # Displayed as: "1010 — Cash In Hand"
        gl_choices = [('', '— Select GL Account (optional) —')]
        accounts = (
            ChartOfAccounts.objects
            .filter(is_active=True)
            .order_by('gl_code')
            .values_list('gl_code', 'account_name')
        )
        gl_choices += [(code, f'{code} \u2014 {name}') for code, name in accounts]
        self.fields['gl_code'].choices = gl_choices

        # Rate fields are stored in the DB as decimal fractions (0.035 = 3.5%).
        # Multiply by 100 so the form shows and accepts plain percentages (3.5).
        if self.instance and self.instance.pk:
            for fname in _DECIMAL_PCT_FIELDS:
                val = getattr(self.instance, fname, None)
                if val is not None:
                    self.initial[fname] = (Decimal(str(val)) * 100).normalize()

    def clean_code(self):
        """Validate code uniqueness"""
        code = self.cleaned_data.get('code')
        if code:
            code = code.upper()
            queryset = LoanProduct.objects.filter(code=code)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError("A loan product with this code already exists.")
        return code

    # -------------------------------------------------------------------------
    # Rate-field converters: user enters percentage (3.5), we store fraction (0.035)
    # -------------------------------------------------------------------------
    def _pct_to_fraction(self, fname):
        """Convert a percentage value entered by the user to a 4-dp decimal fraction."""
        val = self.cleaned_data.get(fname)
        if val is None:
            return val
        try:
            return (Decimal(str(val)) / 100).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise ValidationError("Enter a valid percentage (e.g. 3.5 for 3.5%).")

    def clean_monthly_interest_rate(self):
        return self._pct_to_fraction('monthly_interest_rate')

    def clean_risk_premium_rate(self):
        return self._pct_to_fraction('risk_premium_rate')

    def clean_rp_income_rate(self):
        return self._pct_to_fraction('rp_income_rate')

    def clean_tech_fee_rate(self):
        return self._pct_to_fraction('tech_fee_rate')

    def clean_early_repayment_penalty_rate(self):
        return self._pct_to_fraction('early_repayment_penalty_rate')

    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()

        # Validate principal amounts
        min_principal = cleaned_data.get('min_principal_amount')
        max_principal = cleaned_data.get('max_principal_amount')
        if min_principal and max_principal and min_principal > max_principal:
            raise ValidationError("Minimum principal amount cannot be greater than maximum.")

        # Validate duration
        min_duration = cleaned_data.get('min_duration_months')
        max_duration = cleaned_data.get('max_duration_months')
        if min_duration and max_duration and min_duration > max_duration:
            raise ValidationError("Minimum duration cannot be greater than maximum.")

        return cleaned_data


class LoanProductSearchForm(forms.Form):
    """Form for searching loan products"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white',
            'placeholder': 'Search by name or code...',
        })
    )

    loan_type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + list(LoanProduct._meta.get_field('loan_type').choices),
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white',
        })
    )

    status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Status'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white',
        })
    )


# =============================================================================
# SAVINGS PRODUCT FORMS
# =============================================================================

class SavingsProductForm(forms.ModelForm):
    """Form for creating/updating savings products"""

    class Meta:
        model = SavingsProduct
        fields = [
            'code', 'name', 'description', 'gl_code', 'product_type',
            'interest_rate_annual', 'interest_calculation_method', 'interest_payment_frequency',
            'minimum_balance', 'minimum_opening_balance', 'maximum_balance',
            'min_deposit_amount', 'min_withdrawal_amount', 'max_withdrawal_amount', 'daily_withdrawal_limit',
            'fixed_term_months', 'allows_withdrawal_before_maturity',
        ]

        widgets = {
            'code': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., REG-SAV, FD-6M',
            }),
            'name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Basic Savings Account',
            }),
            'description': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Product description and features',
            }),
            # gl_code — overridden as ChoiceField in __init__; no widget entry needed here
            'product_type': forms.Select(attrs={'class': SELECT_CLASS}),
            'interest_rate_annual': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
                'placeholder': '5.00 (5%)',
            }),
            'interest_calculation_method': forms.Select(attrs={'class': SELECT_CLASS}),
            'interest_payment_frequency': forms.Select(attrs={'class': SELECT_CLASS}),
            'minimum_balance': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'minimum_opening_balance': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'maximum_balance': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'min_deposit_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'min_withdrawal_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'max_withdrawal_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'daily_withdrawal_limit': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'step': '0.01',
            }),
            'fixed_term_months': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
            }),
            'allows_withdrawal_before_maturity': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASS}),
        }

    # Override gl_code as a ChoiceField so users pick from the Chart of Accounts
    gl_code = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        label='GL Account',
        help_text='The general ledger liability account this savings product posts deposits to.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Build dropdown choices from active ChartOfAccounts records
        # Displayed as: "2010 — Savings Deposits - Regular"
        gl_choices = [('', '— Select GL Account (optional) —')]
        accounts = (
            ChartOfAccounts.objects
            .filter(is_active=True)
            .order_by('gl_code')
            .values_list('gl_code', 'account_name')
        )
        gl_choices += [(code, f'{code} \u2014 {name}') for code, name in accounts]
        self.fields['gl_code'].choices = gl_choices

    def clean_code(self):
        """Validate code uniqueness"""
        code = self.cleaned_data.get('code')
        if code:
            code = code.upper()
            queryset = SavingsProduct.objects.filter(code=code)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError("A savings product with this code already exists.")
        return code

    def clean(self):
        """Cross-field validation"""
        cleaned_data = super().clean()

        # Validate balances
        min_balance = cleaned_data.get('minimum_balance')
        max_balance = cleaned_data.get('maximum_balance')
        if min_balance and max_balance and min_balance > max_balance:
            raise ValidationError("Minimum balance cannot be greater than maximum balance.")

        # Validate opening balance
        min_opening = cleaned_data.get('minimum_opening_balance')
        if min_balance and min_opening and min_opening < min_balance:
            raise ValidationError("Minimum opening balance cannot be less than minimum balance.")

        # Fixed deposit validation
        product_type = cleaned_data.get('product_type')
        fixed_term = cleaned_data.get('fixed_term_months')
        if product_type == 'fixed' and not fixed_term:
            self.add_error('fixed_term_months', "Fixed term is required for fixed deposit products.")

        return cleaned_data


class SavingsProductSearchForm(forms.Form):
    """Form for searching savings products"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white',
            'placeholder': 'Search by name or code...',
        })
    )

    product_type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + list(SavingsProduct.PRODUCT_TYPE_CHOICES),
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white',
        })
    )

    status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Status'),
            ('active', 'Active'),
            ('inactive', 'Inactive'),
        ],
        widget=forms.Select(attrs={
            'class': 'px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white',
        })
    )
