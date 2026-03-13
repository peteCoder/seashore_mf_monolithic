"""
SMS Celery Tasks
================

Scheduled and on-demand SMS notifications via Africa's Talking.

Scheduled tasks (beat schedule in settings.py):
    - ``send_repayment_reminders``  — daily at 08:00 WAT
      Sends a reminder to every client whose next loan repayment is due in
      exactly 3 days and in exactly 1 day.

    - ``send_overdue_alerts``       — daily at 09:00 WAT
      Sends an alert to clients with overdue loans (status='overdue').

On-demand helpers (called by other views/tasks):
    - ``send_loan_disbursement_sms``
    - ``send_savings_deposit_confirmation_sms``
"""

import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled: repayment reminders
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='core.tasks.sms_tasks.send_repayment_reminders')
def send_repayment_reminders():
    """
    Send SMS reminders to clients whose next repayment date is 3 days or 1 day away.
    Runs daily at 08:00 WAT.
    """
    from core.models import Loan
    from core.sms_service import send_sms

    today = date.today()
    reminder_days = [1, 3]

    sent = 0
    for days_ahead in reminder_days:
        target_date = today + timedelta(days=days_ahead)
        loans = Loan.objects.filter(
            status__in=['active', 'overdue'],
            next_repayment_date=target_date,
        ).select_related('client', 'branch')

        for loan in loans:
            client = loan.client
            if not client.phone:
                continue

            amount = loan.installment_amount or 0
            message = (
                f"Dear {client.first_name}, your Seashore loan repayment of "
                f"NGN {amount:,.2f} is due in {days_ahead} day{'s' if days_ahead > 1 else ''} "
                f"({target_date.strftime('%d %b %Y')}). "
                f"Loan: {loan.loan_number}. Please ensure funds are available. "
                f"Thank you."
            )
            result = send_sms(client.phone, message)
            if result:
                sent += 1

    logger.info("Repayment reminders sent: %d", sent)
    return {'sent': sent}


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled: overdue alerts
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='core.tasks.sms_tasks.send_overdue_alerts')
def send_overdue_alerts():
    """
    Alert clients with overdue loans. Runs daily at 09:00 WAT.
    Only sends to loans overdue by 1, 7, 14, or 30 days to avoid alert fatigue.
    """
    from core.models import Loan
    from core.sms_service import send_sms

    today     = date.today()
    alert_intervals = {1, 7, 14, 30}

    sent = 0
    loans = Loan.objects.filter(
        status='overdue',
        next_repayment_date__lt=today,
    ).select_related('client')

    for loan in loans:
        if not loan.next_repayment_date or not loan.client.phone:
            continue

        days_overdue = (today - loan.next_repayment_date).days
        if days_overdue not in alert_intervals:
            continue

        client = loan.client
        message = (
            f"URGENT: Dear {client.first_name}, your Seashore loan {loan.loan_number} "
            f"is {days_overdue} day{'s' if days_overdue > 1 else ''} overdue. "
            f"Outstanding balance: NGN {loan.outstanding_balance:,.2f}. "
            f"Please make payment immediately or contact your branch to avoid penalties."
        )
        result = send_sms(client.phone, message)
        if result:
            sent += 1

    logger.info("Overdue SMS alerts sent: %d", sent)
    return {'sent': sent}


# ─────────────────────────────────────────────────────────────────────────────
# On-demand: loan disbursement confirmation
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='core.tasks.sms_tasks.send_loan_disbursement_sms')
def send_loan_disbursement_sms(loan_id: str):
    """
    Send disbursement confirmation SMS to the client.
    Call after a loan has been marked as disbursed.

    Parameters
    ----------
    loan_id : UUID string of the Loan record
    """
    from core.models import Loan
    from core.sms_service import send_sms

    try:
        loan = Loan.objects.select_related('client').get(id=loan_id)
    except Loan.DoesNotExist:
        logger.warning("send_loan_disbursement_sms: Loan %s not found", loan_id)
        return

    client = loan.client
    if not client.phone:
        return

    message = (
        f"Dear {client.first_name}, your Seashore loan of "
        f"NGN {loan.amount_disbursed or loan.principal_amount:,.2f} "
        f"(Ref: {loan.loan_number}) has been disbursed successfully. "
        f"First repayment date: {loan.first_repayment_date.strftime('%d %b %Y') if loan.first_repayment_date else 'TBD'}. "
        f"For enquiries call your branch. Thank you for choosing Seashore Microfinance."
    )
    send_sms(client.phone, message)


# ─────────────────────────────────────────────────────────────────────────────
# On-demand: savings deposit confirmation
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='core.tasks.sms_tasks.send_savings_deposit_confirmation_sms')
def send_savings_deposit_confirmation_sms(account_id: str, amount: str):
    """
    Send deposit confirmation SMS to the client.

    Parameters
    ----------
    account_id : UUID string of the SavingsAccount record
    amount     : Decimal amount deposited (as string for Celery serialisation)
    """
    from decimal import Decimal
    from core.models import SavingsAccount
    from core.sms_service import send_sms

    try:
        account = SavingsAccount.objects.select_related('client').get(id=account_id)
    except SavingsAccount.DoesNotExist:
        logger.warning("send_savings_deposit_confirmation_sms: Account %s not found", account_id)
        return

    client = account.client
    if not client.phone:
        return

    amt = Decimal(amount)
    message = (
        f"Dear {client.first_name}, a deposit of NGN {amt:,.2f} has been credited to your "
        f"Seashore savings account ({account.account_number}). "
        f"New balance: NGN {account.balance:,.2f}. "
        f"Thank you."
    )
    send_sms(client.phone, message)
