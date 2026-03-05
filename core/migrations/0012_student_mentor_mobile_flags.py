from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_alter_studentresult_marks_current"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="father_mobile_updated_by_mentor",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="student",
            name="student_mobile_updated_by_mentor",
            field=models.BooleanField(default=False),
        ),
    ]

