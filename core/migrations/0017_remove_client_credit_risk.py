from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_remove_client_level'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='client',
            name='client_credit_score_range',
        ),
        migrations.RemoveField(
            model_name='client',
            name='credit_score',
        ),
        migrations.RemoveField(
            model_name='client',
            name='risk_rating',
        ),
    ]
