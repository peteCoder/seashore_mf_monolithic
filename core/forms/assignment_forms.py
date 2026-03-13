"""
Assignment Request Forms
========================
"""

from django import forms
from core.models import AssignmentRequest, Client, User, Branch, ClientGroup


TAILWIND_INPUT = (
    'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg '
    'bg-white dark:bg-gray-700 text-gray-900 dark:text-white '
    'focus:ring-2 focus:ring-primary-500 focus:border-primary-500'
)
TAILWIND_TEXTAREA = TAILWIND_INPUT


class AssignmentRequestForm(forms.Form):
    """
    Dynamic form for creating assignment requests.
    The assignment_type drives which target fields are required.
    """

    SINGLE_TYPES = [
        ('client_to_staff', 'Assign Client → Staff Member'),
        ('client_to_branch', 'Assign Client → Branch'),
        ('client_to_group', 'Assign Client → Group'),
        ('unassign_client_from_staff', 'Unassign Client from Staff'),
        ('unassign_client_from_group', 'Unassign Client from Group'),
        ('group_to_branch', 'Assign Group → Branch'),
    ]

    BULK_TYPES = [
        ('bulk_clients_to_staff', 'Bulk: Assign Multiple Clients → Staff Member'),
        ('bulk_clients_to_branch', 'Bulk: Assign Multiple Clients → Branch'),
        ('bulk_clients_to_group', 'Bulk: Assign Multiple Clients → Group'),
    ]

    ALL_TYPES = SINGLE_TYPES + BULK_TYPES

    assignment_type = forms.ChoiceField(
        choices=ALL_TYPES,
        widget=forms.Select(attrs={'class': TAILWIND_INPUT, 'id': 'id_assignment_type'}),
        label='Assignment Type',
    )

    # Single client
    client = forms.ModelChoiceField(
        queryset=Client.objects.filter(is_active=True, approval_status='approved').select_related('branch'),
        required=False,
        widget=forms.Select(attrs={'class': TAILWIND_INPUT}),
        label='Client',
        help_text='Select the client to reassign.',
    )

    # Multiple clients (bulk)
    clients = forms.ModelMultipleChoiceField(
        queryset=Client.objects.filter(is_active=True, approval_status='approved').select_related('branch'),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': TAILWIND_INPUT, 'size': '8'}),
        label='Clients (select multiple)',
        help_text='Hold Ctrl/Cmd to select multiple clients.',
    )

    # Target staff
    target_staff = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True, user_role__in=['staff', 'manager']).order_by('first_name', 'last_name'),
        required=False,
        widget=forms.Select(attrs={'class': TAILWIND_INPUT}),
        label='Target Staff Member',
    )

    # Target branch
    target_branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True).order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': TAILWIND_INPUT}),
        label='Target Branch',
    )

    # Target group
    target_group = forms.ModelChoiceField(
        queryset=ClientGroup.objects.filter(status='active').select_related('branch').order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': TAILWIND_INPUT}),
        label='Target Group',
    )

    # Target group (for group → branch)
    source_group = forms.ModelChoiceField(
        queryset=ClientGroup.objects.filter(status='active').select_related('branch').order_by('name'),
        required=False,
        widget=forms.Select(attrs={'class': TAILWIND_INPUT}),
        label='Group to Reassign',
    )

    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': TAILWIND_TEXTAREA,
            'placeholder': 'Optional reason for this assignment request',
        }),
        label='Reason',
    )

    def clean(self):
        cleaned = super().clean()
        atype = cleaned.get('assignment_type', '')

        # Validate required targets per assignment type
        if atype in ('client_to_staff', 'unassign_client_from_staff', 'client_to_branch',
                     'client_to_group', 'unassign_client_from_group'):
            if not cleaned.get('client'):
                self.add_error('client', 'Please select a client.')

        if atype in ('bulk_clients_to_staff', 'bulk_clients_to_branch', 'bulk_clients_to_group'):
            if not cleaned.get('clients'):
                self.add_error('clients', 'Please select at least one client.')

        if atype in ('client_to_staff', 'bulk_clients_to_staff'):
            if not cleaned.get('target_staff'):
                self.add_error('target_staff', 'Please select a target staff member.')

        if atype in ('client_to_branch', 'bulk_clients_to_branch', 'group_to_branch'):
            if not cleaned.get('target_branch'):
                self.add_error('target_branch', 'Please select a target branch.')

        if atype in ('client_to_group', 'bulk_clients_to_group'):
            if not cleaned.get('target_group'):
                self.add_error('target_group', 'Please select a target group.')

        if atype == 'group_to_branch':
            if not cleaned.get('source_group'):
                self.add_error('source_group', 'Please select the group to reassign.')

        return cleaned

    def build_assignment_data(self):
        """Build the JSON-serialisable data dict for AssignmentRequest.assignment_data."""
        cleaned = self.cleaned_data
        atype = cleaned['assignment_type']
        data = {}

        client = cleaned.get('client')
        if client:
            data['client_id'] = str(client.id)
            data['client_name'] = client.get_full_name()

        clients = cleaned.get('clients')
        if clients:
            data['client_ids'] = [str(c.id) for c in clients]
            data['client_names'] = [c.get_full_name() for c in clients]

        target_staff = cleaned.get('target_staff')
        if target_staff:
            data['staff_id'] = str(target_staff.id)
            data['staff_name'] = target_staff.get_full_name()

        target_branch = cleaned.get('target_branch')
        if target_branch:
            data['branch_id'] = str(target_branch.id)
            data['branch_name'] = target_branch.name

        target_group = cleaned.get('target_group')
        if target_group:
            data['group_id'] = str(target_group.id)
            data['group_name'] = target_group.name

        source_group = cleaned.get('source_group')
        if source_group:
            data['group_id'] = str(source_group.id)
            data['group_name'] = source_group.name

        return data

    def build_description(self):
        cleaned = self.cleaned_data
        atype = cleaned['assignment_type']

        client = cleaned.get('client')
        clients = cleaned.get('clients')
        target_staff = cleaned.get('target_staff')
        target_branch = cleaned.get('target_branch')
        target_group = cleaned.get('target_group')
        source_group = cleaned.get('source_group')

        if atype == 'client_to_staff' and client and target_staff:
            return f'Assign {client.get_full_name()} to {target_staff.get_full_name()}'
        if atype == 'client_to_branch' and client and target_branch:
            return f'Move {client.get_full_name()} to branch {target_branch.name}'
        if atype == 'client_to_group' and client and target_group:
            return f'Add {client.get_full_name()} to group {target_group.name}'
        if atype == 'unassign_client_from_staff' and client:
            return f'Unassign {client.get_full_name()} from their current staff officer'
        if atype == 'unassign_client_from_group' and client:
            return f'Remove {client.get_full_name()} from their current group'
        if atype == 'group_to_branch' and source_group and target_branch:
            return f'Move group {source_group.name} to branch {target_branch.name}'
        if atype == 'bulk_clients_to_staff' and clients and target_staff:
            return f'Assign {len(clients)} clients to {target_staff.get_full_name()}'
        if atype == 'bulk_clients_to_branch' and clients and target_branch:
            return f'Move {len(clients)} clients to branch {target_branch.name}'
        if atype == 'bulk_clients_to_group' and clients and target_group:
            return f'Add {len(clients)} clients to group {target_group.name}'
        return dict(self.ALL_TYPES).get(atype, atype)


class AssignmentReviewForm(forms.Form):
    """Approve or reject an assignment request."""

    DECISION_CHOICES = [
        ('approve', 'Approve and Execute'),
        ('reject', 'Reject'),
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
            'placeholder': 'Notes about this decision',
        }),
        label='Review Notes',
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') == 'reject' and not cleaned.get('review_notes', '').strip():
            self.add_error('review_notes', 'Please explain why this request is being rejected.')
        return cleaned
