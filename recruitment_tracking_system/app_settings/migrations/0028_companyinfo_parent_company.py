def _ensure_parent_company_column(apps, schema_editor):
    """
    Existing installs may already have the column (manual DB change or partial migration).
    Make this migration idempotent by skipping if the column already exists.
    """
    table = "app_settings_companyinfo"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cursor.fetchall()}

    if "parent_company_id" in existing_cols:
        return

    CompanyInfo = apps.get_model("app_settings", "CompanyInfo")
    field = CompanyInfo._meta.get_field("parent_company")
    schema_editor.add_field(CompanyInfo, field)


from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("app_settings", "0027_assessmentfield_scoring"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_ensure_parent_company_column, reverse_code=migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="companyinfo",
                    name="parent_company",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sub_companies",
                        to="app_settings.companyinfo",
                    ),
                ),
            ],
        )
    ]
