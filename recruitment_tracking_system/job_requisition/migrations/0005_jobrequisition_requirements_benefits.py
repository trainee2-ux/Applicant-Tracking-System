from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_requisition", "0004_jobrequisition_opening_status_and_closure_dates"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobrequisition",
            name="requirements",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="jobrequisition",
            name="benefits",
            field=models.TextField(blank=True),
        ),
    ]
