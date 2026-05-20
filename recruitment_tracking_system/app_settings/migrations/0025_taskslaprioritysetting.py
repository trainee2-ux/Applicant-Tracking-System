from django.db import migrations, models


def seed_sla_settings(apps, schema_editor):
    TaskSlaPrioritySetting = apps.get_model("app_settings", "TaskSlaPrioritySetting")
    defaults = {
        "urgent": (1, 4),
        "high": (2, 10),
        "medium": (6, 20),
        "low": (8, 30),
    }
    for priority, (resp, res) in defaults.items():
        TaskSlaPrioritySetting.objects.update_or_create(
            priority=priority,
            defaults={"first_response_hours": resp, "resolution_hours": res},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0024_globalauditlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskSlaPrioritySetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("priority", models.CharField(choices=[("urgent", "Urgent"), ("high", "High"), ("medium", "Medium"), ("low", "Low")], max_length=20, unique=True)),
                ("first_response_hours", models.PositiveSmallIntegerField(default=6)),
                ("resolution_hours", models.PositiveSmallIntegerField(default=20)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["priority"]},
        ),
        migrations.RunPython(seed_sla_settings, migrations.RunPython.noop),
    ]
