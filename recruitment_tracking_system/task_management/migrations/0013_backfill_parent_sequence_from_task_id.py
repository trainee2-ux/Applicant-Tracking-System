import re

from django.db import migrations


TASK_ID_RE = re.compile(r"^TASK(\d{1,10})$", re.IGNORECASE)


def backfill_parent_sequence_from_task_id(apps, schema_editor):
    TaskRecord = apps.get_model("task_management", "TaskRecord")
    qs = TaskRecord.objects.filter(parent_task__isnull=True).exclude(task_id__exact="")
    for row in qs.iterator():
        if row.parent_sequence is not None:
            continue
        raw = (row.task_id or "").strip()
        match = TASK_ID_RE.match(raw)
        if not match:
            continue
        row.parent_sequence = int(match.group(1))
        row.save(update_fields=["parent_sequence"])


class Migration(migrations.Migration):

    dependencies = [
        ("task_management", "0012_taskrecord_subtask_group"),
    ]

    operations = [
        migrations.RunPython(backfill_parent_sequence_from_task_id, migrations.RunPython.noop),
    ]

