"""
Inter-Branch Transfer Forms
============================
"""
from django import forms
from core.models import InterBranchTransfer, Branch

TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class TransferCreateForm(forms.ModelForm):
    """Request a new inter-branch cash transfer."""

    class Meta:
        model = InterBranchTransfer
        fields = ['from_branch', 'to_branch', 'amount', 'purpose', 'notes']
        widgets = {
            'from_branch': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'to_branch':   forms.Select(attrs={'class': TAILWIND_INPUT}),
            'amount': forms.NumberInput(attrs={
                'class': TAILWIND_INPUT, 'step': '0.01', 'min': '1.00', 'placeholder': '0.00',
            }),
            'purpose': forms.TextInput(attrs={
                'class': TAILWIND_INPUT,
                'placeholder': 'Reason for transfer (e.g. Branch operational funds)',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3, 'class': TAILWIND_TEXTAREA, 'placeholder': 'Additional notes (optional)',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['to_branch'].queryset = Branch.objects.filter(is_active=True)
        if user is not None:
            from core.permissions import PermissionChecker
            checker = PermissionChecker(user)
            if checker.is_manager() and hasattr(user, 'branch') and user.branch:
                # Manager can only send FROM their own branch
                self.fields['from_branch'].queryset = Branch.objects.filter(
                    id=user.branch.id, is_active=True
                )
                self.fields['from_branch'].initial = user.branch
            else:
                self.fields['from_branch'].queryset = Branch.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        from_b = cleaned.get('from_branch')
        to_b   = cleaned.get('to_branch')
        if from_b and to_b and from_b == to_b:
            raise forms.ValidationError("Source and destination branch cannot be the same.")
        return cleaned


class TransferApproveForm(forms.Form):
    """Approve or reject a pending transfer."""

    DECISION_CHOICES = [
        ('approve', 'Approve — Release funds for transfer'),
        ('reject',  'Reject — Return without processing'),
    ]

    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'mr-2'}),
        label='Decision',
    )
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Rejection reason (required if rejecting)',
        }),
        label='Rejection Reason',
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'reject':
            if not cleaned.get('rejection_reason', '').strip():
                self.add_error('rejection_reason', 'Please provide a reason for rejection.')
        return cleaned


class TransferCompleteForm(forms.Form):
    """Confirm cash receipt at destination branch."""

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Receipt confirmation notes (optional)',
        }),
        label='Confirmation Notes',
    )
