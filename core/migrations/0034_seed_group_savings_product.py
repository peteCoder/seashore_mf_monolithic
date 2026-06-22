from django.db import migrations


def create_group_savings_product(apps, schema_editor):
    SavingsProduct = apps.get_model('core', 'SavingsProduct')
    if not SavingsProduct.objects.filter(product_type='group_savings').exists():
        SavingsProduct.objects.create(
            name='Group Savings',
            code='GRP-SAV',
            description='Collective savings account for client groups. Tracks group-level deposits with per-member breakdown.',
            product_type='group_savings',
            interest_rate_annual='0.00',
            interest_calculation_method='simple',
            interest_payment_frequency='monthly',
            minimum_balance='0.00',
            minimum_opening_balance='0.00',
            min_deposit_amount='0.00',
            min_withdrawal_amount='0.00',
            monthly_maintenance_fee='0.00',
            withdrawal_fee='0.00',
            below_minimum_balance_fee='0.00',
            early_withdrawal_penalty_rate='0.00',
            is_active=True,
        )


def reverse_create_group_savings_product(apps, schema_editor):
    SavingsProduct = apps.get_model('core', 'SavingsProduct')
    SavingsProduct.objects.filter(code='GRP-SAV', product_type='group_savings').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_add_group_savings_product_type'),
    ]

    operations = [
        migrations.RunPython(
            create_group_savings_product,
            reverse_create_group_savings_product,
        ),
    ]
