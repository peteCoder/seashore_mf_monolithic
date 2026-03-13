"""
Context Processors
==================
Injects global template variables available on every page.
"""


def notifications(request):
    """Add unread notification count to every template context."""
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0}
    try:
        from core.models import Notification
        count = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
        return {'unread_notification_count': count}
    except Exception:
        return {'unread_notification_count': 0}
