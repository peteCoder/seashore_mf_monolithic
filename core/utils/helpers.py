from django.utils import timezone
from decimal import Decimal
from datetime import timedelta, date as date_type
from dateutil.relativedelta import relativedelta
from core.utils.money import MoneyCalculator


# =============================================================================
# BUSINESS-DAY UTILITIES
# =============================================================================

def is_business_day(d, holidays=None):
    """Return True if d is Monday–Friday and not a public holiday."""
    if d.weekday() >= 5:  # 0=Mon … 4=Fri; 5=Sat, 6=Sun
        return False
    if holidays and d in holidays:
        return False
    return True


def next_business_day(d, holidays=None):
    """
    Return d if it is already a business day, otherwise advance to the next
    Monday–Friday that is not a public holiday.
    Pass a set of date objects as `holidays` to skip those days too.
    """
    while not is_business_day(d, holidays):
        d += timedelta(days=1)
    return d


def add_one_business_day(d, holidays=None):
    """
    Advance d by exactly one business day (Mon–Fri, skipping weekends and
    any dates in the optional `holidays` set).

    Monday → Tuesday
    Friday → Monday
    Saturday → Monday  (advance to next business day first, then +1 business day)
    """
    d += timedelta(days=1)
    return next_business_day(d, holidays)


def count_business_days_in_months(start_date, num_months, holidays=None):
    """
    Count the number of Mon–Fri days (excluding public holidays) in the period
    [start_date, start_date + num_months).

    Used to determine how many daily installments a loan has when weekend
    days are excluded.
    """
    end_date = start_date + relativedelta(months=num_months)
    total = 0
    current = start_date
    while current < end_date:
        if is_business_day(current, holidays):
            total += 1
        current += timedelta(days=1)
    return total


# =============================================================================
# HELPER FUNCTION: GENERATE REPAYMENT SCHEDULE
# =============================================================================

