"""
Core Middleware
===============

Custom Django middleware for Seashore Microfinance:
  - IPSessionLockMiddleware: Terminates sessions when the client IP changes
  - ReadOnlyAuditorMiddleware: Hard-blocks all mutation for the 'auditor' role
"""

import logging

from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


def _get_client_ip(request):
    """Return the real client IP, honouring X-Forwarded-For when behind a proxy."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


class IPSessionLockMiddleware:
    """
    Terminates a user's session when their client IP address changes.

    On first authenticated request after login the IP is recorded in the session
    (under the key ``login_ip``).  Every subsequent request checks the current IP
    against the stored one.  If they differ the user is forcibly logged out and
    redirected to the login page with a warning message.

    Exemptions
    ----------
    * Unauthenticated requests are always passed through unchanged.
    * The login, logout, and password-reset URLs are never blocked so that a
      redirected user can actually reach the login page.
    * Superusers are exempt so that admin access from multiple locations is not
      blocked during development / support sessions.
    """

    # URL prefixes that must never be blocked (otherwise the redirect loop is infinite)
    EXEMPT_URL_NAMES = {
        '/login/',
        '/logout/',
        '/register/',
        '/reset-password/',
        '/verify-2fa/',
        '/setup-2fa/',
        '/disable-2fa/',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            # Skip exempt paths
            path = request.path_info
            is_exempt = any(path.startswith(exempt) for exempt in self.EXEMPT_URL_NAMES)

            if not is_exempt:
                current_ip = _get_client_ip(request)
                stored_ip = request.session.get('login_ip', '')

                if not stored_ip:
                    # First request after login — record the IP
                    request.session['login_ip'] = current_ip
                    logger.info(
                        "IPSessionLock: Recorded login IP %s for user %s",
                        current_ip, request.user.email,
                    )
                elif stored_ip != current_ip:
                    # IP changed — terminate the session
                    logger.warning(
                        "IPSessionLock: IP mismatch for user %s "
                        "(stored=%s, current=%s) — session terminated.",
                        request.user.email, stored_ip, current_ip,
                    )
                    logout(request)
                    try:
                        messages.warning(
                            request,
                            'Your session was terminated because your network address changed. '
                            'Please log in again to continue.',
                        )
                    except Exception:
                        pass  # MessageMiddleware not available (e.g. API request)
                    return redirect('core:login')

        response = self.get_response(request)
        return response


class ReadOnlyAuditorMiddleware:
    """
    Hard, code-independent guarantee that a user with user_role == 'auditor'
    can NEVER create, edit, approve, or delete anything — anywhere in the
    app, including the REST API.

    Why a middleware and not just permission-list membership: this codebase's
    permission checks are hand-rolled per action (core/permissions.py), and at
    least one of them conflates a VIEW flag with a WRITE action —
    PermissionChecker.can_approve_collections() returns True for anyone with
    can_view_all_branches(), which the auditor role deliberately has. Relying
    solely on getting every permission list right, across a codebase this
    size, under time pressure, is not a safe bet. This middleware blocks the
    HTTP verb itself, before any view or permission check runs, so a mistake
    or omission in any single view's permission check can never let an
    auditor mutate data.

    GET/HEAD/OPTIONS (safe methods — never mutate) are always allowed.
    Everything else (POST/PUT/PATCH/DELETE) is rejected outright for this
    role, full stop, including the auditor's own profile/password forms —
    this is a short-lived, view-only audit account, not a regular staff
    account.
    """

    SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, 'user_role', None) == 'auditor'
            and request.method not in self.SAFE_METHODS
        ):
            logger.warning(
                "ReadOnlyAuditorMiddleware: blocked %s %s for auditor user %s",
                request.method, request.path, user.email,
            )
            return HttpResponseForbidden(
                "This is a read-only auditor account. Viewing is allowed; "
                "creating, editing, approving, or deleting anything is not."
            )
        return self.get_response(request)
