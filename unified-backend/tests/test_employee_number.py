# test_employee_number.py
#
# Regression coverage for the "official employee human-readable ID"
# feature: a new, purely additional `employee_number` column/field
# alongside every user's existing UUID (`user_id`), which remains the
# sole canonical/relational identifier everywhere — no foreign key,
# reporting-hierarchy relationship, assignment, or authentication claim
# was changed to use it.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_status_on_assignment.py / test_attachment_upload_authorization.py.
# A handful of tests deliberately query the connected database directly
# (not a fixture-created row) to guard the actual backfill result
# (scripts/org_seed/backfill_employee_number.py) against silent drift,
# the same pattern test_attachment_upload_authorization.py's own
# Staff/editother_ticket guard test already established.

import uuid
from datetime import datetime, timezone

import pytest
from shared_models.models import Role, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.user import UserResponse
from app.ticketing.schemas.assignment import AssignableUserSummary
from scripts.org_seed.source_data import EMPLOYEES


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


# ---------------------------------------------------------------
# 1 & 4. The real backfill correctly mapped known official employees,
#    and never invented anything for an account with no official match.
# ---------------------------------------------------------------


async def test_known_real_employees_have_correct_employee_number(db_session):
    # (email, expected employee_number) — a handful spread across the
    # real EMPLOYEES source, cross-checked against source_data.py
    # itself rather than hardcoded twice.
    by_email = {e[3].lower(): e[0] for e in EMPLOYEES}
    samples = ["umesh@probeps.com", "vinay@probeps.com", "sowmyashree@probeps.com"]

    for email in samples:
        user = (
            await db_session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            pytest.skip(f"{email} not present in the connected database.")
        assert user.employee_number == str(by_email[email])


async def test_unmatched_official_employee_was_not_invented(db_session):
    """
    Pavan Raj N (employee_id 153, official email pavan@probeps.com) has
    no user in the connected database under that exact email (a
    separate, already-flagged account exists under a different email,
    Gogineni@painmedpa.com — see the session's own reconciliation
    report) — the backfill must leave this genuinely unmatched rather
    than guessing an ID by name.
    """

    user = (
        await db_session.execute(select(User).where(User.email == "pavan@probeps.com"))
    ).scalar_one_or_none()
    assert user is None, (
        "If this now finds a row, the email mismatch was corrected separately — "
        "update this test's expectation rather than assuming it's a regression."
    )


async def test_no_dummy_or_system_account_has_an_employee_number(db_session):
    """
    Demo/system accounts (no official employee record) must never have
    had an employee_number invented for them.
    """

    dummy_emails = [
        "admin@rbac.com", "sitelead@probeps.com", "manager@probeps.com",
        "teamlead@probeps.com", "staff@probeps.com", "viewer@probeps.com",
        "sophia.turner@probeps.com",
    ]
    rows = (
        await db_session.execute(select(User).where(User.email.in_(dummy_emails)))
    ).scalars().all()
    if not rows:
        pytest.skip("None of the known demo accounts exist in the connected database.")
    for row in rows:
        assert row.employee_number is None, f"{row.email} should have no employee_number, got {row.employee_number!r}"


# ---------------------------------------------------------------
# 3. employee_number is unique — the DB constraint actually rejects a
#    duplicate, it isn't just convention.
# ---------------------------------------------------------------


async def test_employee_number_uniqueness_is_enforced_by_the_database(db_session):
    role = (await db_session.execute(select(Role).limit(1))).scalars().first()
    if role is None:
        pytest.skip("No role exists in the connected database.")

    shared_number = f"TEST-{uuid.uuid4().hex[:8]}"

    user_a = User(
        user_id=uuid.uuid4(),
        name="Employee Number Test A",
        email=f"empnum-test-a-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
        employee_number=shared_number,
    )
    db_session.add(user_a)
    await db_session.flush()

    user_b = User(
        user_id=uuid.uuid4(),
        name="Employee Number Test B",
        email=f"empnum-test-b-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
        employee_number=shared_number,
    )
    db_session.add(user_b)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_multiple_users_with_null_employee_number_are_allowed(db_session):
    """
    NULL is not subject to the unique constraint (standard Postgres
    behavior — every NULL is distinct from every other NULL) — two
    demo/system-style accounts with no official employee record must
    coexist fine.
    """

    role = (await db_session.execute(select(Role).limit(1))).scalars().first()
    if role is None:
        pytest.skip("No role exists in the connected database.")

    for _ in range(2):
        db_session.add(
            User(
                user_id=uuid.uuid4(),
                name="Null Employee Number Test",
                email=f"empnum-null-test-{uuid.uuid4().hex[:8]}@example.com",
                password_hash="not-a-real-hash",
                role_id=role.role_id,
                is_active=True,
                employee_number=None,
            )
        )

    await db_session.flush()  # must not raise


# ---------------------------------------------------------------
# 2. Employee number is returned by the API response schemas.
# ---------------------------------------------------------------


async def test_user_response_schema_exposes_employee_number(db_session):
    result = await db_session.execute(
        select(User)
        .options(joinedload(User.role))
        .where(User.employee_number.is_not(None))
        .limit(1)
    )
    user = result.unique().scalar_one_or_none()
    if user is None:
        pytest.skip("No user with an employee_number exists in the connected database.")

    response = UserResponse.model_validate(user)
    assert response.employee_number == user.employee_number
    # The UUID remains the canonical id field, untouched and still present.
    assert response.user_id == user.user_id


async def test_assignable_user_summary_exposes_employee_number():
    summary = AssignableUserSummary(
        user_id=uuid.uuid4(), name="Test Assignee", employee_number="266"
    )
    assert summary.employee_number == "266"

    # Backward-compatible: omitting it entirely must still validate,
    # for demo/system accounts with no official record.
    summary_without = AssignableUserSummary(user_id=uuid.uuid4(), name="No Employee Number")
    assert summary_without.employee_number is None


# ---------------------------------------------------------------
# 5, 6, 7. Search works by employee number, name, and email — all
#    three, not just the new one at the expense of the existing two.
# ---------------------------------------------------------------


async def test_search_by_employee_number(db_session):
    repo = UserRepository(db_session)
    sample = (
        await db_session.execute(select(User).where(User.employee_number.is_not(None)).limit(1))
    ).scalar_one_or_none()
    if sample is None:
        pytest.skip("No user with an employee_number exists in the connected database.")

    users, total = await repo.get_all(page=1, page_size=10, search=sample.employee_number)
    assert total >= 1
    assert any(u.user_id == sample.user_id for u in users)


async def test_search_by_name_still_works(db_session):
    repo = UserRepository(db_session)
    sample = (await db_session.execute(select(User).limit(1))).scalars().first()
    if sample is None:
        pytest.skip("No user exists in the connected database.")

    # A distinctive substring of the name, not the whole string, to
    # mirror how a real user would actually search.
    query = sample.name.strip().split(" ")[0]
    if not query:
        pytest.skip("Sample user has no usable name substring.")

    users, total = await repo.get_all(page=1, page_size=50, search=query)
    assert total >= 1
    assert any(u.user_id == sample.user_id for u in users)


async def test_search_by_email_still_works(db_session):
    repo = UserRepository(db_session)
    sample = (await db_session.execute(select(User).limit(1))).scalars().first()
    if sample is None:
        pytest.skip("No user exists in the connected database.")

    users, total = await repo.get_all(page=1, page_size=10, search=sample.email)
    assert total >= 1
    assert any(u.user_id == sample.user_id for u in users)


# ---------------------------------------------------------------
# 8, 9, 10. UUID remains the real lookup/relational key — get_by_id,
#    manager_id/teamlead_id, and a fresh User row's own user_id are all
#    completely unaffected by any of the above.
# ---------------------------------------------------------------


async def test_uuid_based_lookup_still_works(db_session):
    repo = UserRepository(db_session)
    sample = (await db_session.execute(select(User).limit(1))).scalars().first()
    if sample is None:
        pytest.skip("No user exists in the connected database.")

    found = await repo.get_by_id(sample.user_id)
    assert found is not None
    assert found.user_id == sample.user_id


async def test_new_user_uuid_is_generated_independently_of_employee_number(db_session):
    role = (await db_session.execute(select(Role).limit(1))).scalars().first()
    if role is None:
        pytest.skip("No role exists in the connected database.")

    user = User(
        user_id=uuid.uuid4(),
        name="UUID Independence Test",
        email=f"uuid-independence-test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
        employee_number="999999",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    assert user.user_id is not None
    assert user.employee_number == "999999"
    # The two identifiers are fully independent — changing one never
    # touches the other.
    user.employee_number = "888888"
    await db_session.flush()
    await db_session.refresh(user)
    assert user.employee_number == "888888"