def generate_repayment_schedule(loan):
    """
    Generate repayment schedule for a loan with status indicators.

    For **daily** repayment loans, due dates are assigned to Mon–Fri only
    (Saturdays and Sundays are skipped).  The installment count reflects
    the number of working days in the loan period, not calendar days.

    Returns:
        list: Schedule with installment details and status
    """
    if not loan.disbursement_date and loan.status != 'approved':
        return []

    # Load public holidays once for the entire schedule build.
    # Lazy import avoids circular dependency (all_models imports helpers at module level).
    try:
        from core.models.all_models import PublicHoliday
        holidays = set(PublicHoliday.objects.values_list('date', flat=True))
    except Exception:
        holidays = set()

    schedule = []

    # Use the installment count already stored on the loan (which already
    # accounts for business days when frequency is 'daily').
    num_installments = loan.number_of_installments
    if not num_installments or num_installments <= 0:
        return []

    installment_amount = loan.installment_amount
    total_amount       = loan.total_repayment

    # Determine interest method for per-installment breakdown
    is_reducing = getattr(loan, 'interest_type', 'flat') == 'reducing_balance'

    if is_reducing:
        # Amortisation: each period's interest is on the outstanding principal.
        # Period rate matches the repayment frequency (same logic as calculate_loan_details).
        monthly_rate = Decimal(str(loan.monthly_interest_rate or 0))
        _period_rate_map = {
            'daily':       monthly_rate / 20,
            'weekly':      monthly_rate / 4,
            'fortnightly': monthly_rate / 2,
            'monthly':     monthly_rate,
            'yearly':      monthly_rate * 12,
        }
        period_rate = _period_rate_map.get(loan.repayment_frequency, monthly_rate)
        # Remaining principal tracked separately for amortisation
        rb_principal = Decimal(str(loan.principal_amount))
        # Placeholders — will be overridden inside the loop
        interest_per_installment  = Decimal('0')
        principal_per_installment = Decimal('0')
    else:
        # Flat rate: interest and principal split evenly across all installments.
        interest_per_installment  = loan.total_interest   / num_installments
        principal_per_installment = loan.principal_amount / num_installments
        period_rate = Decimal('0')
        rb_principal = Decimal('0')

    remaining_balance = total_amount

    # First due date — always one period after disbursement (set by disburse())
    if loan.disbursement_date:
        if loan.first_repayment_date:
            first_due = loan.first_repayment_date
        else:
            # Fallback: derive from disbursement date + grace period + 1 period
            grace_days = 0
            try:
                if loan.loan_product_id and loan.loan_product:
                    grace_days = loan.loan_product.grace_period_days or 0
            except Exception:
                pass
            schedule_start = loan.disbursement_date.date() + timedelta(days=grace_days)
            first_due = loan.calculate_next_payment_date(schedule_start)
    else:
        # Approved but not yet disbursed — use a placeholder
        first_due = timezone.now().date() + timedelta(days=7)

    # Ensure the first due date never falls on a weekend or public holiday
    first_due = next_business_day(first_due, holidays)

    today = timezone.now().date()
    total_installments_paid = (
        int(loan.amount_paid / installment_amount)
        if installment_amount and installment_amount > 0
        else 0
    )

    # Grace period (in days) from the loan product
    grace_days = 0
    try:
        if loan.loan_product_id and loan.loan_product:
            grace_days = loan.loan_product.grace_period_days or 0
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Build the date sequence                                             #
    # ------------------------------------------------------------------ #
    current_due = first_due

    for i in range(num_installments):
        installment_number = i + 1

        if i == 0:
            due_date = current_due
        else:
            # Advance by one period, then shift forward if it lands on a weekend or holiday
            if loan.repayment_frequency == 'daily':
                due_date = add_one_business_day(current_due, holidays)
            elif loan.repayment_frequency == 'weekly':
                due_date = next_business_day(current_due + timedelta(weeks=1), holidays)
            elif loan.repayment_frequency == 'fortnightly':
                due_date = next_business_day(current_due + timedelta(weeks=2), holidays)
            elif loan.repayment_frequency == 'yearly':
                due_date = next_business_day(current_due + relativedelta(years=1), holidays)
            else:  # monthly
                due_date = next_business_day(current_due + relativedelta(months=1), holidays)

        current_due = due_date

        # ---- status flags -------------------------------------------- #
        is_paid     = False
        is_overdue  = False
        is_upcoming = False
        days_until  = None
        days_overdue_val = None

        overdue_threshold = due_date + timedelta(days=grace_days)

        if installment_number <= total_installments_paid:
            is_paid = True
        elif overdue_threshold < today:
            is_overdue = True
            days_overdue_val = (today - overdue_threshold).days
        elif (due_date - today).days <= 7:
            is_upcoming = True
            days_until = (due_date - today).days

        # ---- amounts -------------------------------------------------- #
        if is_reducing:
            # Interest this period = outstanding principal × period rate
            interest_this = MoneyCalculator.round_money(rb_principal * period_rate)
            principal_this = installment_amount - interest_this
            # Last installment absorbs rounding
            if installment_number == num_installments:
                principal_this = rb_principal
                interest_this  = installment_amount - principal_this
                interest_this  = max(interest_this, Decimal('0'))
            rb_principal -= principal_this
            rb_principal = max(rb_principal, Decimal('0'))
            current_installment   = installment_amount if installment_number < num_installments else remaining_balance
            interest_per_installment  = interest_this
            principal_per_installment = principal_this
        else:
            if installment_number == num_installments:
                current_installment = remaining_balance  # absorb rounding
            else:
                current_installment = installment_amount

        remaining_balance -= current_installment

        status = 'paid' if is_paid else ('overdue' if is_overdue else 'pending')

        schedule.append({
            'installment_number':  installment_number,
            'due_date':            due_date,
            'principal_amount':    principal_per_installment,
            'interest_amount':     interest_per_installment,
            'installment_amount':  current_installment,
            'total_amount':        current_installment,  # template alias
            'remaining_balance':   max(remaining_balance, Decimal('0')),
            'status':              status,
            'is_paid':             is_paid,
            'is_overdue':          is_overdue,
            'is_upcoming':         is_upcoming,
            'days_until':          days_until,
            'days_overdue':        days_overdue_val,
        })

    return schedule


