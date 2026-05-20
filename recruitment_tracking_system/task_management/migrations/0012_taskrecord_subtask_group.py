from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("task_management", "0011_taskrecord_parent_sequence"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrecord",
            name="subtask_group",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]

