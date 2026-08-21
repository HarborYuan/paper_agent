import pytest
from sqlmodel import SQLModel, create_engine, Session, StaticPool
from fastapi.testclient import TestClient
from src.main import app
from src.database import get_session

# Use an in-memory SQLite database for testing
# StaticPool is important for in-memory SQLite with multiple threads/connections 
# (though here mostly single thread)
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        TEST_DATABASE_URL, 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Redirect env-file writes to a temp file and restore the live settings object afterwards."""
    from src.config import settings as app_settings
    from src.services import env_file as env_file_mod
    path = tmp_path / ".env"
    path.write_text('# test env\nOPENROUTER_API_KEY="sk-or-test-secret-1234"\nLLM_MODEL_STAGE1="openai/gpt-4o-mini"\n')
    monkeypatch.setattr(env_file_mod, "resolve_env_file_path", lambda: path)
    snapshot = {k: getattr(app_settings, k) for k in type(app_settings).model_fields}
    yield path
    for k, v in snapshot.items():
        setattr(app_settings, k, v)
