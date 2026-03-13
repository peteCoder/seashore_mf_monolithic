"""
SMS Service — Africa's Talking
================================

Thin wrapper around the Africa's Talking Python SDK.

Usage
-----
    from core.sms_service import send_sms, send_sms_bulk

    send_sms('+2348012345678', 'Hello from Seashore!')

The module reads AT_USERNAME, AT_API_KEY, and AT_SENDER_ID from Django settings.
If AT_API_KEY is empty (default in development) the function logs a warning and
returns without attempting to send, so tests and local dev never make live calls.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _get_sms_service():
    """Initialise and return the Africa's Talking SMS service object."""
    import africastalking
    username = getattr(settings, 'AT_USERNAME', 'sandbox')
    api_key  = getattr(settings, 'AT_API_KEY',  '')
    if not api_key:
        return None
    africastalking.initialize(username, api_key)
    return africastalking.SMS


def send_sms(phone: str, message: str) -> dict:
    """
    Send a single SMS.

    Parameters
    ----------
    phone   : E.164 phone number, e.g. ``'+2348012345678'``
    message : Plain-text message body (max 160 chars per segment)

    Returns
    -------
    dict    : Africa's Talking response data, or ``{}`` when AT is not configured
    """
    sms = _get_sms_service()
    if sms is None:
        logger.warning(
            "SMS not sent to %s — AT_API_KEY is not configured. "
            "Set AT_USERNAME and AT_API_KEY in .env to enable SMS.",
            phone,
        )
        return {}

    sender_id = getattr(settings, 'AT_SENDER_ID', '') or None
    try:
        response = sms.send(message, [phone], sender_id=sender_id)
        logger.info("SMS sent to %s: %s", phone, response)
        return response
    except Exception as exc:
        logger.error("SMS send failed for %s: %s", phone, exc)
        return {}


def send_sms_bulk(recipients: list[str], message: str) -> dict:
    """
    Send the same SMS to multiple recipients.

    Parameters
    ----------
    recipients : List of E.164 phone numbers
    message    : Plain-text message body

    Returns
    -------
    dict : Africa's Talking response data, or ``{}`` when AT is not configured
    """
    sms = _get_sms_service()
    if sms is None:
        logger.warning(
            "Bulk SMS not sent to %d recipients — AT_API_KEY is not configured.",
            len(recipients),
        )
        return {}

    sender_id = getattr(settings, 'AT_SENDER_ID', '') or None
    try:
        response = sms.send(message, recipients, sender_id=sender_id)
        logger.info("Bulk SMS sent to %d recipients: %s", len(recipients), response)
        return response
    except Exception as exc:
        logger.error("Bulk SMS send failed: %s", exc)
        return {}
