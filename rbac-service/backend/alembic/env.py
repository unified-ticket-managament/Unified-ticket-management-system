from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models import Base

# Import models so Alembic registers them
from shared_models.models import User, Role, Category
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.audit_log import AuditLog
from app.models.permission_override import UserPermissionOverride

config = context.config
settings = get_settings()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ----------------------------------------------------
# Metadata
# ----------------------------------------------------

target_metadata = Base.metadata

# ----------------------------------------------------
# Ignore objects that belong to other services
# ----------------------------------------------------


def include_object(object, name, type_, reflected, compare_to):
    """
    Ignore Ticket Management tables when generating
    RBAC migrations.
    """

    ignored_tables = {
        "ticket_alembic_version",
        "tickets",
        "interactions",
        "attachments",
        "clients",
        "ticket_audit_logs",
        "mail_folders",
        "ticket_relations",
    }

    if type_ == "table" and name in ignored_tables:
        return False

    return True


# ----------------------------------------------------
# Convert async URL -> sync URL
# ----------------------------------------------------

sync_url = (
    settings.database_url
    .replace("+asyncpg", "")
    .replace("ssl=require", "sslmode=require")
)

config.set_main_option("sqlalchemy.url", sync_url)


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()