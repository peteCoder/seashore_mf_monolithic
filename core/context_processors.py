"""
Context Processors
==================
Injects global template variables available on every page.
"""


def notifications(request):
    """Add unread notification count and overdue installment count to every template context."""
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0, 'overdue_installments_count': 0}
    try:
        from core.models import Notification, LoanRepaymentSchedule
        from django.utils import timezone
        from core.permissions import PermissionChecker

        notif_count = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()

        checker = PermissionChecker(request.user)
        today = timezone.localdate()
        overdue_qs = LoanRepaymentSchedule.objects.filter(
            status__in=['pending', 'partial', 'overdue'],
            outstanding_amount__gt=0,
            due_date__lt=today,
            loan__status__in=['active', 'overdue', 'disbursed'],
            loan__outstanding_balance__gt=0,
        )
        if not checker.can_view_all_branches() and hasattr(request.user, 'branch') and request.user.branch:
            overdue_qs = overdue_qs.filter(loan__branch=request.user.branch)

        return {
            'unread_notification_count': notif_count,
            'overdue_installments_count': overdue_qs.count(),
        }
    except Exception:
        return {'unread_notification_count': 0, 'overdue_installments_count': 0}
