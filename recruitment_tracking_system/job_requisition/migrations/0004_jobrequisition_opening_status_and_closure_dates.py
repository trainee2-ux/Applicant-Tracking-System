from django.db import migrations, models


def backfill_opening_status(apps, schema_editor):
    JobRequisition = apps.get_model("job_requisition", "JobRequisition")
    for job in JobRequisition.objects.all():
        status_value = (job.status or "").strip().lower()
        if status_value in {"open", "hold", "closed"}:
            job.job_opening_status = status_value.capitalize()
        elif not job.job_opening_status:
            job.job_opening_status = "Open"
        job.save(update_fields=["job_opening_status"])


class Migration(migrations.Migration):

    dependencies = [
        ("job_requisition", "0003_jobrequisition_public_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobrequisition",
            name="date_of_opening",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="jobrequisition",
            name="job_opening_status",
            field=models.CharField(default="Open", max_length=20),
        ),
        migrations.AddField(
            model_name="jobrequisition",
            name="target_closure_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_opening_status, migrations.RunPython.noop),
    ]
