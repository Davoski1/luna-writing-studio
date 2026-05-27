import os
import sys
import uuid
import json
import threading

# Ensure backend directory is in the Python search path for module resolution
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
import prompts
import compiler
import storage

app = FastAPI(title="Writing Agent API")

# Configure dynamic CORS origins to support Azure Static Web Apps and local dashboard dev servers
ALLOWED_ORIGINS = [
    os.getenv("FRONTEND_URL", "http://localhost:5000"),
    "https://*.azurestaticapps.net",
    "*" # Fallback wildcard for local testing
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """
    Serves the visual single-page dashboard directly on the root path.
    """
    frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Luna AI Writing Studio - Frontend file index.html not found!</h1>"

# Ensure DB is initialized before startup
@app.on_event("startup")
def startup():
    db.init_db()

class BookCreateRequest(BaseModel):
    reference_text: str
    target_chapters: int = 5

def background_writing_pipeline(book_id: str, reference_text: str, target_chapters: int):
    """
    Background worker that runs the Stage 1 & Stage 2 pipelines:
    1. Deconstruct and Adapt reference text to unique title, synopsis, character_bible
    2. Generate structured multi-chapter outline
    """
    try:
        # Stage 1: Deconstruction
        print(f"[Worker] Starting deconstruction for book {book_id}...")
        proposal = prompts.deconstruct_and_adapt(reference_text)
        
        title = proposal.get("title", "The Alpha's Fated Shadow")
        synopsis = proposal.get("synopsis", "A fated werewolf romance...")
        genre = proposal.get("genre", "Werewolf Romance")
        style_guide = proposal.get("style_guide", "Short dramatic paragraphs.")
        character_bible = json.dumps(proposal.get("character_bible", {}))

        # Save proposal back to books table
        conn = db.get_db_connection()
        db.execute_query(conn, """
            UPDATE books 
            SET title = ?, synopsis = ?, genre = ?, style_guide = ?, character_bible = ?, status = 'planning'
            WHERE id = ?
        """, (title, synopsis, genre, style_guide, character_bible, book_id), commit=True)
        
        # Stage 2: Generate Outline
        print(f"[Worker] Designing outline for book {book_id}...")
        outline = prompts.generate_outline(title, synopsis, proposal.get("character_bible", {}), target_chapters)
        
        for ch in outline:
            db.execute_query(conn, """
                INSERT INTO outlines (id, book_id, chapter_number, title, goals, cliffhanger_focus, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """, (
                str(uuid.uuid4()),
                book_id,
                ch.get("chapter_number"),
                ch.get("title"),
                ch.get("goals"),
                ch.get("cliffhanger_focus")
            ))
        conn.commit()
        
        # Update status to ready for drafting
        db.execute_query(conn, "UPDATE books SET status = 'drafting' WHERE id = ?", (book_id,), commit=True)
        conn.close()
        print(f"[Worker] Pipeline initialization completed successfully for book {book_id}.")
        
    except Exception as e:
        print(f"[Worker Error] Pipeline failed: {e}")
        # Mark as failed in status
        conn = db.get_db_connection()
        db.execute_query(conn, "UPDATE books SET status = 'failed' WHERE id = ?", (book_id,), commit=True)
        conn.close()

def generate_chapter_sync(book_id: str):
    """
    Helper function to generate the NEXT pending chapter in sequence.
    """
    conn = db.get_db_connection()
    
    # 1. Fetch Book Details
    book = db.execute_query(conn, "SELECT * FROM books WHERE id = ?", (book_id,), fetch_one=True)
    if not book:
        conn.close()
        return False, "Book not found"
        
    # 2. Find Next Pending Chapter outline
    next_outline = db.execute_query(conn, """
        SELECT * FROM outlines 
        WHERE book_id = ? AND status = 'pending' 
        ORDER BY chapter_number ASC LIMIT 1
    """, (book_id,), fetch_one=True)
    
    if not next_outline:
        # Mark book as completed
        db.execute_query(conn, "UPDATE books SET status = 'completed' WHERE id = ?", (book_id,), commit=True)
        conn.close()
        return True, "All chapters are already drafted."

    # 3. Retrieve previous chapter context if chapter_number > 1
    previous_chapter_text = ""
    if next_outline["chapter_number"] > 1:
        prev_ch = db.execute_query(conn, """
            SELECT content FROM chapters 
            WHERE book_id = ? AND chapter_number = ?
        """, (book_id, next_outline["chapter_number"] - 1), fetch_one=True)
        if prev_ch:
            previous_chapter_text = prev_ch["content"]

    conn.close()

    # 4. Invoke LLM to write chapter
    print(f"[Worker] Drafting Chapter {next_outline['chapter_number']} for book {book_id}...")
    char_bible = json.loads(book["character_bible"]) if book["character_bible"] else {}
    chapter_content = prompts.generate_chapter(
        title=book["title"],
        style_guide=book["style_guide"],
        character_bible=char_bible,
        chapter_num=next_outline["chapter_number"],
        chapter_title=next_outline["title"],
        goals=next_outline["goals"],
        cliffhanger_focus=next_outline["cliffhanger_focus"],
        previous_chapter_text=previous_chapter_text
    )

    # 5. Save drafted chapter to DB and mark outline status
    word_count = len(chapter_content.split())
    conn = db.get_db_connection()
    db.execute_query(conn, """
        INSERT INTO chapters (id, book_id, chapter_number, title, content, word_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), book_id, next_outline["chapter_number"], next_outline["title"], chapter_content, word_count))
    
    db.execute_query(conn, "UPDATE outlines SET status = 'completed' WHERE id = ?", (next_outline["id"],), commit=True)

    # Re-check if any pending chapters remain
    remaining_res = db.execute_query(conn, "SELECT COUNT(*) as total FROM outlines WHERE book_id = ? AND status = 'pending'", (book_id,), fetch_one=True)
    remaining = remaining_res["total"] if remaining_res else 0
    if remaining == 0:
         db.execute_query(conn, "UPDATE books SET status = 'completed' WHERE id = ?", (book_id,), commit=True)

    conn.close()
    return True, f"Chapter {next_outline['chapter_number']} generated."

@app.post("/api/books")
def create_book(req: BookCreateRequest, background_tasks: BackgroundTasks):
    book_id = str(uuid.uuid4())
    conn = db.get_db_connection()
    db.execute_query(conn, """
        INSERT INTO books (id, title, status, target_chapters)
        VALUES (?, 'Preparing Novel Adaptation...', 'processing', ?)
    """, (book_id, req.target_chapters), commit=True)
    conn.close()

    # Run adaptation pipeline asynchronously in background task
    background_tasks.add_task(background_writing_pipeline, book_id, req.reference_text, req.target_chapters)
    return {"book_id": book_id, "status": "processing"}

@app.get("/api/books")
def list_books():
    conn = db.get_db_connection()
    books = db.execute_query(conn, "SELECT * FROM books ORDER BY created_at DESC", fetch_all=True)
    conn.close()
    return [dict(b) for b in books]

@app.get("/api/books/{book_id}")
def get_book_details(book_id: str):
    conn = db.get_db_connection()
    book = db.execute_query(conn, "SELECT * FROM books WHERE id = ?", (book_id,), fetch_one=True)
    if not book:
        conn.close()
        raise HTTPException(status_code=404, detail="Book not found")
    
    outlines = db.execute_query(conn, "SELECT * FROM outlines WHERE book_id = ? ORDER BY chapter_number ASC", (book_id,), fetch_all=True)
    chapters = db.execute_query(conn, "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_number ASC", (book_id,), fetch_all=True)
    conn.close()
    
    return {
        "book": dict(book),
        "outlines": [dict(o) for o in outlines],
        "chapters": [dict(c) for c in chapters]
    }

@app.post("/api/books/{book_id}/generate_next")
def generate_next_chapter(book_id: str, background_tasks: BackgroundTasks):
    """
    Trigger the background generation of the next chapter.
    """
    def run_gen():
        generate_chapter_sync(book_id)
        
    background_tasks.add_task(run_gen)
    return {"status": "triggered"}

@app.get("/api/books/{book_id}/download")
def download_pdf(book_id: str):
    conn = db.get_db_connection()
    book = db.execute_query(conn, "SELECT * FROM books WHERE id = ?", (book_id,), fetch_one=True)
    if not book:
        conn.close()
        raise HTTPException(status_code=404, detail="Book not found")
        
    chapters = db.execute_query(conn, "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_number ASC", (book_id,), fetch_all=True)
    conn.close()
    
    if not chapters:
        raise HTTPException(status_code=400, detail="No chapters have been drafted yet.")
        
    safe_title = "".join(x for x in book["title"] if x.isalnum() or x in " -_").strip()
    pdf_filename = f"{safe_title}.pdf"
    
    # Save target locally for compilation
    pdf_path = os.path.join(os.path.dirname(__file__), pdf_filename)
    
    # Compile text/PDF structure
    compiler.compile_chapters(
        book_title=book["title"],
        author_name="Luna AI Writer",
        chapters=[dict(c) for c in chapters],
        output_filename=pdf_path
    )
    
    # Try uploading to Azure Blob Storage
    cloud_url = storage.upload_to_azure_blob(pdf_path, pdf_filename)
    if cloud_url:
        # Instantly redirect client browser to Azure Blob download URL with 2-hour secure SAS
        return RedirectResponse(url=cloud_url, status_code=307)
        
    # Zero-cost local fallback if Azure connection string is absent
    return FileResponse(
        pdf_path,
        media_type='application/pdf' if not pdf_path.endswith('.html') else 'text/html',
        filename=pdf_filename
    )
