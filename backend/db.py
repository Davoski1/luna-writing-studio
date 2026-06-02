import os
import sqlite3

# Try to load environment variables from backend/.env manually to ensure resiliency
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

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
        plot_bible TEXT,
        structural_outline TEXT,
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
    
    # 4. Reference Pages Table for Screenshot OCR
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS reference_pages (
        id VARCHAR(255) PRIMARY KEY,
        book_id VARCHAR(255) NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        page_number INTEGER NOT NULL,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # Dynamic column addition for backward compatibility
    # PostgreSQL invalidates active transactions upon statement failure.
    # We must roll back aborted transactions and re-initialize cursors cleanly.
    
    # 1. Check & Add plot_bible
    try:
        cursor.execute("SELECT plot_bible FROM books LIMIT 1;")
    except Exception:
        conn.rollback()
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE books ADD COLUMN plot_bible TEXT;")
            conn.commit()
            cursor = conn.cursor()
        except Exception:
            conn.rollback()
            cursor = conn.cursor()
            
    # 2. Check & Add style_example_chapter
    try:
        cursor.execute("SELECT style_example_chapter FROM books LIMIT 1;")
    except Exception:
        conn.rollback()
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE books ADD COLUMN style_example_chapter TEXT;")
            conn.commit()
            cursor = conn.cursor()
        except Exception:
            conn.rollback()
            cursor = conn.cursor()

    # 3. Check & Add structural_outline
    try:
        cursor.execute("SELECT structural_outline FROM books LIMIT 1;")
    except Exception:
        conn.rollback()
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE books ADD COLUMN structural_outline TEXT;")
            conn.commit()
            cursor = conn.cursor()
        except Exception:
            conn.rollback()
            cursor = conn.cursor()
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialization check passed.")
