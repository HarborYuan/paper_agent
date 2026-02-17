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
            logger.info("Migration 001: Adding user_score column...")
            session.exec(text("ALTER TABLE paper ADD COLUMN user_score INTEGER"))
            session.commit()
        else:
            logger.info("Migration 001: user_score column already exists.")
            
    except Exception as e:
        logger.error(f"Migration 001 Failed: {e}")
        raise e

import json
from src.models import Paper

# Valid migrations list
MIGRATIONS = [
    migration_001_add_user_score,
]

def migration_002_clean_authors(session: Session):
    """
    Clean up author names: remove colons and trim whitespace.
    """
    logger.info("Migration 002: Cleaning author names...")
    
    # Select all papers
    papers = session.exec(select(Paper)).all()
    updated_count = 0
    
    for paper in papers:
        try:
            current_json = paper.authors
            if not current_json:
                continue
            
            authors = []
            cleaned_authors = []
            changed = False

            try:
                authors = json.loads(current_json)
            except json.JSONDecodeError:
                # Fallback for malformed JSON (e.g. unescaped quotes)
                # This logic mimics Paper.authors_list property
                logger.warning(f"Migration 002: Found malformed JSON for paper {paper.id}, applying fallback...")
                logger.debug(f"The malformed JSON is: {current_json}")
                parts = current_json.strip('[]').split('", "')
                authors = [p.strip('"') for p in parts if p.strip('"')]
                changed = True  # We will save it back as valid JSON
                logger.debug(f"The parsed authors are: {authors}")
            
            for author_name in authors:
                if not isinstance(author_name, str):
                    cleaned_authors.append(author_name)
                    continue

                # Apply cleaning logic
                cleaned_name = author_name.replace(":", "").strip()
                
                # Check if name was changed
                if cleaned_name != author_name:
                    changed = True
                
                # Filter out empty strings
                if cleaned_name:
                    cleaned_authors.append(cleaned_name)
                elif author_name: # Was not empty but became empty -> changed/removed
                    changed = True
            
            # Check length difference as well (items filtered out)
            if len(authors) != len(cleaned_authors):
                changed = True
                
            if changed:
                paper.authors = json.dumps(cleaned_authors)
                session.add(paper)
                updated_count += 1
                
        except Exception as e:
            logger.error(f"Migration 002 Error processing paper {paper.id}: {e}")
            
    session.commit()
    logger.info(f"Migration 002: Updated {updated_count} papers.")

# Valid migrations list
MIGRATIONS = [
    migration_001_add_user_score,
    migration_002_clean_authors,
]

def check_and_migrate():
    """
    Check current DB version and run missing migrations.
    """
    logger.info("Checking database migrations...")
    
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
            logger.error("Error checking version. Is DB initialized?")
            return

        current_version = version_record.version if version_record else 0
        target_version = len(MIGRATIONS)
        
        logger.info(f"Current DB Version: {current_version}. Target Version: {target_version}.")
        
        if current_version < target_version:
            for i in range(current_version, target_version):
                migration_func = MIGRATIONS[i]
                version_idx = i + 1
                logger.info(f"Running migration {version_idx}...")
                
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
                    logger.info(f"Migration {version_idx} completed successfully.")
                    
                except Exception as e:
                    logger.error(f"Migration {version_idx} failed: {e}")
                    # Stop if migration fails
                    break
        else:
            logger.info("Database is up to date.")
