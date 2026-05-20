from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("task_management", "0008_taskrecord_repeat_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="reminder_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="reminder_type",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="reminder_notify_mode",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="reminder_last_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

