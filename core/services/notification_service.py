"""
Notification Service
====================
Centralised helper for creating Notification records.

Usage:
    from core.services.notification_service import notify

    notify(
        user=some_user,
        notification_type='loan_approved',
        title='Loan Approved',
        message='Loan LN123 has been approved.',
        related_loan=loan_obj,
        is_urgent=False,
    )
"""

import logging

logger = logging.getLogger(__name__)


def notify(
    user,
    notification_type,
    title,
    message,
    related_client=None,
    related_loan=None,
    related_savings=None,
    is_urgent=False,
):
    """
    Create a single Notification record for the given user.

    Args:
        user:               User instance to notify.
        notification_type:  One of Notification.NOTIFICATION_TYPE_CHOICES keys.
        title:              Short headline (max 200 chars).
        message:            Full notification body.
        related_client:     Optional Client FK.
        related_loan:       Optional Loan FK.
        related_savings:    Optional SavingsAccount FK.
        is_urgent:          Mark notification as urgent (shows in red).
    """
    if user is None:
        return

    try:
        from core.models import Notification
        Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            related_client=related_client,
            related_loan=related_loan,
            related_savings=related_savings,
            is_urgent=is_urgent,
        )
    except Exception as exc:
        # Never let a notification failure crash a financial transaction.
        logger.error("Failed to create notification for user %s: %s", user, exc)


def notify_role(
    roles,
    notification_type,
    title,
    message,
    branch=None,
    related_client=None,
    related_loan=None,
    related_savings=None,
    is_urgent=False,
    exclude_user=None,
):
    """
    Create a Notification for every active user matching the given role(s).

    Args:
        roles:        A single role string (e.g. 'manager') or a list of role strings.
        branch:       Optional Branch — when supplied, only users in that branch are notified.
        exclude_user: Optional User — skip this user (e.g. the person who performed the action).
        Other args are identical to notify().
    """
    if isinstance(roles, str):
        roles = [roles]

    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        qs = User.objects.filter(user_role__in=roles, is_active=True)
        if branch is not None:
            qs = qs.filter(branch=branch)
        if exclude_user is not None:
            qs = qs.exclude(pk=exclude_user.pk)
        for user in qs:
            notify(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                related_client=related_client,
                related_loan=related_loan,
                related_savings=related_savings,
                is_urgent=is_urgent,
            )
    except Exception as exc:
        logger.error("Failed to notify_role %s: %s", roles, exc)
