"""
Decimal and Money Calculation Utilities
========================================

Provides consistent rounding and money calculations across the system
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_UP


class MoneyCalculator:
    """
    Consistent money calculations with proper rounding
    
    Usage:
        total = MoneyCalculator.round_money(123.456)  # 123.46
        fee = MoneyCalculator.calculate_percentage(1000, 0.035)  # 35.00
    """
    
    # Rounding precision constants
    TWO_PLACES = Decimal('0.01')
    FOUR_PLACES = Decimal('0.0001')
    
    @staticmethod
    def round_money(amount, places=None, rounding=ROUND_HALF_UP):
        """
        Round amount to specified decimal places
        
        Args:
            amount: Amount to round (can be Decimal, int, float, str)
            places: Decimal precision (default: 2 places)
            rounding: Rounding mode (default: ROUND_HALF_UP)
        
        Returns:
            Decimal: Rounded amount
        """
        if amount is None:
            return Decimal('0.00')
        
        if places is None:
            places = MoneyCalculator.TWO_PLACES
        
        return Decimal(str(amount)).quantize(places, rounding=rounding)
    
    @staticmethod
    def calculate_percentage(amount, rate, places=None):
        """
        Calculate percentage of amount
        
        Args:
            amount: Base amount
            rate: Percentage rate (e.g., 0.035 for 3.5%)
            places: Decimal precision (default: 2 places)
        
        Returns:
            Decimal: Calculated percentage
        
        Example:
            >>> MoneyCalculator.calculate_percentage(10000, 0.035)
            Decimal('350.00')
        """
        if not amount or not rate:
            return Decimal('0.00')
        
        result = Decimal(str(amount)) * Decimal(str(rate))
        return MoneyCalculator.round_money(result, places)
    
    @staticmethod
    def safe_divide(numerator, denominator, default=Decimal('0.00'), places=None):
        """
        Safe division with zero-handling
        
        Args:
            numerator: Number to divide
            denominator: Divisor
            default: Return value if denominator is zero
            places: Decimal precision
        
        Returns:
            Decimal: Result or default if denominator is zero
        """
        if not denominator or Decimal(str(denominator)) == 0:
            return default
        
        result = Decimal(str(numerator)) / Decimal(str(denominator))
        return MoneyCalculator.round_money(result, places)
    
    @staticmethod
    def sum_amounts(*amounts):
        """
        Sum multiple amounts safely
        
        Args:
            *amounts: Variable number of amounts to sum
        
        Returns:
            Decimal: Sum of all amounts
        """
        total = Decimal('0.00')
        for amount in amounts:
            if amount:
                total += Decimal(str(amount))
        return MoneyCalculator.round_money(total)
    
    @staticmethod
    def calculate_interest(principal, rate, periods, method='flat'):
        """
        Calculate interest based on method
        
        Args:
            principal: Loan principal
            rate: Interest rate per period
            periods: Number of periods
            method: 'flat' or 'reducing_balance'
        
        Returns:
            Decimal: Total interest
        """
        principal = Decimal(str(principal))
        rate = Decimal(str(rate))
        periods = int(periods)
        
        if method == 'flat':
            # Flat rate: Principal × Rate × Periods
            interest = principal * rate * periods
        elif method == 'reducing_balance':
            # Reducing balance (simplified)
            # More complex calculation needed for true reducing balance
            monthly_payment = MoneyCalculator.calculate_emi(principal, rate, periods)
            total_payment = monthly_payment * periods
            interest = total_payment - principal
        else:
            raise ValueError(f"Unknown interest calculation method: {method}")
        
        return MoneyCalculator.round_money(interest)
    
    @staticmethod
    def calculate_emi(principal, rate, periods):
        """
        Calculate Equal Monthly Installment (EMI)
        
        Formula: P × r × (1+r)^n / ((1+r)^n - 1)
        
        Args:
            principal: Loan principal
            rate: Interest rate per period
            periods: Number of periods
        
        Returns:
            Decimal: EMI amount
        """
        if not rate or rate == 0:
            # If no interest, just divide principal by periods
            return MoneyCalculator.safe_divide(principal, periods)
        
        principal = Decimal(str(principal))
        rate = Decimal(str(rate))
        periods = int(periods)
        
        # EMI formula
        factor = (1 + rate) ** periods
        emi = principal * rate * factor / (factor - 1)
        
        return MoneyCalculator.round_money(emi)
    
    @staticmethod
    def validate_amount(amount, min_amount=None, max_amount=None):
        """
        Validate amount is within acceptable range
        
        Args:
            amount: Amount to validate
            min_amount: Minimum acceptable amount
            max_amount: Maximum acceptable amount
        
        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            amount = Decimal(str(amount))
        except:
            return False, "Invalid amount format"
        
        if amount < 0:
            return False, "Amount cannot be negative"
        
        if min_amount is not None:
            if amount < Decimal(str(min_amount)):
                return False, f"Amount must be at least {min_amount}"
        
        if max_amount is not None:
            if amount > Decimal(str(max_amount)):
                return False, f"Amount cannot exceed {max_amount}"
        
        return True, ""
    
    @staticmethod
    def format_currency(amount, currency='NGN', symbol='₦'):
        """
        Format amount as currency string
        
        Args:
            amount: Amount to format
            currency: Currency code
            symbol: Currency symbol
        
        Returns:
            str: Formatted currency string
        
        Example:
            >>> MoneyCalculator.format_currency(1234567.89)
            '₦1,234,567.89'
        """
        amount = MoneyCalculator.round_money(amount)
        return f"{symbol}{amount:,.2f}"


