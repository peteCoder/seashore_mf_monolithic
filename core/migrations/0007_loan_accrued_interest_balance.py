from decimal import Decimal
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_fix_group_membership_unique_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="accrued_interest_balance",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text=(
                    "Cumulative interest accrued via month-end journals but not yet "
                    "received in cash. Cleared against 1820 (not 4010) when repayment arrives."
                ),
                max_digits=15,
            ),
        ),
    ]
