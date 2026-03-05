from django.db import migrations, models
import django.db.models.deletion


def assign_default_module(apps, schema_editor):
    AcademicModule = apps.get_model("core", "AcademicModule")
    Student = apps.get_model("core", "Student")
    Subject = apps.get_model("core", "Subject")
    ResultUpload = apps.get_model("core", "ResultUpload")
    WeekLock = apps.get_model("core", "WeekLock")

    module, _ = AcademicModule.objects.get_or_create(
        name="FY2 - Batch 2026-29_Sem-1",
        defaults={
            "academic_batch": "2026-29",
            "year_level": "FY",
            "variant": "FY2-CE",
            "semester": "Sem-1",
            "is_active": True,
        },
    )

    Student.objects.filter(module__isnull=True).update(module=module)
    Subject.objects.filter(module__isnull=True).update(module=module)
    ResultUpload.objects.filter(module__isnull=True).update(module=module)
    WeekLock.objects.filter(module__isnull=True).update(module=module)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_student_mentor_mobile_flags"),
    ]

    operations = [
        migrations.CreateModel(
            name="AcademicModule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("academic_batch", models.CharField(max_length=20)),
                ("year_level", models.CharField(choices=[("FY", "FY"), ("SY", "SY"), ("TY", "TY"), ("LY", "LY")], default="FY", max_length=10)),
                ("variant", models.CharField(choices=[("FY1", "FY1"), ("FY2-CE", "FY2-CE"), ("FY2-Non CE", "FY2-Non CE"), ("FY3", "FY3"), ("FY4", "FY4"), ("FY5", "FY5"), ("SY1", "SY1"), ("SY2", "SY2"), ("TY1", "TY1"), ("TY2", "TY2"), ("LY1", "LY1"), ("LY2", "LY2")], default="FY2-CE", max_length=20)),
                ("semester", models.CharField(choices=[("Sem-1", "Sem-1"), ("Sem-2", "Sem-2")], default="Sem-1", max_length=10)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddField(
            model_name="resultupload",
            name="module",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="result_uploads", to="core.academicmodule"),
        ),
        migrations.AddField(
            model_name="student",
            name="module",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="students", to="core.academicmodule"),
        ),
        migrations.AddField(
            model_name="subject",
            name="module",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="subjects", to="core.academicmodule"),
        ),
        migrations.AddField(
            model_name="weeklock",
            name="module",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="week_locks", to="core.academicmodule"),
        ),
        migrations.AlterField(
            model_name="student",
            name="enrollment",
            field=models.CharField(max_length=20),
        ),
        migrations.AlterField(
            model_name="subject",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="weeklock",
            name="week_no",
            field=models.IntegerField(),
        ),
        migrations.RunPython(assign_default_module, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="resultupload",
            name="module",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="result_uploads", to="core.academicmodule"),
        ),
        migrations.AlterField(
            model_name="student",
            name="module",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="students", to="core.academicmodule"),
        ),
        migrations.AlterField(
            model_name="subject",
            name="module",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subjects", to="core.academicmodule"),
        ),
        migrations.AlterField(
            model_name="weeklock",
            name="module",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="week_locks", to="core.academicmodule"),
        ),
        migrations.AlterUniqueTogether(
            name="student",
            unique_together={("module", "enrollment")},
        ),
        migrations.AlterUniqueTogether(
            name="subject",
            unique_together={("module", "name")},
        ),
        migrations.AlterUniqueTogether(
            name="weeklock",
            unique_together={("module", "week_no")},
        ),
        migrations.AlterUniqueTogether(
            name="resultupload",
            unique_together={("module", "test_name", "subject")},
        ),
    ]

