"""
Voice Call Service — Twilio Voice + ElevenLabs
================================================

Places an outbound AI-voice phone call to a client reminding them of a loan
repayment that's due or overdue. Staff-initiated only — triggered by the
"Call" button on a loan row in the client detail page
(core/views/client_views.client_call_reminder). There is deliberately no
scheduled/automatic calling; mirrors the shape of core/sms_service.py
otherwise.

Pipeline
--------
1. Build the reminder script as plain text (build_reminder_message()).
2. Synthesise it to speech with ElevenLabs and upload the audio to
   Cloudinary (already used elsewhere in this app for media storage) so it
   has a public URL Twilio can fetch mid-call.
3. Ask Twilio to place the call, pointing it at our TwiML webhook
   (core/views/voice_views.voice_twiml), which just tells Twilio to
   <Play> that audio URL, then hang up.
4. Twilio posts call-status updates back to our status-callback webhook
   (voice_status_callback) as the call progresses; that view updates the
   VoiceCallLog row's status/duration/completed_at.

Every call attempt — including ones that fail before ever reaching Twilio
(no phone number on file, provider not configured, TTS failure, etc.) —
creates a VoiceCallLog row, so failures stay auditable instead of silently
vanishing. This mirrors send_sms() logging a warning and returning {} rather
than raising when unconfigured; nothing here calls out in dev unless every
one of the .env vars below is actually set.

Configuration (.env) — all blank by default:
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
    SITE_BASE_URL
        Public base URL Twilio can reach for webhooks — an ngrok URL in
        dev, your real domain in production. Twilio calls back into this
        app from the outside, so localhost will not work for a live call.
"""

import logging

from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(
        getattr(settings, 'TWILIO_ACCOUNT_SID', '')
        and getattr(settings, 'TWILIO_AUTH_TOKEN', '')
        and getattr(settings, 'TWILIO_FROM_NUMBER', '')
        and getattr(settings, 'ELEVENLABS_API_KEY', '')
    )


def _get_twilio_client():
    from twilio.rest import Client
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def synthesize_speech(text: str):
    """
    Convert text to speech via the ElevenLabs REST API.
    Returns raw MP3 bytes, or None if not configured / the request fails.
    """
    api_key = getattr(settings, 'ELEVENLABS_API_KEY', '')
    if not api_key:
        logger.warning("ElevenLabs not configured — ELEVENLABS_API_KEY is blank.")
        return None

    voice_id = getattr(settings, 'ELEVENLABS_VOICE_ID', '') or '21m00Tcm4TlvDq8ikWAM'
    import requests
    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.content
    except Exception as exc:
        logger.error("ElevenLabs speech synthesis failed: %s", exc)
        return None


def _upload_audio(audio_bytes: bytes, public_id: str) -> str:
    """Upload synthesised audio to Cloudinary and return its public URL."""
    import cloudinary.uploader
    result = cloudinary.uploader.upload(
        audio_bytes,
        resource_type='video',  # Cloudinary serves non-image/raw audio under 'video'
        public_id=f"voice_calls/{public_id}",
        format='mp3',
        overwrite=True,
    )
    return result['secure_url']


def build_reminder_message(client, loan=None, schedule_row=None, purpose='due_reminder') -> str:
    """Build the spoken script for a repayment reminder call."""
    name = client.first_name or 'Customer'

    if schedule_row is not None:
        amount = schedule_row.outstanding_amount or schedule_row.total_amount
        due_date = schedule_row.due_date
    else:
        amount = loan.installment_amount if loan else None
        due_date = loan.next_repayment_date if loan else None

    amount_txt = f"{amount:,.2f} Naira" if amount is not None else "an outstanding amount"
    due_txt = due_date.strftime('%A, %d %B %Y') if due_date else "soon"
    loan_ref = loan.loan_number if loan else ''

    if purpose == 'overdue_alert':
        return (
            f"Hello {name}, this is an automated call from Seashore Microfinance. "
            f"Your loan {loan_ref} repayment of {amount_txt} was due on {due_txt} "
            f"and is now overdue. Please make payment as soon as possible to avoid "
            f"penalties, or contact your branch if you have already paid. Thank you."
        )
    return (
        f"Hello {name}, this is an automated call from Seashore Microfinance. "
        f"This is a reminder that your loan {loan_ref} repayment of {amount_txt} "
        f"is due on {due_txt}. Please ensure funds are available. Thank you."
    )


def initiate_call(client, loan=None, schedule_row=None, purpose='due_reminder', initiated_by=None):
    """
    Place an outbound AI-voice reminder call to `client`.

    Always creates and returns a VoiceCallLog row, whether or not the call
    actually reaches Twilio — check `.status` / `.error_message` on the
    returned row to see what happened.
    """
    from django.utils import timezone
    from core.models import VoiceCallLog

    message = build_reminder_message(client, loan, schedule_row, purpose)
    if schedule_row is not None:
        amount = schedule_row.outstanding_amount or schedule_row.total_amount
    else:
        amount = loan.installment_amount if loan else None

    call_log = VoiceCallLog.objects.create(
        client=client,
        loan=loan,
        schedule_row=schedule_row,
        purpose=purpose,
        phone=client.phone or '',
        amount_due=amount,
        message_text=message,
        initiated_by=initiated_by,
        status='pending',
    )

    if not client.phone:
        call_log.status = 'failed'
        call_log.error_message = 'Client has no phone number on file.'
        call_log.save(update_fields=['status', 'error_message'])
        return call_log

    if not _is_configured():
        logger.warning(
            "Voice call not placed to %s — Twilio/ElevenLabs are not configured. "
            "Set TWILIO_* and ELEVENLABS_API_KEY in .env to enable calls.",
            client.phone,
        )
        call_log.status = 'failed'
        call_log.error_message = 'Voice calling is not configured.'
        call_log.save(update_fields=['status', 'error_message'])
        return call_log

    audio_bytes = synthesize_speech(message)
    if not audio_bytes:
        call_log.status = 'failed'
        call_log.error_message = 'Speech synthesis failed.'
        call_log.save(update_fields=['status', 'error_message'])
        return call_log

    try:
        audio_url = _upload_audio(audio_bytes, str(call_log.id))
    except Exception as exc:
        logger.error("Audio upload failed for call %s: %s", call_log.id, exc)
        call_log.status = 'failed'
        call_log.error_message = f'Audio upload failed: {exc}'
        call_log.save(update_fields=['status', 'error_message'])
        return call_log

    call_log.audio_url = audio_url
    call_log.save(update_fields=['audio_url'])

    base_url = getattr(settings, 'SITE_BASE_URL', '').rstrip('/')
    twiml_url = f"{base_url}{reverse('core:voice_twiml', args=[call_log.id])}"
    status_callback_url = f"{base_url}{reverse('core:voice_status_callback', args=[call_log.id])}"

    try:
        twilio_client = _get_twilio_client()
        call = twilio_client.calls.create(
            to=client.phone,
            from_=settings.TWILIO_FROM_NUMBER,
            url=twiml_url,
            status_callback=status_callback_url,
            status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
            status_callback_method='POST',
        )
        call_log.call_sid = call.sid
        call_log.status = call.status or 'queued'
        call_log.initiated_at = timezone.now()
        call_log.save(update_fields=['call_sid', 'status', 'initiated_at'])
        logger.info("Voice call placed to %s (SID %s)", client.phone, call.sid)
    except Exception as exc:
        logger.error("Twilio call failed for %s: %s", client.phone, exc)
        call_log.status = 'failed'
        call_log.error_message = str(exc)
        call_log.save(update_fields=['status', 'error_message'])

    return call_log
