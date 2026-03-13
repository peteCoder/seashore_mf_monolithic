"""
Core Middleware
===============

Custom Django middleware for Seashore Microfinance:
  - IPSessionLockMiddleware: Terminates sessions when the client IP changes
"""

import logging

from django.contrib import messages
from django.contrib.auth import logout
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
                    messages.warning(
                        request,
                        'Your session was terminated because your network address changed. '
                        'Please log in again to continue.',
                    )
                    return redirect('core:login')

        response = self.get_response(request)
        return response
