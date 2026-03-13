from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_fix_emergency_frequency_and_daily_installments'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='client',
            name='core_client_level_54fc0e_idx',
        ),
        migrations.RemoveField(
            model_name='client',
            name='level',
        ),
    ]
