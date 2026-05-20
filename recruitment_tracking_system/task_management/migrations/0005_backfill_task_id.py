from django.db import migrations


def backfill_task_id(apps, schema_editor):
    TaskRecord = apps.get_model("task_management", "TaskRecord")
    for row in TaskRecord.objects.filter(task_id__isnull=True) | TaskRecord.objects.filter(task_id=""):
        row.task_id = f"TASK{row.pk:05d}"
        row.save(update_fields=["task_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("task_management", "0004_taskrecord_job_id_taskrecord_task_id_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_task_id, migrations.RunPython.noop),
    ]
