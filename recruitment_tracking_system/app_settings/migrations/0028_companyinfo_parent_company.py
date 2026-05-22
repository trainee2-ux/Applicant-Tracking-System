def _ensure_parent_company_column(apps, schema_editor):
    """
    Existing installs may already have the column (manual DB change or partial migration).
    Make this migration idempotent by skipping if the column already exists.
    """
    table = "app_settings_companyinfo"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({schema_editor.quote_name(table)})")
        existing_cols = {row[1] for row in cursor.fetchall()}

    if "parent_company_id" in existing_cols:
        return

    # Add a nullable integer column. (SQLite cannot easily add FK constraints
    # with ALTER TABLE; Django will treat this as the FK column at runtime.)
    schema_editor.execute(
        f"ALTER TABLE {schema_editor.quote_name(table)} "
        f"ADD COLUMN {schema_editor.quote_name('parent_company_id')} integer NULL"
    )
    schema_editor.execute(
        f"CREATE INDEX IF NOT EXISTS {schema_editor.quote_name('app_settings_companyinfo_parent_company_id_idx')} "
        f"ON {schema_editor.quote_name(table)} ({schema_editor.quote_name('parent_company_id')})"
    )


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
