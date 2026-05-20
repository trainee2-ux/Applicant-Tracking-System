from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("candidate_management", "0008_candidatejobapplication_stage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="candidate",
            name="highest_education_level",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="candidate",
            name="degree_name",
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AlterField(
            model_name="candidate",
            name="institute_name",
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.AlterField(
            model_name="candidate",
            name="year_of_passing",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="candidate",
            name="percentage_cgpa",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]

