from src.database import init_db
import time

if __name__ == "__main__":
    print("Initializing database...")
    # diverse retry logic
    max_retries = 5
    for i in range(max_retries):
        try:
            init_db()
            print("Database initialized successfully!")
            break
        except Exception as e:
            print(f"Failed to initialize database (attempt {i+1}/{max_retries}): {e}")
            time.sleep(2)
