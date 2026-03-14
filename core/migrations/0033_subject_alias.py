from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_lectureadjustment_swap_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectAlias",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alias", models.CharField(max_length=120)),
                ("canonical", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "module",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subject_aliases",
                        to="core.academicmodule",
                    ),
                ),
            ],
            options={
                "ordering": ["alias"],
                "unique_together": {("module", "alias")},
            },
        ),
    ]
