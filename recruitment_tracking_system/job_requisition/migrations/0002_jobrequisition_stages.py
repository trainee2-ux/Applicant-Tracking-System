# Generated manually for stages field
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("job_requisition", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobrequisition",
            name="stages",
            field=models.TextField(blank=True),
        ),
    ]
