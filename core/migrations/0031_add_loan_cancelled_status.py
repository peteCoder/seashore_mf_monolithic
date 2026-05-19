from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0030_add_public_holiday'),
    ]

    operations = [
        # Extend the status field max_length to accommodate 'cancelled'
        # (it's already max_length=20, 'cancelled' is 9 chars — no change needed)
        # Just update STATUS_CHOICES via AlterField to add 'cancelled'
        migrations.AlterField(
            model_name='loan',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending_fees',     'Pending Fee Payment'),
                    ('pending_approval', 'Pending Approval'),
                    ('approved',         'Approved'),
                    ('rejected',         'Rejected'),
                    ('cancelled',        'Cancelled'),
                    ('disbursed',        'Disbursed'),
                    ('active',           'Active'),
                    ('completed',        'Completed'),
                    ('overdue',          'Overdue'),
                    ('written_off',      'Written Off'),
                ],
                db_index=True,
                default='pending_fees',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='loan',
            name='cancelled_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loans_cancelled',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='loan',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loan',
            name='cancellation_reason',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
    ]
