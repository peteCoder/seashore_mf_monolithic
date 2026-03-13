"""
Follow-up Task Forms
====================
"""

from django import forms
from django.utils import timezone
from core.models import FollowUpTask, User


TAILWIND_INPUT = 'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
TAILWIND_TEXTAREA = TAILWIND_INPUT


class FollowUpTaskForm(forms.ModelForm):
    """Create or edit a follow-up task for a loan."""

    class Meta:
        model = FollowUpTask
        fields = ['follow_up_type', 'priority', 'assigned_to', 'due_date', 'notes']
        widgets = {
            'follow_up_type': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'priority': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'assigned_to': forms.Select(attrs={'class': TAILWIND_INPUT}),
            'due_date': forms.DateInput(attrs={
                'class': TAILWIND_INPUT,
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'rows': 4,
                'class': TAILWIND_TEXTAREA,
                'placeholder': 'Describe what needs to be done during this follow-up',
            }),
        }

    def __init__(self, *args, **kwargs):
        branch = kwargs.pop('branch', None)
        super().__init__(*args, **kwargs)
        # Restrict assigned_to to active staff/managers in the same branch
        qs = User.objects.filter(is_active=True, user_role__in=['staff', 'manager', 'director', 'hr', 'admin'])
        if branch:
            qs = qs.filter(branch=branch)
        self.fields['assigned_to'].queryset = qs.order_by('first_name', 'last_name')

    def clean_due_date(self):
        due_date = self.cleaned_data.get('due_date')
        if due_date and due_date < timezone.now().date():
            raise forms.ValidationError('Due date cannot be in the past.')
        return due_date


class FollowUpTaskCompleteForm(forms.Form):
    """Mark a follow-up task as completed with an outcome note."""

    outcome = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'class': TAILWIND_TEXTAREA,
            'placeholder': "What happened? What was the client's response?",
        }),
        label='Outcome / Result',
        help_text='Describe what happened during this follow-up.',
    )
