"""
Voice Call Webhooks — Twilio
=============================

Public endpoints Twilio itself calls back into while placing/running an
AI-voice reminder call started by core/voice_service.initiate_call(). These
are NOT staff-facing pages: no login, no CSRF token (Twilio can't supply
either), authenticated instead by Twilio's request-signature header.

    voice_twiml            — Twilio fetches this when the call connects; we
                              respond with TwiML telling it to <Play> the
                              pre-synthesised ElevenLabs audio for this call.
    voice_status_callback  — Twilio POSTs call-progress updates here
                              (ringing → in-progress → completed/...); we
                              mirror them onto the VoiceCallLog row.
"""

import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.models import VoiceCallLog

logger = logging.getLogger(__name__)

# Call statuses that mean the call has finished and won't progress further.
_TERMINAL_STATUSES = {'completed', 'busy', 'failed', 'no-answer', 'canceled'}


def _validate_twilio_request(request, call_log_id) -> bool:
    """
    Verify the request actually came from Twilio using the X-Twilio-Signature
    header. Reconstructs the URL from SITE_BASE_URL (the same base the call
    was created with in voice_service.initiate_call) rather than
    request.build_absolute_uri(), since a proxy in front of Django can
    rewrite scheme/host in ways that would otherwise break the signature
    check.

    Skipped (returns True) when TWILIO_AUTH_TOKEN isn't configured — at that
    point no real call could have been placed by this app in the first
    place, so there's nothing legitimate to protect yet.
    """
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    if not auth_token:
        return True

    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    if not signature:
        return False

    from twilio.request_validator import RequestValidator
    base_url = getattr(settings, 'SITE_BASE_URL', '').rstrip('/')
    url = f"{base_url}{request.path}"
    validator = RequestValidator(auth_token)
    return validator.validate(url, request.POST.dict(), signature)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def voice_twiml(request, call_log_id):
    """Return the TwiML that plays the reminder message for this call."""
    from twilio.twiml.voice_response import VoiceResponse

    if not _validate_twilio_request(request, call_log_id):
        return HttpResponseForbidden("Invalid Twilio signature")

    try:
        call_log = VoiceCallLog.objects.get(id=call_log_id)
    except (VoiceCallLog.DoesNotExist, ValueError):
        raise Http404

    response = VoiceResponse()
    if call_log.audio_url:
        response.play(call_log.audio_url)
    else:
        # Shouldn't happen — initiate_call() only places the Twilio call
        # after the audio has been synthesised and uploaded — but fall back
        # to a plain-TTS read of the script rather than a silent dead call.
        response.say(call_log.message_text or "We were unable to load your reminder message.")
    response.hangup()

    return HttpResponse(str(response), content_type='text/xml')


@csrf_exempt
@require_http_methods(["POST"])
def voice_status_callback(request, call_log_id):
    """Mirror Twilio's call-status updates onto the VoiceCallLog row."""
    if not _validate_twilio_request(request, call_log_id):
        return HttpResponseForbidden("Invalid Twilio signature")

    try:
        call_log = VoiceCallLog.objects.get(id=call_log_id)
    except (VoiceCallLog.DoesNotExist, ValueError):
        raise Http404

    call_status = request.POST.get('CallStatus', '')
    call_sid = request.POST.get('CallSid', '')
    duration = request.POST.get('CallDuration', '')

    update_fields = []
    if call_status:
        call_log.status = call_status
        update_fields.append('status')
    if call_sid and not call_log.call_sid:
        call_log.call_sid = call_sid
        update_fields.append('call_sid')
    if duration.isdigit():
        call_log.duration_seconds = int(duration)
        update_fields.append('duration_seconds')
    if call_status in _TERMINAL_STATUSES and not call_log.completed_at:
        call_log.completed_at = timezone.now()
        update_fields.append('completed_at')

    if update_fields:
        call_log.save(update_fields=update_fields)

    logger.info("Voice call %s status update: %s", call_log_id, call_status)
    return HttpResponse(status=204)
