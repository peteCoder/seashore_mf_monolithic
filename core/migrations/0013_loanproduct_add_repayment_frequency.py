from django.db import migrations, models


FREQ_MAP = {
    'thrift':         'daily',
    'group':          'weekly',
    'emergency':      'weekly',
    'med':            'monthly',
    'business':       'monthly',
    'salary_advance': 'monthly',
    'asset_finance':  'monthly',
    'agricultural':   'monthly',
}


def populate_repayment_frequency(apps, schema_editor):
    """Seed repayment_frequency from the existing loan_type on each product."""
    LoanProduct = apps.get_model('core', 'LoanProduct')
    for product in LoanProduct.objects.all():
        product.repayment_frequency = FREQ_MAP.get(product.loan_type, 'monthly')
        product.save(update_fields=['repayment_frequency'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanproduct',
            name='repayment_frequency',
            field=models.CharField(
                choices=[
                    ('daily',       'Daily'),
                    ('weekly',      'Weekly'),
                    ('fortnightly', 'Fortnightly'),
                    ('monthly',     'Monthly'),
                    ('yearly',      'Yearly'),
                ],
                default='monthly',
                max_length=20,
                help_text='How often borrowers make installment payments',
            ),
        ),
        migrations.RunPython(populate_repayment_frequency, migrations.RunPython.noop),
    ]
