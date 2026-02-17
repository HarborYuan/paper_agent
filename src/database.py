from sqlmodel import SQLModel, create_engine, Session
from src.config import settings

engine = create_engine(settings.DATABASE_URL)

def get_session():
    with Session(engine) as session:
        yield session

DEV_COMMIT=True

def init_db():
    # Helper to check if DB needs migration
    # Import models to register them with SQLModel.metadata
    import src.models 
    SQLModel.metadata.create_all(engine)
    # Run migrations; delay import to avoid circular import
    from src.migrations import check_and_migrate
    check_and_migrate(dev_commit=DEV_COMMIT)
