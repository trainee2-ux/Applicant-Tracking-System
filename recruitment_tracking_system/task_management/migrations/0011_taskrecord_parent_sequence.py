from django.db import migrations, models


def backfill_parent_sequence(apps, schema_editor):
    TaskRecord = apps.get_model("task_management", "TaskRecord")
    parents = TaskRecord.objects.filter(parent_task__isnull=True).order_by("created_at", "id")
    seq = 1
    for row in parents:
        if row.parent_sequence is None:
            row.parent_sequence = seq
            row.save(update_fields=["parent_sequence"])
        seq += 1


class Migration(migrations.Migration):

    dependencies = [
        ("task_management", "0010_taskrecord_parent_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="parent_sequence",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.RunPython(backfill_parent_sequence, migrations.RunPython.noop),
    ]

