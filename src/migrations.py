from sqlmodel import Session, select
from sqlalchemy import text
from src.database import engine
from src.models import SchemaVersion
from src.logger import logger
import logging
from datetime import datetime

logger = logging.getLogger("migration")

def migration_001_add_user_score(session: Session):
    """
    Add user_score column to paper table if not exists.
    """
    # Check if column exists
    # SQLite specific check
    try:
        result = session.exec(text("PRAGMA table_info(paper)")).all()
        columns = [row[1] for row in result]
        
        if "user_score" not in columns:
            print("Migration 001: Adding user_score column...")
            session.exec(text("ALTER TABLE paper ADD COLUMN user_score INTEGER"))
            session.commit()
        else:
            print("Migration 001: user_score column already exists.")
            
    except Exception as e:
        print(f"Migration 001 Failed: {e}")
        raise e

# Valid migrations list
MIGRATIONS = [
    migration_001_add_user_score,
]

def check_and_migrate():
    """
    Check current DB version and run missing migrations.
    """
    print("Checking database migrations...")
    
    # Ensure SchemaVersion table exists
    # This is safe because init_db calls create_all before this? 
    # Or we should call create_all here for SchemaVersion specifically?
    # init_db() in database.py calls create_all, so SchemaVersion table should exist 
    # if it was added to models.py and imported.
    
    with Session(engine) as session:
        # Get current version
        # If table is empty, version is 0
        statement = select(SchemaVersion).limit(1)
        try:
            version_record = session.exec(statement).first()
        except Exception:
            # Table might not exist yet if init_db failed or wasn't called?
            # But init_db should be called first.
            print("Error checking version. Is DB initialized?")
            return

        current_version = version_record.version if version_record else 0
        target_version = len(MIGRATIONS)
        
        print(f"Current DB Version: {current_version}. Target Version: {target_version}.")
        
        if current_version < target_version:
            for i in range(current_version, target_version):
                migration_func = MIGRATIONS[i]
                version_idx = i + 1
                print(f"Running migration {version_idx}...")
                
                try:
                    migration_func(session)
                    
                    # Update version
                    if not version_record:
                        version_record = SchemaVersion(version=version_idx)
                        session.add(version_record)
                    else:
                        version_record.version = version_idx
                        version_record.updated_at = datetime.now()
                        session.add(version_record)
                    
                    session.commit()
                    session.refresh(version_record)
                    print(f"Migration {version_idx} completed successfully.")
                    
                except Exception as e:
                    print(f"Migration {version_idx} failed: {e}")
                    # Stop if migration fails
                    break
        else:
            print("Database is up to date.")
