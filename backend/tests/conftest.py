"""Shared test fixtures for backend tests."""

import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set test env vars before importing app modules
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["DISABLE_AUTH"] = "false"
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
os.environ["CLERK_SECRET_KEY"] = ""
os.environ["CLERK_PUBLISHABLE_KEY"] = ""

from app.core.database import Base
# Importing the `models` package eagerly registers every table on the shared
# Base.metadata so create_all() builds the full schema (including newer tables
# like app_settings that some tests use without their dedicated model imports).
import app.models  # noqa: F401
from app.models.user import User
from app.models.warehouse import WarehouseConnection
from app.models.conversation import Conversation, ConversationMessage
from app.models.local_duckdb import LocalDuckDB
from app.core.security import encrypt_credentials


@pytest.fixture()
def db_engine():
    # StaticPool keeps the same in-memory connection across all queries for
    # this test. Without it each new connection gets a fresh empty DB and
    # multi-roundtrip tests randomly see "no such table" for whichever
    # connection wasn't the one create_all ran on.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def test_user(db_session):
    user = User(
        id="test-user-1",
        email="test@example.com",
        name="Test User",
        plan="pro",
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_user(db_session):
    user = User(
        id="admin-user-1",
        email="admin@example.com",
        name="Admin User",
        plan="pro",
        is_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def test_warehouse(db_session, test_user):
    creds = encrypt_credentials({"host": "localhost", "port": "5432", "database": "testdb", "username": "user", "password": "pass"})
    warehouse = WarehouseConnection(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        warehouse_type="postgresql",
        name="Test Warehouse",
        credentials_encrypted=creds,
        connection_status="connected",
        last_tested_at=datetime.utcnow(),
    )
    db_session.add(warehouse)
    db_session.commit()
    db_session.refresh(warehouse)
    return warehouse


@pytest.fixture()
def test_local_duckdb(db_session, test_user):
    local_db = LocalDuckDB(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        file_path="/tmp/test-not-real.duckdb",
    )
    db_session.add(local_db)
    db_session.commit()
    db_session.refresh(local_db)
    return local_db


@pytest.fixture()
def test_conversation(db_session, test_user, test_warehouse):
    conv = Conversation(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        warehouse_connection_id=test_warehouse.id,
        title="Test Conversation",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    return conv


@pytest.fixture()
def test_message(db_session, test_conversation):
    msg = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=test_conversation.id,
        role="user",
        content="Test message",
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


@pytest.fixture()
def mock_executor():
    """A mock WarehouseExecutor for testing."""
    executor = MagicMock()
    executor.execute_sql = MagicMock(return_value="| col1 | col2 |\n| val1 | val2 |")
    executor.list_datasets = MagicMock(return_value="| dataset |\n| ds1 |")
    executor.list_tables = MagicMock(return_value="| table |\n| t1 |")
    executor.get_table_schema = MagicMock(return_value="| column | type |\n| id | int |")
    executor.connect = MagicMock(return_value=None)
    executor.get_schema_summary = MagicMock(return_value="db.public.users: id (int), name (text)")
    return executor


# FastAPI TestClient fixtures
@pytest.fixture()
def app_with_db(db_engine):
    """Create FastAPI app with test database override."""
    from app.core.database import get_db
    from app.main import app

    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield app, TestSession
    app.dependency_overrides.clear()


@pytest.fixture()
def client(app_with_db):
    """TestClient with no auth (for public endpoints)."""
    from httpx import ASGITransport, AsyncClient
    app, _ = app_with_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture()
def authed_client(app_with_db):
    """TestClient authenticated as an admin dev_user.

    Overrides `get_current_user` to bypass JWT validation regardless of the
    DISABLE_AUTH env var. Without this override, behavior shifted between
    local runs (where a developer's .env can flip DISABLE_AUTH on) and CI
    (where DISABLE_AUTH is intentionally left off so the auth-required
    suite is meaningful).
    """
    from httpx import ASGITransport, AsyncClient
    from app.core.dependencies import get_current_user
    app, TestSession = app_with_db

    # Create dev_user in the test DB so the override returns a real row
    session = TestSession()
    existing = session.query(User).filter(User.id == "dev_user").first()
    if not existing:
        user = User(
            id="dev_user",
            email="dev@datachat.local",
            name="Development User",
            plan="pro",
            is_admin=True,
        )
        session.add(user)
        session.commit()
    session.close()

    def _override_current_user():
        # Yield a fresh dev_user attached to the test session so admin checks
        # see is_admin=True without making a real JWT round-trip.
        s = TestSession()
        try:
            yield s.query(User).filter(User.id == "dev_user").first()
        finally:
            s.close()

    app.dependency_overrides[get_current_user] = _override_current_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
