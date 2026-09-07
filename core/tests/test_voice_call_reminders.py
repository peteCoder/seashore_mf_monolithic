"""
Tests for the AI voice-call reminder feature — staff-initiated only, via
the "Call" button on a loan row in the client detail page
(core/views/client_views.client_call_reminder). There is no
scheduled/automatic calling.

Covers core/voice_service.py, core/views/voice_views.py (Twilio webhooks),
and the client_call_reminder view itself.

Twilio/ElevenLabs credentials are blank in every test environment (see
.env / settings_test.py), so these tests exercise the "not configured"
and webhook-plumbing paths rather than placing real calls.
"""

from decimal import Decimal

from django.test import TestCase, RequestFactory
from django.urls import reverse

from core.models import Loan, VoiceCallLog
from core.tests.factories import make_branch, make_user, make_client, make_loan_product
from core.voice_service import build_reminder_message, initiate_call
from core.views.voice_views import voice_twiml, voice_status_callback


class InitiateCallUnconfiguredTests(TestCase):
    """With no TWILIO_*/ELEVENLABS_API_KEY set, calls must fail loudly (a
    logged VoiceCallLog row), never silently or by raising."""

    def setUp(self):
        self.branch = make_branch()
        self.staff = make_user(self.branch, role='staff')
        self.client_obj = make_client(self.branch, self.staff)

    def test_creates_failed_log_when_unconfigured(self):
        call_log = initiate_call(self.client_obj, purpose='manual')
        self.assertEqual(call_log.status, 'failed')
        self.assertIn('not configured', call_log.error_message)
        self.assertTrue(VoiceCallLog.objects.filter(id=call_log.id).exists())

    def test_creates_failed_log_when_no_phone(self):
        self.client_obj.phone = ''
        self.client_obj.save(update_fields=['phone'])
        call_log = initiate_call(self.client_obj, purpose='manual')
        self.assertEqual(call_log.status, 'failed')
        self.assertIn('phone', call_log.error_message.lower())


class BuildReminderMessageTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.staff = make_user(self.branch, role='staff')
        self.client_obj = make_client(self.branch, self.staff)

    def test_due_reminder_mentions_due_date_not_overdue(self):
        msg = build_reminder_message(self.client_obj, purpose='due_reminder')
        self.assertIn(self.client_obj.first_name, msg)
        self.assertNotIn('overdue', msg.lower())

    def test_overdue_alert_mentions_overdue(self):
        msg = build_reminder_message(self.client_obj, purpose='overdue_alert')
        self.assertIn('overdue', msg.lower())


