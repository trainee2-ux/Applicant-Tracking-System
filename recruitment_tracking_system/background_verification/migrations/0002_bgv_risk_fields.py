from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("background_verification", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="backgroundverificationrecord",
            name="risk_score",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backgroundverificationrecord",
            name="risk_level",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="backgroundverificationrecord",
            name="risk_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="backgroundverificationrecord",
            name="ocr_summary",
            field=models.TextField(blank=True),
        ),
    ]
