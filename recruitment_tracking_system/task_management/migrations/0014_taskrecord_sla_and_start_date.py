from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("task_management", "0013_backfill_parent_sequence_from_task_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="sla_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="sla_first_response_hours",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="sla_resolution_hours",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="sla_first_response_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecord",
            name="sla_resolution_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

