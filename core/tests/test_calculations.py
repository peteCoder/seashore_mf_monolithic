"""
Financial Calculation Tests
============================

Tests for MoneyCalculator, InterestCalculator, and
generate_repayment_schedule utility.
"""

from decimal import Decimal
from datetime import date

from django.test import SimpleTestCase

from core.utils.money import MoneyCalculator, InterestCalculator


# =============================================================================
# MoneyCalculator Tests
# =============================================================================

class TestRoundMoney(SimpleTestCase):
    """MoneyCalculator.round_money"""

    def test_rounds_to_two_decimal_places_by_default(self):
        self.assertEqual(MoneyCalculator.round_money('1234.565'), Decimal('1234.57'))

    def test_rounds_none_to_zero(self):
        self.assertEqual(MoneyCalculator.round_money(None), Decimal('0.00'))

    def test_accepts_float(self):
        result = MoneyCalculator.round_money(100.1)
        self.assertIsInstance(result, Decimal)

    def test_accepts_integer(self):
        self.assertEqual(MoneyCalculator.round_money(100), Decimal('100.00'))

    def test_accepts_decimal(self):
        self.assertEqual(MoneyCalculator.round_money(Decimal('99.999')), Decimal('100.00'))


class TestCalculatePercentage(SimpleTestCase):
    """MoneyCalculator.calculate_percentage"""

    def test_basic_percentage(self):
        # 3.5% of 10,000 = 350
        result = MoneyCalculator.calculate_percentage(10000, Decimal('0.035'))
        self.assertEqual(result, Decimal('350.00'))

    def test_zero_amount_returns_zero(self):
        self.assertEqual(MoneyCalculator.calculate_percentage(0, Decimal('0.05')), Decimal('0.00'))

    def test_zero_rate_returns_zero(self):
        self.assertEqual(MoneyCalculator.calculate_percentage(10000, 0), Decimal('0.00'))

    def test_processing_fee_calculation(self):
        # 1% processing fee on ₦500,000 = ₦5,000
        result = MoneyCalculator.calculate_percentage(500000, Decimal('0.01'))
        self.assertEqual(result, Decimal('5000.00'))


class TestSafeDivide(SimpleTestCase):
    """MoneyCalculator.safe_divide"""

    def test_normal_division(self):
        result = MoneyCalculator.safe_divide(100, 4)
        self.assertEqual(result, Decimal('25.00'))

    def test_division_by_zero_returns_default(self):
        result = MoneyCalculator.safe_divide(100, 0)
        self.assertEqual(result, Decimal('0.00'))

    def test_division_by_zero_returns_custom_default(self):
        result = MoneyCalculator.safe_divide(100, 0, default=Decimal('99.99'))
        self.assertEqual(result, Decimal('99.99'))


class TestSumAmounts(SimpleTestCase):
    """MoneyCalculator.sum_amounts"""

    def test_sums_multiple_values(self):
        result = MoneyCalculator.sum_amounts(100, 200, 300)
        self.assertEqual(result, Decimal('600.00'))

    def test_ignores_none_values(self):
        result = MoneyCalculator.sum_amounts(100, None, 200)
        self.assertEqual(result, Decimal('300.00'))

    def test_empty_returns_zero(self):
        self.assertEqual(MoneyCalculator.sum_amounts(), Decimal('0.00'))


class TestCalculateInterest(SimpleTestCase):
    """MoneyCalculator.calculate_interest"""

    def test_flat_rate_interest(self):
        # ₦100,000 at 3% per month for 6 months = ₦18,000
        result = MoneyCalculator.calculate_interest(100000, Decimal('0.03'), 6, method='flat')
        self.assertEqual(result, Decimal('18000.00'))

    def test_reducing_balance_interest_less_than_flat(self):
        # Reducing balance interest is always lower than flat for same principal/rate/term
        flat = MoneyCalculator.calculate_interest(100000, Decimal('0.03'), 12, method='flat')
        reducing = MoneyCalculator.calculate_interest(100000, Decimal('0.03'), 12, method='reducing_balance')
        self.assertLess(reducing, flat)

    def test_invalid_method_raises(self):
        with self.assertRaises(ValueError):
            MoneyCalculator.calculate_interest(100000, Decimal('0.03'), 6, method='unknown')


class TestCalculateEMI(SimpleTestCase):
    """MoneyCalculator.calculate_emi"""

    def test_zero_rate_divides_principal_equally(self):
        # Zero interest: ₦120,000 over 12 months = ₦10,000/month
        result = MoneyCalculator.calculate_emi(120000, 0, 12)
        self.assertEqual(result, Decimal('10000.00'))

    def test_emi_multiplied_by_periods_covers_principal(self):
        # EMI × periods should be ≥ principal
        emi = MoneyCalculator.calculate_emi(500000, Decimal('0.03'), 18)
        total = emi * 18
        self.assertGreaterEqual(total, Decimal('500000.00'))

    def test_emi_is_consistent(self):
        # Same inputs should produce same result
        emi1 = MoneyCalculator.calculate_emi(200000, Decimal('0.025'), 12)
        emi2 = MoneyCalculator.calculate_emi(200000, Decimal('0.025'), 12)
        self.assertEqual(emi1, emi2)


