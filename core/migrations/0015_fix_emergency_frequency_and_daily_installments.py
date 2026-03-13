"""
0015 — Fix Emergency loan product frequency (weekly → monthly)
       and recalculate installment_amount / number_of_installments
       for all existing daily-frequency loans using the corrected
       standard of 20 working days per month.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def fix_emergency_products(apps, schema_editor):
    """Change any Emergency loan product that has weekly frequency to monthly."""
    LoanProduct = apps.get_model('core', 'LoanProduct')
    LoanProduct.objects.filter(
        loan_type='emergency',
        repayment_frequency='weekly',
    ).update(repayment_frequency='monthly')


def recalculate_daily_loans(apps, schema_editor):
    """
    Recalculate number_of_installments and installment_amount for all
    daily-frequency loans using duration_months × 20 (standard working days).
    """
    Loan = apps.get_model('core', 'Loan')

    daily_loans = Loan.objects.filter(
        loan_product__repayment_frequency='daily',
    ).select_related('loan_product')

    for loan in daily_loans:
        if not loan.duration_months or loan.duration_months <= 0:
            continue
        n = loan.duration_months * 20
        if n > 0 and loan.total_repayment:
            installment = (
                Decimal(str(loan.total_repayment)) / n
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            loan.number_of_installments = n
            loan.installment_amount = installment
            loan.save(update_fields=['number_of_installments', 'installment_amount'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_alter_loanproduct_repayment_frequency_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_emergency_products,  migrations.RunPython.noop),
        migrations.RunPython(recalculate_daily_loans, migrations.RunPython.noop),
    ]
