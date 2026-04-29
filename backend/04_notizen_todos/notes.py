import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
from database import get_db
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

router = APIRouter(tags=["Notizen & To-dos"])
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ─── Models ───────────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    title: Optional[str] = None
    content: str

class NoteAppend(BaseModel):
    content: str

class NoteOut(BaseModel):
    id: int
    title: Optional[str]
    content: str
    created_at: str
    updated_at: str

class TodoCreate(BaseModel):
    text: str
    due_date: Optional[str] = None

class TodoFromText(BaseModel):
    text: str

class TodoOut(BaseModel):
    id: int
    text: str
    done: bool
    due_date: Optional[str]
    created_at: str


# ─── Notizen ──────────────────────────────────────────────────────────────────

@router.get("/notes", response_model=list[NoteOut])
async def get_notes():
    """Gibt alle gespeicherten Notizen zurück."""
    async with get_db() as db:
        cursor = await db.execute("SELECT id, title, content, created_at, updated_at FROM notes ORDER BY updated_at DESC")
        rows = await cursor.fetchall()
    return [NoteOut(id=r[0], title=r[1], content=r[2], created_at=r[3], updated_at=r[4]) for r in rows]


@router.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(note: NoteCreate):
    """Erstellt eine neue Notiz."""
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO notes (title, content) VALUES (?, ?)",
            (note.title, note.content),
        )
        await db.commit()
        row = await (await db.execute(
            "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
            (cursor.lastrowid,)
        )).fetchone()
    return NoteOut(id=row[0], title=row[1], content=row[2], created_at=row[3], updated_at=row[4])


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def append_to_note(note_id: int, body: NoteAppend):
    """Hängt Inhalt an eine bestehende Notiz an."""
    async with get_db() as db:
        row = await (await db.execute("SELECT content FROM notes WHERE id = ?", (note_id,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Notiz nicht gefunden.")
        new_content = row[0] + "\n" + body.content
        await db.execute(
            "UPDATE notes SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_content, note_id),
        )
        await db.commit()
        updated = await (await db.execute(
            "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?", (note_id,)
        )).fetchone()
    return NoteOut(id=updated[0], title=updated[1], content=updated[2], created_at=updated[3], updated_at=updated[4])


# ─── To-dos ───────────────────────────────────────────────────────────────────

@router.get("/todos", response_model=list[TodoOut])
async def get_todos():
    """Gibt alle offenen To-dos zurück."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, text, done, due_date, created_at FROM todos ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
    return [TodoOut(id=r[0], text=r[1], done=bool(r[2]), due_date=r[3], created_at=r[4]) for r in rows]


@router.post("/todos", response_model=TodoOut, status_code=201)
async def create_todo(todo: TodoCreate):
    """Erstellt einen einzelnen To-do-Eintrag."""
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO todos (text, due_date) VALUES (?, ?)",
            (todo.text, todo.due_date),
        )
        await db.commit()
        row = await (await db.execute(
            "SELECT id, text, done, due_date, created_at FROM todos WHERE id = ?", (cursor.lastrowid,)
        )).fetchone()
    return TodoOut(id=row[0], text=row[1], done=bool(row[2]), due_date=row[3], created_at=row[4])


@router.post("/todos/from-text", response_model=list[TodoOut], status_code=201)
async def create_todos_from_text(body: TodoFromText):
    """
    Extrahiert mehrere To-dos aus einem längeren Text per LLM
    und speichert alle auf einmal.
    """
    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=(
                "Extrahiere aus dem folgenden Text alle Aufgaben als JSON-Array. "
                "Gib NUR ein JSON-Array zurück, z.B.: [\"Aufgabe 1\", \"Aufgabe 2\"]"
            ),
            messages=[{"role": "user", "content": body.text}],
        )
        raw = message.content[0].text.strip()
        # Markdown-Codeblöcke entfernen falls vorhanden
        raw = raw.replace("```json", "").replace("```", "").strip()
        # Array aus dem Text extrahieren
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            raise ValueError("Kein Array gefunden")
        tasks = json.loads(raw[start:end])
        if not isinstance(tasks, list):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=500, detail="To-dos konnten nicht extrahiert werden.")

    created = []
    async with get_db() as db:
        for task_text in tasks:
            if isinstance(task_text, str) and task_text.strip():
                cursor = await db.execute("INSERT INTO todos (text) VALUES (?)", (task_text.strip(),))
                row = await (await db.execute(
                    "SELECT id, text, done, due_date, created_at FROM todos WHERE id = ?", (cursor.lastrowid,)
                )).fetchone()
                created.append(TodoOut(id=row[0], text=row[1], done=bool(row[2]), due_date=row[3], created_at=row[4]))
        await db.commit()

    return created


@router.patch("/todos/{todo_id}/done")
async def mark_todo_done(todo_id: int):
    """Markiert ein To-do als erledigt."""
    async with get_db() as db:
        result = await db.execute("UPDATE todos SET done = 1 WHERE id = ?", (todo_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="To-do nicht gefunden.")
    return {"status": "ok", "id": todo_id, "done": True}
