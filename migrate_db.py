import sqlite3
from contextlib import closing

DATABASE_FILE = '/home/reigicad/KoukiKanshi/machine_monitoring.db'

def migrate_database():
    """Migrate the database schema to include duration columns."""
    try:
        with closing(sqlite3.connect(DATABASE_FILE)) as conn:
            cursor = conn.cursor()
            
            # Create a temporary table with the updated schema
            cursor.execute("""
                CREATE TABLE machine_runtime_new (
                    machine_id TEXT PRIMARY KEY,
                    current_status TEXT,
                    current_start_time TEXT,
                    off_duration REAL DEFAULT 0,
                    prep_duration REAL DEFAULT 0,
                    on_duration REAL DEFAULT 0,
                    unknown_duration REAL DEFAULT 0,
                    last_reset_time TEXT
                )
            """)
            
            # Copy data from old table to new table
            cursor.execute("""
                INSERT INTO machine_runtime_new (
                    machine_id, current_status, current_start_time,
                    off_duration, prep_duration, on_duration, unknown_duration
                )
                SELECT 
                    machine_id, current_status, current_start_time,
                    off_duration, prep_duration, on_duration, unknown_duration
                FROM machine_runtime
            """)
            
            # Drop old table and rename new table
            cursor.execute("DROP TABLE machine_runtime")
            cursor.execute("ALTER TABLE machine_runtime_new RENAME TO machine_runtime")
            
            # Make sure machine_events table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS machine_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    machine_id TEXT,
                    timestamp TEXT,
                    status TEXT
                )
            """)
            
            # Create index on timestamp for better query performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_machine_events_timestamp 
                ON machine_events(timestamp)
            """)
            
            conn.commit()
            print("Database migration completed successfully.")
    except Exception as e:
        print(f"Error during migration: {e}")
        raise

if __name__ == "__main__":
    migrate_database() 
