"""
Loan Forms
==========

Forms for loan application, approval, disbursement, and repayment posting
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from core.models import Loan, LoanProduct, Branch, Client, SavingsAccount, LoanRepaymentPosting, Guarantor
from datetime import date, datetime


# CSS Classes for form widgets
TEXT_INPUT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
SELECT_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
TEXTAREA_CLASS = 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:border-primary-500 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-900/30 transition-all'
CHECKBOX_CLASS = 'h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded'


class LoanApplicationForm(forms.ModelForm):
    """
    Form for creating a new loan application

    This form:
    1. Allows staff to create loan applications
    2. Calculates fees based on loan product
    3. Shows fee breakdown and repayment calculator
    4. Does NOT collect fees (that happens in separate step)
    """

    class Meta:
        model = Loan
        fields = [
            'client', 'loan_product', 'principal_amount', 'duration_months',
            'purpose', 'purpose_details', 'loan_sector', 'linked_account',
            'branch', 'client_signature',
        ]
        widgets = {
            'client': forms.Select(attrs={'class': SELECT_CLASS}),
            'loan_product': forms.Select(attrs={'class': SELECT_CLASS}),
            'principal_amount': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '₦ 10,000.00',
                'inputmode': 'decimal',
                'id': 'id_principal_amount'
            }),
            'duration_months': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'min': '1',
                'max': '36',
                'id': 'id_duration_months'
            }),
            'purpose': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Business expansion, Equipment purchase'
            }),
            'purpose_details': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 3,
                'placeholder': 'Provide detailed information about loan purpose'
            }),
            'loan_sector': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Agriculture, Retail, Manufacturing'
            }),
            'linked_account': forms.Select(attrs={'class': SELECT_CLASS}),
            'branch': forms.Select(attrs={'class': SELECT_CLASS}),
            'client_signature': forms.ClearableFileInput(attrs={
                'class': 'block w-full text-sm text-gray-900 dark:text-gray-300 '
                         'border border-gray-300 dark:border-gray-600 rounded-lg cursor-pointer '
                         'bg-gray-50 dark:bg-gray-700 focus:outline-none',
                'accept': 'image/*',
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

        # Filter loan products to active only
        self.fields['loan_product'].queryset = LoanProduct.objects.filter(is_active=True)

        # Linked account is optional
        self.fields['linked_account'].required = False
        self.fields['linked_account'].queryset = SavingsAccount.objects.none()

        # Client signature is required
        self.fields['client_signature'].required = True

        # If client is known (edit mode via instance, or POST submission), filter linked accounts
        client_id = None
        if self.instance and self.instance.client_id:
            client_id = self.instance.client_id
        elif self.data.get('client'):
            client_id = self.data.get('client')

        if client_id:
            self.fields['linked_account'].queryset = SavingsAccount.objects.filter(
                client_id=client_id,
                status='active'
            )

    def clean_principal_amount(self):
        value = self.data.get('principal_amount', '')
        value = value.replace(',', '').strip()
        try:
            return Decimal(value)
        except Exception:
            raise forms.ValidationError('Enter a valid amount (e.g. 90,000 or 90000).')

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get('client')
        loan_product = cleaned_data.get('loan_product')
        principal_amount = cleaned_data.get('principal_amount')
        duration_months = cleaned_data.get('duration_months')

        if not all([client, loan_product, principal_amount, duration_months]):
            return cleaned_data

        # Validate principal amount range
        if principal_amount < loan_product.min_principal_amount:
            self.add_error('principal_amount',
                f"Amount must be at least ₦{loan_product.min_principal_amount:,.2f}")

        if principal_amount > loan_product.max_principal_amount:
            self.add_error('principal_amount',
                f"Amount must not exceed ₦{loan_product.max_principal_amount:,.2f}")

        # Validate duration
        if duration_months < loan_product.min_duration_months:
            self.add_error('duration_months',
                f"Duration must be at least {loan_product.min_duration_months} months")

        if duration_months > loan_product.max_duration_months:
            self.add_error('duration_months',
                f"Duration must not exceed {loan_product.max_duration_months} months")

        # Check client status
        if not client.is_active:
            self.add_error('client', "Client must be active to apply for a loan")

        # Check for existing active loans
        active_loans = Loan.objects.filter(
            client=client,
            status__in=['pending_fees', 'pending_approval', 'approved', 'active', 'overdue']
        ).exclude(pk=self.instance.pk if self.instance else None)

        if active_loans.exists():
            self.add_error('client',
                f"Client has {active_loans.count()} active loan(s). "
                f"Please complete existing loans before applying for new ones."
            )

        return cleaned_data

    def get_fee_breakdown(self):
        """Calculate fee breakdown for display"""
        if not self.is_valid():
            return None

        loan_product = self.cleaned_data['loan_product']
        principal = self.cleaned_data['principal_amount']

        fees = loan_product.calculate_fees(principal)
        return fees

    def get_repayment_calculation(self):
        """Calculate repayment details for display"""
        if not self.is_valid():
            return None

        from core.utils.money import InterestCalculator

        loan_product = self.cleaned_data['loan_product']
        principal = self.cleaned_data['principal_amount']
        months = self.cleaned_data['duration_months']

        calc = InterestCalculator.calculate_flat_interest(
            principal=principal,
            monthly_rate=loan_product.monthly_interest_rate,
            months=months
        )

        # Calculate number of installments
        freq_map = {
            'daily':       months * 20,   # 20 standard working days per month
            'weekly':      months * 4,
            'fortnightly': months * 2,
            'monthly':     months,
            'yearly':      max(1, months // 12),
        }

        num_installments = freq_map.get(loan_product.repayment_frequency, months)
        installment_amount = calc['total_repayment'] / num_installments

        return {
            'principal_amount': principal,
            'total_interest': calc['total_interest'],
            'total_repayment': calc['total_repayment'],
            'monthly_installment': calc['monthly_installment'],
            'number_of_installments': num_installments,
            'installment_amount': installment_amount,
            'repayment_frequency': loan_product.repayment_frequency,
            'monthly_rate_display': loan_product.monthly_interest_rate * 100,
        }


class LoanFeePaymentForm(forms.Form):
    """Form for paying loan application fees"""

    payment_method = forms.ChoiceField(
        choices=[
            ('cash', 'Cash'),
            ('bank_transfer', 'Bank Transfer'),
            ('mobile_money', 'Mobile Money'),
            ('cheque', 'Cheque'),
        ],
        widget=forms.Select(attrs={'class': SELECT_CLASS})
    )

    payment_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Transaction reference, receipt number, etc.'
        })
    )

    payment_details = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 2,
            'placeholder': 'Additional payment information (bank name, mobile number, etc.)'
        })
    )

    def __init__(self, *args, **kwargs):
        self.loan = kwargs.pop('loan', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()

        if not self.loan:
            raise ValidationError("Loan instance is required")

        if self.loan.fees_paid:
            raise ValidationError("Fees have already been paid for this loan")

        if self.loan.status != 'pending_fees':
            raise ValidationError(
                f"Cannot pay fees for loan with status: {self.loan.get_status_display()}"
            )

        return cleaned_data


class LoanApprovalForm(forms.Form):
    """Form for approving or rejecting loan applications"""

    DECISION_CHOICES = [
        ('approve', 'Approve Loan'),
        ('reject', 'Reject Loan'),
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
        self.loan = kwargs.pop('loan', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        decision = cleaned_data.get('decision')

        if not self.loan:
            raise ValidationError("Loan instance is required")

        if self.loan.status != 'pending_approval':
            raise ValidationError(
                f"Cannot process loan with status: {self.loan.get_status_display()}"
            )

        if not self.loan.fees_paid:
            raise ValidationError("Fees must be paid before approval")

        if decision == 'reject':
            notes = cleaned_data.get('notes')
            if not notes or len(notes.strip()) < 10:
                self.add_error('notes',
                    "Please provide a reason for rejection (minimum 10 characters)")

        return cleaned_data


class LoanDisbursementForm(forms.Form):
    """Form for disbursing approved loans"""

    disbursement_method = forms.ChoiceField(
        choices=Loan.DISBURSEMENT_METHOD_CHOICES,
        widget=forms.Select(attrs={'class': SELECT_CLASS})
    )

    bank_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Bank name (for bank transfers)'
        })
    )

    bank_account_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Account number'
        })
    )

    bank_account_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Account name'
        })
    )

    disbursement_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Transaction reference'
        })
    )

    disbursement_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Additional disbursement notes'
        })
    )

    def __init__(self, *args, **kwargs):
        self.loan = kwargs.pop('loan', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('disbursement_method')

        if not self.loan:
            raise ValidationError("Loan instance is required")

        if self.loan.status != 'approved':
            raise ValidationError(
                f"Cannot disburse loan with status: {self.loan.get_status_display()}"
            )

        # Validate bank details for bank transfers
        if method == 'bank_transfer':
            if not cleaned_data.get('bank_name'):
                self.add_error('bank_name', 'Bank name is required for bank transfers')
            if not cleaned_data.get('bank_account_number'):
                self.add_error('bank_account_number', 'Account number is required')
            if not cleaned_data.get('bank_account_name'):
                self.add_error('bank_account_name', 'Account name is required')

        return cleaned_data


class LoanRepaymentPostingForm(forms.ModelForm):
    """Form for staff to post a single loan repayment"""

    class Meta:
        model = LoanRepaymentPosting
        fields = [
            'loan', 'amount', 'payment_method', 'payment_reference',
            'payment_details', 'payment_date', 'submission_notes'
        ]
        widgets = {
            'loan': forms.Select(attrs={'class': SELECT_CLASS}),
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
                'placeholder': 'Notes about this repayment'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)

            # Filter loans to active/overdue only
            base_queryset = Loan.objects.filter(
                status__in=['active', 'overdue']
            ).select_related('client', 'branch')

            if checker.is_staff():
                self.fields['loan'].queryset = base_queryset.filter(
                    client__assigned_staff=user
                )
            elif checker.is_manager():
                self.fields['loan'].queryset = base_queryset.filter(
                    branch=user.branch
                )
            else:
                self.fields['loan'].queryset = base_queryset

        # Set default payment date to today
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.now().date()

    def clean(self):
        cleaned_data = super().clean()
        loan = cleaned_data.get('loan')
        amount = cleaned_data.get('amount')

        if not loan or not amount:
            return cleaned_data

        # Validate loan status
        if loan.status not in ['active', 'overdue']:
            self.add_error('loan',
                f"Cannot post repayment for loan with status: {loan.get_status_display()}"
            )

        # Validate amount
        if amount <= 0:
            self.add_error('amount', "Amount must be greater than zero")

        if amount > loan.outstanding_balance:
            self.add_error('amount',
                f"Amount (₦{amount:,.2f}) exceeds outstanding balance "
                f"(₦{loan.outstanding_balance:,.2f})"
            )

        return cleaned_data


class BulkLoanRepaymentPostingForm(forms.Form):
    """Form for posting multiple loan repayments at once"""

    loan_repayments = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 10,
            'placeholder': (
                'Enter repayments in format:\n'
                'LOAN_NUMBER, AMOUNT, PAYMENT_METHOD, PAYMENT_REF, PAYMENT_DATE\n\n'
                'Example:\n'
                'LN20260204123456789012, 5000, cash, REC001, 2026-02-04\n'
                'LN20260204123456789013, 10000, mobile_money, MM12345, 2026-02-04'
            )
        }),
        help_text=(
            'One repayment per line. Format: LOAN_NUMBER, AMOUNT, PAYMENT_METHOD, '
            'PAYMENT_REF, PAYMENT_DATE (YYYY-MM-DD)'
        )
    )

    payment_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        }),
        help_text='Default payment date if not specified per line'
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if not self.data:
            self.fields['payment_date'].initial = timezone.now().date()

    def clean_loan_repayments(self):
        """Parse and validate bulk repayment data"""
        data = self.cleaned_data['loan_repayments']
        lines = [line.strip() for line in data.strip().split('\n') if line.strip()]

        if not lines:
            raise ValidationError("Please enter at least one repayment")

        if len(lines) > 100:
            raise ValidationError("Cannot process more than 100 repayments at once")

        parsed_repayments = []
        errors = []

        for i, line in enumerate(lines, 1):
            parts = [p.strip() for p in line.split(',')]

            if len(parts) < 2:
                errors.append(f"Line {i}: Invalid format (need at least loan number and amount)")
                continue

            try:
                loan_number = parts[0]
                amount = Decimal(parts[1])
                payment_method = parts[2] if len(parts) > 2 else 'cash'
                payment_ref = parts[3] if len(parts) > 3 else ''
                payment_date_str = parts[4] if len(parts) > 4 else None

                # Validate loan exists
                try:
                    loan = Loan.objects.get(loan_number=loan_number)
                except Loan.DoesNotExist:
                    errors.append(f"Line {i}: Loan {loan_number} not found")
                    continue

                # Validate loan status
                if loan.status not in ['active', 'overdue']:
                    errors.append(
                        f"Line {i}: Loan {loan_number} has status {loan.get_status_display()}"
                    )
                    continue

                # Validate amount
                if amount <= 0:
                    errors.append(f"Line {i}: Amount must be greater than zero")
                    continue

                if amount > loan.outstanding_balance:
                    errors.append(
                        f"Line {i}: Amount ₦{amount:,.2f} exceeds balance "
                        f"₦{loan.outstanding_balance:,.2f}"
                    )
                    continue

                # Parse payment date
                if payment_date_str:
                    payment_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
                else:
                    payment_date = self.cleaned_data.get('payment_date') or timezone.now().date()

                parsed_repayments.append({
                    'loan': loan,
                    'amount': amount,
                    'payment_method': payment_method,
                    'payment_reference': payment_ref,
                    'payment_date': payment_date,
                    'line_number': i
                })

            except ValueError as e:
                errors.append(f"Line {i}: {str(e)}")

        if errors:
            raise ValidationError('\n'.join(errors))

        return parsed_repayments


class ApproveRepaymentPostingForm(forms.Form):
    """Form for approving or rejecting a repayment posting"""

    DECISION_CHOICES = [
        ('approve', 'Approve Repayment'),
        ('reject', 'Reject Repayment'),
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


class LoanSearchForm(forms.Form):
    """Search and filter form for loan list"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'placeholder': 'Search by loan number, client name, or ID...'
        })
    )

    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All Statuses')] + Loan.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': SELECT_CLASS})
    )

    branch = forms.ModelChoiceField(
        required=False,
        queryset=Branch.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        empty_label='All Branches'
    )

    loan_product = forms.ModelChoiceField(
        required=False,
        queryset=LoanProduct.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        empty_label='All Loan Products'
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        })
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': TEXT_INPUT_CLASS,
            'type': 'date'
        })
    )


