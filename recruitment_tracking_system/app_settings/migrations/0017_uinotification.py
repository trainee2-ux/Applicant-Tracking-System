from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app_settings", "0016_alter_assessmentfield_field_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="UiNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recipient_name", models.CharField(max_length=150)),
                ("title", models.CharField(max_length=180)),
                ("message", models.TextField(blank=True)),
                ("link", models.CharField(blank=True, max_length=255)),
                ("source", models.CharField(blank=True, max_length=60)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