class VoiceWebhookTests(TestCase):
    """
    Webhook views have no login_required (Twilio itself calls them) and skip
    signature validation when TWILIO_AUTH_TOKEN is blank — exactly the state
    every test environment is in, matching the "not configured" default.
    """

    def setUp(self):
        self.branch = make_branch()
        self.staff = make_user(self.branch, role='staff')
        self.client_obj = make_client(self.branch, self.staff)
        self.call_log = VoiceCallLog.objects.create(
            client=self.client_obj,
            phone=self.client_obj.phone,
            purpose='manual',
            message_text='Hello, this is a test reminder.',
            audio_url='https://res.cloudinary.com/demo/video/upload/voice_calls/test.mp3',
            status='queued',
        )
        self.rf = RequestFactory()

    def test_twiml_plays_audio_url_when_present(self):
        request = self.rf.post(
            reverse('core:voice_twiml', args=[self.call_log.id])
        )
        response = voice_twiml(request, self.call_log.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<Play>', response.content)
        self.assertIn(self.call_log.audio_url.encode(), response.content)

    def test_twiml_falls_back_to_say_without_audio(self):
        self.call_log.audio_url = ''
        self.call_log.save(update_fields=['audio_url'])
        request = self.rf.post(
            reverse('core:voice_twiml', args=[self.call_log.id])
        )
        response = voice_twiml(request, self.call_log.id)
        self.assertIn(b'<Say>', response.content)

    def test_twiml_404_for_unknown_call_log(self):
        import uuid
        request = self.rf.post(
            reverse('core:voice_twiml', args=[uuid.uuid4()])
        )
        with self.assertRaises(Exception):
            voice_twiml(request, uuid.uuid4())

    def test_status_callback_updates_log(self):
        request = self.rf.post(
            reverse('core:voice_status_callback', args=[self.call_log.id]),
            data={'CallStatus': 'completed', 'CallSid': 'CA123', 'CallDuration': '42'},
        )
        response = voice_status_callback(request, self.call_log.id)
        self.assertEqual(response.status_code, 204)

        self.call_log.refresh_from_db()
        self.assertEqual(self.call_log.status, 'completed')
        self.assertEqual(self.call_log.call_sid, 'CA123')
        self.assertEqual(self.call_log.duration_seconds, 42)
        self.assertIsNotNone(self.call_log.completed_at)


class ClientCallReminderViewTests(TestCase):
    """
    The "Call" button on the client detail page's Loans tab — this is the
    ONLY way a voice reminder call gets placed; there is no beat schedule
    for it any more.
    """

    def setUp(self):
        self.branch = make_branch(code='CCR001')
        self.staff = make_user(self.branch, role='staff', email='ccr_staff@test.com')
        self.other_staff = make_user(self.branch, role='staff', email='ccr_other@test.com')
        self.client_obj = make_client(self.branch, self.staff, email='ccr_client@test.com')
        self.product = make_loan_product(code='CCRP001')
        self.loan = Loan.objects.create(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=4,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('30000.00'),
        )

    def _url(self):
        return reverse('core:client_call_reminder', args=[self.client_obj.id, self.loan.id])

    def test_get_request_places_no_call(self):
        self.client.force_login(self.staff)
        response = self.client.get(self._url())
        self.assertRedirects(response, reverse('core:client_detail', args=[self.client_obj.id]))
        self.assertFalse(VoiceCallLog.objects.exists())

    def test_post_creates_call_log_and_reports_failure_when_unconfigured(self):
        self.client.force_login(self.staff)
        response = self.client.post(self._url(), follow=True)
        self.assertEqual(response.status_code, 200)

        call_log = VoiceCallLog.objects.get(loan=self.loan)
        self.assertEqual(call_log.status, 'failed')
        self.assertEqual(call_log.purpose, 'manual')
        self.assertEqual(call_log.initiated_by, self.staff)

        messages_text = [str(m) for m in response.context['messages']]
        self.assertTrue(any('Could not place the reminder call' in m for m in messages_text))

    def test_zero_outstanding_balance_blocks_call(self):
        self.loan.outstanding_balance = Decimal('0.00')
        self.loan.save(update_fields=['outstanding_balance'])
        self.client.force_login(self.staff)
        response = self.client.post(self._url(), follow=True)

        self.assertFalse(VoiceCallLog.objects.exists())
        messages_text = [str(m) for m in response.context['messages']]
        self.assertTrue(any('no outstanding balance' in m for m in messages_text))

    def test_no_phone_blocks_call(self):
        self.client_obj.phone = ''
        self.client_obj.save(update_fields=['phone'])
        self.client.force_login(self.staff)
        response = self.client.post(self._url(), follow=True)

        self.assertFalse(VoiceCallLog.objects.exists())
        messages_text = [str(m) for m in response.context['messages']]
        self.assertTrue(any('no phone number' in m for m in messages_text))

    def test_staff_cannot_call_about_a_client_not_assigned_to_them(self):
        self.client.force_login(self.other_staff)
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(VoiceCallLog.objects.exists())


class ClientDetailCallButtonRenderTests(TestCase):
    """
    The client detail page's main action bar shows a "Call Client" button
    whenever the client has an outstanding loan — not just the per-loan
    button buried in the Loans tab — so the action is easy to find. It
    always renders (even with no phone on file) but gives immediate
    client-side feedback instead of silently submitting.
    """

    def setUp(self):
        self.branch = make_branch(code='CDB001')
        self.staff = make_user(self.branch, role='staff', email='cdb_staff@test.com')
        self.client_obj = make_client(self.branch, self.staff, email='cdb_client@test.com')
        self.product = make_loan_product(code='CDBP001')

    def _detail_url(self):
        return reverse('core:client_detail', args=[self.client_obj.id])

    def test_call_client_button_renders_with_outstanding_loan(self):
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=4,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('30000.00'),
        )
        self.client.force_login(self.staff)
        response = self.client.get(self._detail_url())
        html = response.content.decode()
        expected_action = reverse('core:client_call_reminder', args=[self.client_obj.id, loan.id])
        self.assertIn(expected_action, html)
        self.assertIn('Call Client', html)

    def test_call_client_button_absent_without_outstanding_loan(self):
        self.client.force_login(self.staff)
        response = self.client.get(self._detail_url())
        html = response.content.decode()
        self.assertNotIn('Call Client', html)

    def test_call_client_button_warns_client_side_when_no_phone(self):
        self.client_obj.phone = ''
        self.client_obj.save(update_fields=['phone'])
        loan = Loan.objects.create(
            client=self.client_obj, loan_product=self.product, branch=self.branch,
            principal_amount=Decimal('100000.00'), duration_months=4,
            disbursement_method='cash', created_by=self.staff,
            purpose='Business', status='active',
            outstanding_balance=Decimal('30000.00'),
        )
        self.client.force_login(self.staff)
        response = self.client.get(self._detail_url())
        html = response.content.decode()
        # Button still renders (visible), but the confirm() is swapped for
        # an alert() that explains why, and the form won't submit.
        self.assertIn('Call Client', html)
        self.assertIn('does not have a phone number on file', html)
        self.assertIn('return false;', html)
