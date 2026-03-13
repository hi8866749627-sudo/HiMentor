from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_alter_timetableentry_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lectureadjustment",
            name="adjustment_type",
            field=models.CharField(
                choices=[("proxy", "Proxy"), ("swap", "Swap")],
                default="proxy",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="lectureadjustment",
            name="swap_batch",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="lectureadjustment",
            name="swap_lecture_no",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lectureadjustment",
            name="swap_pair_key",
            field=models.CharField(blank=True, db_index=True, max_length=40),
        ),
        migrations.AddField(
            model_name="lectureadjustment",
            name="swap_time_slot",
            field=models.CharField(blank=True, max_length=60),
        ),
    ]
