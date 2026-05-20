from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("task_management", "0006_taskrecord_team"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="submission_status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="submitted_to",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="approved_by",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="rejection_reason",
            field=models.TextField(blank=True),
        ),
    ]