class TestValidateAmount(SimpleTestCase):
    """MoneyCalculator.validate_amount"""

    def test_valid_amount(self):
        is_valid, msg = MoneyCalculator.validate_amount(1000)
        self.assertTrue(is_valid)
        self.assertEqual(msg, '')

    def test_negative_amount_is_invalid(self):
        is_valid, msg = MoneyCalculator.validate_amount(-1)
        self.assertFalse(is_valid)
        self.assertIn('negative', msg)

    def test_below_minimum_is_invalid(self):
        is_valid, msg = MoneyCalculator.validate_amount(500, min_amount=1000)
        self.assertFalse(is_valid)

    def test_above_maximum_is_invalid(self):
        is_valid, msg = MoneyCalculator.validate_amount(2000, max_amount=1000)
        self.assertFalse(is_valid)

    def test_within_range_is_valid(self):
        is_valid, _ = MoneyCalculator.validate_amount(1500, min_amount=1000, max_amount=2000)
        self.assertTrue(is_valid)

    def test_invalid_format_is_invalid(self):
        is_valid, _ = MoneyCalculator.validate_amount('not-a-number')
        self.assertFalse(is_valid)


class TestFormatCurrency(SimpleTestCase):
    """MoneyCalculator.format_currency"""

    def test_formats_with_naira_symbol(self):
        result = MoneyCalculator.format_currency(1234567.89)
        self.assertIn('₦', result)
        self.assertIn('1,234,567.89', result)

    def test_formats_zero(self):
        result = MoneyCalculator.format_currency(0)
        self.assertEqual(result, '₦0.00')


# =============================================================================
# InterestCalculator Tests
# =============================================================================

class TestFlatInterest(SimpleTestCase):
    """InterestCalculator.calculate_flat_interest"""

    def test_basic_flat_calculation(self):
        result = InterestCalculator.calculate_flat_interest(
            principal=100000,
            monthly_rate=Decimal('0.03'),
            months=6,
        )
        self.assertEqual(result['principal'], Decimal('100000'))
        self.assertEqual(result['total_interest'], Decimal('18000.00'))
        self.assertEqual(result['total_repayment'], Decimal('118000.00'))
        self.assertEqual(result['months'], 6)

    def test_installment_covers_total(self):
        result = InterestCalculator.calculate_flat_interest(
            principal=200000,
            monthly_rate=Decimal('0.025'),
            months=12,
        )
        # installment × months should be >= total_repayment (rounding up)
        self.assertGreaterEqual(
            result['monthly_installment'] * 12,
            result['total_repayment'],
        )


class TestReducingBalanceInterest(SimpleTestCase):
    """InterestCalculator.calculate_reducing_balance_interest"""

    def test_basic_reducing_calculation(self):
        result = InterestCalculator.calculate_reducing_balance_interest(
            principal=100000,
            monthly_rate=Decimal('0.03'),
            months=12,
        )
        self.assertIn('emi', result)
        self.assertIn('total_interest', result)
        self.assertGreater(result['emi'], 0)
        self.assertGreater(result['total_repayment'], result['principal'])

    def test_reducing_interest_less_than_flat_same_params(self):
        flat = InterestCalculator.calculate_flat_interest(
            principal=500000, monthly_rate=Decimal('0.03'), months=12
        )
        reducing = InterestCalculator.calculate_reducing_balance_interest(
            principal=500000, monthly_rate=Decimal('0.03'), months=12
        )
        self.assertLess(reducing['total_interest'], flat['total_interest'])


class TestAmortizationSchedule(SimpleTestCase):
    """InterestCalculator.generate_amortization_schedule"""

    def setUp(self):
        self.schedule = InterestCalculator.generate_amortization_schedule(
            principal=120000,
            monthly_rate=Decimal('0.03'),
            months=12,
            start_date=date(2025, 1, 1),
        )

    def test_schedule_has_correct_length(self):
        self.assertEqual(len(self.schedule), 12)

    def test_first_installment_number(self):
        self.assertEqual(self.schedule[0]['installment_number'], 1)

    def test_last_installment_number(self):
        self.assertEqual(self.schedule[-1]['installment_number'], 12)

    def test_balance_decreases_over_time(self):
        balances = [row['balance_after'] for row in self.schedule]
        for i in range(1, len(balances)):
            self.assertLessEqual(balances[i], balances[i - 1])

    def test_final_balance_is_near_zero(self):
        final_balance = self.schedule[-1]['balance_after']
        # Should be zero or very close to zero (within ₦1 rounding)
        self.assertLessEqual(abs(final_balance), Decimal('1.00'))

    def test_each_row_has_required_keys(self):
        required_keys = {
            'installment_number', 'due_date', 'emi',
            'principal_payment', 'interest_payment', 'balance_after',
        }
        for row in self.schedule:
            self.assertTrue(required_keys.issubset(row.keys()))
