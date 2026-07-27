"""
Tests confirming assigned staff receive a notification when a follow-up
task is created or reassigned to them — previously loan_add_followup and
followup_update saved the task but never notified anyone.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import FollowUpTask, Loan, Notification
from core.tests.factories import make_branch, make_user, make_client, make_loan_product


class TestFollowUpAssignmentNotifications(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch(code='FUN001')
        cls.manager = make_user(cls.branch, role='manager', email='fun_mgr@test.com')
        cls.staff_a = make_user(cls.branch, role='staff', email='fun_staff_a@test.com')
        cls.staff_b = make_user(cls.branch, role='staff', email='fun_staff_b@test.com')
        client_obj = make_client(cls.branch, cls.staff_a, email='fun_client@test.com')
        product = make_loan_product(code='FUNP001')

        cls.loan = Loan.objects.create(
            client=client_obj, loan_product=product, branch=cls.branch,
            principal_amount=Decimal('50000.00'), duration_months=6,
            disbursement_method='cash', created_by=cls.manager,
            purpose='Business', status='active',
            outstanding_balance=Decimal('50000.00'),
        )

    def _post_add_followup(self, assigned_to):
        return self.client.post(
            reverse('core:loan_add_followup', args=[self.loan.id]),
            {
                'follow_up_type': 'phone_call',
                'priority': 'medium',
                'assigned_to': assigned_to.id,
                'due_date': (timezone.now().date() + timedelta(days=1)).isoformat(),
                'notes': 'Call about upcoming installment.',
            },
        )

    def test_assigning_task_to_another_staff_member_notifies_them(self):
        self.client.force_login(self.manager)
        response = self._post_add_followup(self.staff_b)
        self.assertEqual(response.status_code, 302)

        notifications = Notification.objects.filter(
            user=self.staff_b, notification_type='followup_assigned',
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn(self.loan.loan_number, notifications.first().message)

    def test_assigning_task_to_self_does_not_notify(self):
        self.client.force_login(self.staff_a)
        response = self._post_add_followup(self.staff_a)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            Notification.objects.filter(user=self.staff_a, notification_type='followup_assigned').count(),
            0,
        )

    def test_reassigning_task_notifies_new_assignee(self):
        task = FollowUpTask.objects.create(
            loan=self.loan, follow_up_type='phone_call', priority='medium',
            assigned_to=self.staff_a, created_by=self.manager,
            due_date=timezone.now().date() + timedelta(days=2),
            notes='Initial note',
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('core:followup_update', args=[task.id]),
            {
                'follow_up_type': 'phone_call',
                'priority': 'medium',
                'assigned_to': self.staff_b.id,
                'due_date': (timezone.now().date() + timedelta(days=2)).isoformat(),
                'notes': 'Initial note',
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            Notification.objects.filter(user=self.staff_b, notification_type='followup_assigned').count(),
            1,
        )
        # The original assignee should not get a "you've been assigned" notice
        self.assertEqual(
            Notification.objects.filter(user=self.staff_a, notification_type='followup_assigned').count(),
            0,
        )

    def test_editing_task_without_changing_assignee_does_not_renotify(self):
        task = FollowUpTask.objects.create(
            loan=self.loan, follow_up_type='phone_call', priority='medium',
            assigned_to=self.staff_b, created_by=self.manager,
            due_date=timezone.now().date() + timedelta(days=2),
            notes='Initial note',
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('core:followup_update', args=[task.id]),
            {
                'follow_up_type': 'visit',  # changed field, same assignee
                'priority': 'high',
                'assigned_to': self.staff_b.id,
                'due_date': (timezone.now().date() + timedelta(days=3)).isoformat(),
                'notes': 'Updated note',
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            Notification.objects.filter(user=self.staff_b, notification_type='followup_assigned').count(),
            0,
        )
