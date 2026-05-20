from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("task_management", "0007_taskrecord_manager_submission_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="repeat_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="repeat_end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="repeat_type",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]

