"""
Two-Factor Authentication Views (TOTP)
======================================

Flow
----
1. User enters email + password on /login/
   → login_view in auth_views.py authenticates the user.
   → If ``user.is_2fa_enabled`` is True the user is NOT logged in immediately;
     instead the user.id is stored in the session under ``_2fa_pending_uid``
     and the browser is redirected to ``verify_2fa``.
   → If 2FA is not enabled the user is logged in normally (existing behaviour).

2. ``verify_2fa`` (GET / POST)
   → POST: receives the 6-digit TOTP code from the user's authenticator app.
   → On success: removes ``_2fa_pending_uid``, logs the user in, redirects to dashboard.
   → On failure: shows an error and lets the user try again (max 5 attempts,
     then the pending session is cleared).

3. ``setup_2fa`` (GET / POST)  — requires login
   → GET:  generates a provisional TOTP secret (stored in session, NOT yet saved to DB),
           builds the ``otpauth://`` URI and returns the base64-encoded QR-code PNG for
           the browser to render inline.
   → POST: user submits the 6-digit code from their authenticator app to confirm.
           On success: saves the secret and sets ``is_2fa_enabled = True``.

4. ``disable_2fa`` (POST)  — requires login + current password confirmation
   → Clears ``totp_secret`` and sets ``is_2fa_enabled = False``.
"""

import base64
import io
import logging

import pyotp
import qrcode

from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

User = get_user_model()
logger = logging.getLogger(__name__)

# How many wrong TOTP attempts before wiping the pending session
_MAX_2FA_ATTEMPTS = 5
# Session key where we park the user's PK between password-auth and 2FA verify
_SESSION_PENDING_UID = '_2fa_pending_uid'
# Session key for the provisional TOTP secret (during setup only)
_SESSION_SETUP_SECRET = '_2fa_setup_secret'
# Session key for attempt counter
_SESSION_ATTEMPTS    = '_2fa_attempts'


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_qr_data_uri(otp_uri: str) -> str:
    """Return a data: URI (PNG, base64) for the given OTP URI."""
    img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{b64}'


# ─────────────────────────────────────────────────────────────────────────────
# 1. Verify 2FA during login (session-staged)
# ─────────────────────────────────────────────────────────────────────────────

def verify_2fa(request):
    """
    Step 2 of login when the user has 2FA enabled.

    The user must NOT be logged in yet (``request.user.is_authenticated`` should
    be False).  A ``_2fa_pending_uid`` key in the session holds the user's PK.
    """
    pending_uid = request.session.get(_SESSION_PENDING_UID)

    # If there is no pending UID redirect to login
    if not pending_uid:
        return redirect('core:login')

    # If somehow the user is already logged in, go to dashboard
    if request.user.is_authenticated:
        request.session.pop(_SESSION_PENDING_UID, None)
        return redirect('core:dashboard')

    try:
        user = User.objects.get(pk=pending_uid, is_active=True, is_approved=True)
    except User.DoesNotExist:
        request.session.pop(_SESSION_PENDING_UID, None)
        messages.error(request, 'Session expired. Please log in again.')
        return redirect('core:login')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip().replace(' ', '')

        attempts = request.session.get(_SESSION_ATTEMPTS, 0) + 1
        request.session[_SESSION_ATTEMPTS] = attempts

        if attempts > _MAX_2FA_ATTEMPTS:
            request.session.pop(_SESSION_PENDING_UID, None)
            request.session.pop(_SESSION_ATTEMPTS, None)
            messages.error(
                request,
                'Too many incorrect attempts. Please log in again.',
            )
            return redirect('core:login')

        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            # Success — clear staging keys and log the user in
            request.session.pop(_SESSION_PENDING_UID, None)
            request.session.pop(_SESSION_ATTEMPTS, None)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            # Record login IP for IP-session locking
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
            login_ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR', '')
            request.session['login_ip'] = login_ip
            messages.success(request, f'Welcome back, {user.get_full_name()}!')
            return redirect(request.GET.get('next', 'core:dashboard'))
        else:
            remaining = _MAX_2FA_ATTEMPTS - attempts
            if remaining > 0:
                messages.error(request, f'Invalid code. {remaining} attempt{"s" if remaining > 1 else ""} remaining.')
            else:
                messages.error(request, 'Invalid code.')

    context = {
        'page_title': 'Two-Factor Verification',
        'user_name': user.get_full_name(),
    }
    return render(request, 'auth/verify_2fa.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Setup 2FA (enable)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def setup_2fa(request):
    """
    Enable TOTP two-factor authentication for the logged-in user.

    GET  → generate provisional secret, show QR code.
    POST → verify the code the user scanned, save secret, enable 2FA.
    """
    user = request.user

    if user.is_2fa_enabled:
        # Show the page so the user can see the disable form
        context = {
            'page_title': 'Two-Factor Authentication',
        }
        return render(request, 'auth/setup_2fa.html', context)

    if request.method == 'POST':
        provisional_secret = request.session.get(_SESSION_SETUP_SECRET)
        if not provisional_secret:
            messages.error(request, 'Session expired. Please try again.')
            return redirect('core:setup_2fa')

        code = request.POST.get('code', '').strip().replace(' ', '')
        totp = pyotp.TOTP(provisional_secret)

        if totp.verify(code, valid_window=1):
            user.totp_secret    = provisional_secret
            user.is_2fa_enabled = True
            user.save(update_fields=['totp_secret', 'is_2fa_enabled'])
            request.session.pop(_SESSION_SETUP_SECRET, None)
            messages.success(
                request,
                'Two-factor authentication has been enabled successfully. '
                'Keep your authenticator app safe.',
            )
            logger.info("2FA enabled for user %s", user.email)
            return redirect('core:dashboard')
        else:
            messages.error(request, 'Invalid code. Make sure your device time is correct and try again.')

    # GET (or failed POST) — (re-)generate provisional secret
    provisional_secret = pyotp.random_base32()
    request.session[_SESSION_SETUP_SECRET] = provisional_secret

    site_name = 'Seashore Microfinance'
    otp_uri   = pyotp.totp.TOTP(provisional_secret).provisioning_uri(
        name=user.email,
        issuer_name=site_name,
    )
    qr_data_uri = _make_qr_data_uri(otp_uri)

    context = {
        'page_title':          'Enable Two-Factor Authentication',
        'qr_data_uri':         qr_data_uri,
        'provisional_secret':  provisional_secret,
        'otp_uri':             otp_uri,
    }
    return render(request, 'auth/setup_2fa.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Disable 2FA
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['POST'])
def disable_2fa(request):
    """
    Disable TOTP 2FA for the logged-in user.

    Requires the current account password for confirmation (POST field
    ``current_password``).
    """
    user     = request.user
    password = request.POST.get('current_password', '')

    if not user.check_password(password):
        messages.error(request, 'Incorrect password. 2FA has not been disabled.')
        return redirect('core:setup_2fa')

    if not user.is_2fa_enabled:
        messages.info(request, '2FA is not currently enabled on your account.')
        return redirect('core:dashboard')

    user.totp_secret    = None
    user.is_2fa_enabled = False
    user.save(update_fields=['totp_secret', 'is_2fa_enabled'])
    messages.success(request, 'Two-factor authentication has been disabled.')
    logger.info("2FA disabled for user %s", user.email)
    return redirect('core:dashboard')
