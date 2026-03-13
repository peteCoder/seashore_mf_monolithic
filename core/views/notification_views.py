"""
Notification Views
==================
Handles the notification inbox, bell-dropdown data endpoint, and mark-read actions.
"""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Notification


# =============================================================================
# NOTIFICATION LIST
# =============================================================================

@login_required
def notification_list(request):
    """
    Paginated inbox of all notifications for the current user.
    GET ?filter=unread  → only unread
    """
    filter_by = request.GET.get('filter', 'all')

    qs = Notification.objects.filter(user=request.user).select_related(
        'related_client', 'related_loan', 'related_savings'
    )

    if filter_by == 'unread':
        qs = qs.filter(is_read=False)
    elif filter_by == 'urgent':
        qs = qs.filter(is_urgent=True, is_read=False)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    return render(request, 'notifications/list.html', {
        'page_title': 'Notifications',
        'notifications': page_obj,
        'unread_count': unread_count,
        'filter_by': filter_by,
    })


# =============================================================================
# BELL DROPDOWN DATA  (JSON endpoint — consumed by Alpine.js)
# =============================================================================

@login_required
def notification_data(request):
    """
    Return JSON payload for the notification bell dropdown.
    Returns up to 10 most recent notifications (all, not just unread).
    """
    qs = Notification.objects.filter(user=request.user).select_related(
        'related_loan', 'related_savings', 'related_client'
    )[:10]

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    def _url(notif):
        """Build a best-effort deep-link for the notification."""
        try:
            if notif.related_loan_id:
                return f"/loans/{notif.related_loan_id}/"
            if notif.related_savings_id:
                return f"/savings/{notif.related_savings_id}/"
            if notif.related_client_id:
                return f"/clients/{notif.related_client_id}/"
        except Exception:
            pass
        return "/notifications/"

    data = {
        'unread_count': unread_count,
        'notifications': [
            {
                'id': str(n.id),
                'type': n.notification_type,
                'title': n.title,
                'message': n.message[:120],
                'is_read': n.is_read,
                'is_urgent': n.is_urgent,
                'created_at': n.created_at.strftime('%d %b %Y, %H:%M'),
                'url': _url(n),
            }
            for n in qs
        ],
    }
    return JsonResponse(data)


# =============================================================================
# MARK SINGLE NOTIFICATION AS READ
# =============================================================================

@login_required
@require_POST
def notification_mark_read(request, notification_id):
    """Mark a single notification as read. Returns JSON for AJAX or redirects."""
    notif = get_object_or_404(Notification, id=notification_id, user=request.user)
    notif.mark_as_read()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})

    next_url = request.POST.get('next') or '/notifications/'
    return redirect(next_url)


# =============================================================================
# MARK ALL NOTIFICATIONS AS READ
# =============================================================================

@login_required
@require_POST
def notification_mark_all_read(request):
    """Mark every unread notification for the current user as read."""
    now = timezone.now()
    Notification.objects.filter(user=request.user, is_read=False).update(
        is_read=True,
        read_at=now,
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok', 'count': 0})

    messages.success(request, "All notifications marked as read.")
    return redirect('core:notification_list')