class GuarantorForm(forms.ModelForm):
    """
    Form for adding/editing loan guarantors

    Supports two types:
    - Internal: Select an existing client as guarantor
    - External: Manually enter guarantor details
    """

    class Meta:
        model = Guarantor
        fields = [
            'guarantor_type', 'linked_client', 'guarantee_amount',
            'name', 'phone', 'email', 'relationship', 'address',
            'occupation', 'employer', 'monthly_income',
            'id_type', 'id_number',
            'id_card_front', 'id_card_back', 'signature',
            'notes'
        ]
        widgets = {
            'guarantor_type': forms.Select(attrs={
                'class': SELECT_CLASS,
                'id': 'id_guarantor_type',
                'onchange': 'toggleGuarantorType(this.value)'
            }),
            'linked_client': forms.Select(attrs={
                'class': SELECT_CLASS,
                'id': 'id_linked_client'
            }),
            'guarantee_amount': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '₦ 0.00',
                'step': '0.01'
            }),
            'name': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Full name'
            }),
            'phone': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '+234...'
            }),
            'email': forms.EmailInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'email@example.com'
            }),
            'relationship': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., Friend, Colleague, Spouse'
            }),
            'address': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Full address'
            }),
            'occupation': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Job title or profession'
            }),
            'employer': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'Employer name'
            }),
            'monthly_income': forms.NumberInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': '₦ 0.00',
                'step': '0.01'
            }),
            'id_type': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'e.g., NIN, Passport, Voter\'s Card'
            }),
            'id_number': forms.TextInput(attrs={
                'class': TEXT_INPUT_CLASS,
                'placeholder': 'ID number'
            }),
            'notes': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 2,
                'placeholder': 'Additional notes about this guarantor'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.loan = kwargs.pop('loan', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Make linked_client optional by default (required validation handled in clean)
        self.fields['linked_client'].required = False
        self.fields['email'].required = False
        self.fields['occupation'].required = False
        self.fields['employer'].required = False
        self.fields['monthly_income'].required = False
        self.fields['id_type'].required = False
        self.fields['id_number'].required = False
        self.fields['id_card_front'].required = False
        self.fields['id_card_back'].required = False
        self.fields['notes'].required = False

        # Filter clients for internal guarantor selection
        # Exclude the loan's own client from being their own guarantor
        if self.loan:
            self.fields['linked_client'].queryset = Client.objects.filter(
                is_active=True
            ).exclude(id=self.loan.client_id)
        else:
            self.fields['linked_client'].queryset = Client.objects.filter(is_active=True)

        # Set default guarantee amount to loan principal divided by required guarantors
        if self.loan and not self.instance.pk:
            required = Decimal(str(self.loan.loan_product.required_guarantors or 1))
            default_amount = (self.loan.principal_amount / required).quantize(Decimal('0.01'))
            self.initial['guarantee_amount'] = default_amount
            self.fields['guarantee_amount'].widget.attrs['value'] = str(default_amount)

    def clean(self):
        cleaned_data = super().clean()
        guarantor_type = cleaned_data.get('guarantor_type')
        linked_client = cleaned_data.get('linked_client')
        name = cleaned_data.get('name')
        phone = cleaned_data.get('phone')
        relationship = cleaned_data.get('relationship')
        address = cleaned_data.get('address')

        if guarantor_type == 'internal':
            # Internal guarantor must have linked client
            if not linked_client:
                self.add_error('linked_client',
                    "Please select an existing client for internal guarantor")
            else:
                # Auto-populate fields from linked client if not provided
                if not name:
                    cleaned_data['name'] = linked_client.get_full_name()
                if not phone:
                    cleaned_data['phone'] = linked_client.phone
                if not address:
                    cleaned_data['address'] = linked_client.address or 'N/A'

        elif guarantor_type == 'external':
            # External guarantor must have manual details
            if not name:
                self.add_error('name', "Name is required for external guarantor")
            if not phone:
                self.add_error('phone', "Phone number is required for external guarantor")
            if not address:
                self.add_error('address', "Address is required for external guarantor")

            # Clear linked_client for external
            cleaned_data['linked_client'] = None

        # Relationship is always required
        if not relationship:
            self.add_error('relationship', "Relationship to borrower is required")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Set loan if provided
        if self.loan and not instance.loan_id:
            instance.loan = self.loan
            instance.branch = self.loan.branch

        # For internal guarantor, populate from linked client
        if instance.guarantor_type == 'internal' and instance.linked_client:
            if not instance.name:
                instance.name = instance.linked_client.get_full_name()
            if not instance.phone:
                instance.phone = instance.linked_client.phone
            if not instance.email:
                instance.email = instance.linked_client.email or ''
            if not instance.address:
                instance.address = instance.linked_client.address or 'N/A'

        if commit:
            instance.save()

        return instance
