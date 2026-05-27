import os
import sqlite3

# Load PostgreSQL connection settings from environment
DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db_connection():
    """
    Connects to Azure PostgreSQL if DATABASE_URL is active,
    otherwise falls back to a zero-cost local SQLite engine.
    """
    if DATABASE_URL:
        # Lazy load psycopg2 to avoid local requirements conflicts if not installed
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    else:
        DB_PATH = os.path.join(os.path.dirname(__file__), "writing_agent.db")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def execute_query(conn, query, params=(), fetch_all=False, fetch_one=False, commit=False):
    """
    Executes a query safely across both SQLite and PostgreSQL.
    Converts '?' placeholders to '%s' if running on Postgres.
    """
    is_sqlite = type(conn).__module__.startswith("sqlite3")
    
    if not is_sqlite:
        query = query.replace("?", "%s")
        
    cursor = conn.cursor()
    cursor.execute(query, params)
    
    if commit:
        conn.commit()
        
    if fetch_all:
        res = cursor.fetchall()
        cursor.close()
        return res
    elif fetch_one:
        res = cursor.fetchone()
        cursor.close()
        return res
        
    return cursor

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if we are running in Postgres or SQLite to adjust SQL syntax
    is_postgres = hasattr(cursor, 'cursor_factory') or DATABASE_URL != ""
    
    # 1. Books Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS books (
        id VARCHAR(255) PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        genre VARCHAR(100),
        target_chapters INTEGER DEFAULT 50,
        synopsis TEXT,
        style_guide TEXT,
        character_bible TEXT,
        status VARCHAR(50) DEFAULT 'planning',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # 2. Outlines Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS outlines (
        id VARCHAR(255) PRIMARY KEY,
        book_id VARCHAR(255) NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chapter_number INTEGER NOT NULL,
        title VARCHAR(255),
        goals TEXT,
        cliffhanger_focus TEXT,
        status VARCHAR(50) DEFAULT 'pending'
    );
    """)
    
    # 3. Chapters Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS chapters (
        id VARCHAR(255) PRIMARY KEY,
        book_id VARCHAR(255) NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chapter_number INTEGER NOT NULL,
        title VARCHAR(255),
        content TEXT,
        word_count INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialization check passed.")
