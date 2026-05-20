from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("task_management", "0009_taskrecord_reminder_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="parent_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="subtasks",
                to="task_management.taskrecord",
            ),
        ),
    ]

