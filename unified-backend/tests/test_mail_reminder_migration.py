# test_mail_reminder_migration.py
#
# Migration checks that need NO database connection: the revision graph,
# the generated upgrade/downgrade SQL (alembic offline mode) and parity
# between the SQLAlchemy model and the migration (R-037). The live
# upgrade -> downgrade -> upgrade round trip needs a disposable database
# and is run manually.

import io
import os
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]
INI = BACKEND / "alembic_ticketing" / "alembic.ini"
REVISION = "0c6db321ee79"
PARENT = "444b9869dc1b"


@pytest.fixture(scope="module")
def cfg():
    # env.py insists on this variable even in offline mode; a placeholder
    # is fine because offline mode never connects.
    os.environ.setdefault(
        "ALEMBIC_DATABASE_URL", "postgresql://u:p@localhost:5432/offline"
    )
    c = Config(str(INI))
    c.set_main_option("script_location", str(BACKEND / "alembic_ticketing"))
    return c


def _sql(cfg, fn, rng):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(cfg, rng, sql=True)
    return buf.getvalue()


def test_revision_chains_from_the_merged_head(cfg):
    script = ScriptDirectory.from_config(cfg)
    assert script.get_revision(REVISION).down_revision == PARENT
    # the revision id is unique across the whole chain
    ids = [r.revision for r in script.walk_revisions()]
    assert ids.count(REVISION) == 1


def test_graph_has_a_single_head_that_descends_from_the_reminders_revision(cfg):
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    ancestors = {r.revision for r in script.iterate_revisions(heads[0], "base")}
    assert REVISION in ancestors


def test_upgrade_sql_creates_table_constraints_and_indexes(cfg):
    sql = _sql(cfg, command.upgrade, f"{PARENT}:{REVISION}")

    assert "CREATE TABLE mail_reminders" in sql
    assert "REFERENCES users (user_id) ON DELETE CASCADE" in sql
    assert "REFERENCES interactions (interaction_id) ON DELETE CASCADE" in sql
    assert "remind_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert (
        "CREATE UNIQUE INDEX uq_mail_reminders_active_user_interaction ON "
        "mail_reminders (user_id, interaction_id) WHERE status = 'ACTIVE'"
    ) in sql
    assert (
        "CREATE INDEX idx_mail_reminders_active_remind_at ON mail_reminders "
        "(remind_at) WHERE status = 'ACTIVE'"
    ) in sql
    assert (
        "CREATE INDEX idx_mail_reminders_user_status ON mail_reminders "
        "(user_id, status)"
    ) in sql
    # purely additive: no ALTER / DROP of anything else
    assert not re.search(r"\b(ALTER|DROP)\b", sql)


def test_downgrade_sql_drops_everything_it_created(cfg):
    sql = _sql(cfg, command.downgrade, f"{REVISION}:{PARENT}")

    for index in (
        "idx_mail_reminders_user_status",
        "idx_mail_reminders_active_remind_at",
        "uq_mail_reminders_active_user_interaction",
    ):
        assert f"DROP INDEX {index}" in sql
    assert "DROP TABLE mail_reminders" in sql


def test_model_matches_migration(cfg):
    import app.ticketing.models  # noqa: F401
    from app.ticketing.models.mail_reminder import MailReminder

    table = MailReminder.__table__
    sql = _sql(cfg, command.upgrade, f"{PARENT}:{REVISION}")
    create = sql[sql.index("CREATE TABLE mail_reminders") : sql.index(");")]

    for col in table.columns:
        line = next(
            (l.strip() for l in create.splitlines() if l.strip().startswith(col.name + " ")),
            None,
        )
        assert line is not None, f"column {col.name} missing from migration"
        assert col.nullable == ("NOT NULL" not in line), col.name
    for idx in table.indexes:
        assert idx.name in sql
        assert idx.unique == (f"UNIQUE INDEX {idx.name}" in sql), idx.name


def test_table_is_registered_for_alembic_ownership():
    text = (BACKEND / "alembic_ticketing" / "env.py").read_text(encoding="utf8")
    assert '"mail_reminders"' in text