class InterestCalculator:
    """
    Specialized interest calculations for loans
    """
    
    @staticmethod
    def calculate_flat_interest(principal, monthly_rate, months):
        """
        Calculate flat rate interest
        
        Args:
            principal: Loan principal
            monthly_rate: Monthly interest rate (e.g., 0.035 for 3.5%)
            months: Loan duration in months
        
        Returns:
            dict: Interest details
        """
        principal = Decimal(str(principal))
        monthly_rate = Decimal(str(monthly_rate))
        
        # Total interest = Principal × Rate × Months
        total_interest = principal * monthly_rate * months
        total_interest = MoneyCalculator.round_money(total_interest)
        
        # Total repayment
        total_repayment = principal + total_interest
        
        # Monthly installment
        monthly_installment = total_repayment / months
        monthly_installment = MoneyCalculator.round_money(monthly_installment, rounding=ROUND_UP)
        
        return {
            'principal': principal,
            'total_interest': total_interest,
            'total_repayment': total_repayment,
            'monthly_installment': monthly_installment,
            'months': months,
            'monthly_rate': monthly_rate,
        }
    
    @staticmethod
    def calculate_reducing_balance_interest(principal, monthly_rate, months):
        """
        Calculate reducing balance interest (EMI method)
        
        Args:
            principal: Loan principal
            monthly_rate: Monthly interest rate
            months: Loan duration in months
        
        Returns:
            dict: Interest details with amortization
        """
        principal = Decimal(str(principal))
        monthly_rate = Decimal(str(monthly_rate))
        
        # Calculate EMI
        emi = MoneyCalculator.calculate_emi(principal, monthly_rate, months)
        
        # Calculate total repayment and interest
        total_repayment = emi * months
        total_interest = total_repayment - principal
        
        return {
            'principal': principal,
            'emi': emi,
            'total_interest': MoneyCalculator.round_money(total_interest),
            'total_repayment': MoneyCalculator.round_money(total_repayment),
            'months': months,
            'monthly_rate': monthly_rate,
        }
    
    @staticmethod
    def generate_amortization_schedule(principal, monthly_rate, months, start_date):
        """
        Generate loan amortization schedule
        
        Args:
            principal: Loan principal
            monthly_rate: Monthly interest rate
            months: Loan duration
            start_date: Start date for schedule
        
        Returns:
            list: Schedule with payment breakdown
        """
        from datetime import timedelta
        from dateutil.relativedelta import relativedelta
        
        emi = MoneyCalculator.calculate_emi(principal, monthly_rate, months)
        balance = Decimal(str(principal))
        schedule = []
        
        for month in range(1, months + 1):
            # Interest for this month
            interest_payment = balance * Decimal(str(monthly_rate))
            interest_payment = MoneyCalculator.round_money(interest_payment)
            
            # Principal payment
            principal_payment = emi - interest_payment
            principal_payment = MoneyCalculator.round_money(principal_payment)
            
            # New balance
            balance -= principal_payment
            balance = MoneyCalculator.round_money(balance)
            
            # Ensure balance doesn't go negative
            if balance < 0:
                principal_payment += balance
                balance = Decimal('0.00')
            
            # Payment date
            payment_date = start_date + relativedelta(months=month)
            
            schedule.append({
                'installment_number': month,
                'due_date': payment_date,
                'emi': emi,
                'principal_payment': principal_payment,
                'interest_payment': interest_payment,
                'total_payment': emi,
                'balance_after': balance,
            })
        
        return schedule


# Quick access functions
def round_money(amount, places=None):
    """Shortcut for MoneyCalculator.round_money"""
    return MoneyCalculator.round_money(amount, places)


def calculate_percentage(amount, rate):
    """Shortcut for MoneyCalculator.calculate_percentage"""
    return MoneyCalculator.calculate_percentage(amount, rate)


def format_currency(amount):
    """Shortcut for MoneyCalculator.format_currency"""
    return MoneyCalculator.format_currency(amount)