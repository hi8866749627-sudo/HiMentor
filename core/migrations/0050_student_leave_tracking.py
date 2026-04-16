from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0049_alter_examtimetableentry_mode_examsubjectevaluator"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="student",
            name="left_from_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="student",
            name="left_reason",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]

