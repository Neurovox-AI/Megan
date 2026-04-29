from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import anthropic
from database import get_db
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

router = APIRouter(prefix="/drafts", tags=["Drafts"])

def _get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class EmailDraftCreate(BaseModel):
    recipient: str
    subject: Optional[str] = None
    body_instruction: str


class MessageDraftCreate(BaseModel):
    recipient: str
    body_instruction: str


class DraftOut(BaseModel):
    id: int
    type: str
    recipient: Optional[str]
    subject: Optional[str]
    body: str
    created_at: str


@router.get("", response_model=list[DraftOut])
async def get_drafts(type: Optional[str] = None):
    """Gibt alle gespeicherten Entwürfe zurück. Optional nach Typ filtern: email / message"""
    async with get_db() as db:
        if type:
            cursor = await db.execute(
                "SELECT id, type, recipient, subject, body, created_at FROM drafts WHERE type = ? ORDER BY created_at DESC",
                (type,)
            )
        else:
            cursor = await db.execute(
                "SELECT id, type, recipient, subject, body, created_at FROM drafts ORDER BY created_at DESC"
            )
        rows = await cursor.fetchall()
    return [DraftOut(id=r[0], type=r[1], recipient=r[2], subject=r[3], body=r[4], created_at=r[5]) for r in rows]


@router.post("/email", response_model=DraftOut, status_code=201)
async def create_email_draft(req: EmailDraftCreate):
    """
    Formuliert einen E-Mail-Entwurf per LLM und speichert ihn.
    WICHTIG: Die E-Mail wird NICHT gesendet – nur als Entwurf gespeichert.
    """
    subject = req.subject or await _generate_subject(req.body_instruction, req.recipient)
    body = await _generate_email_body(req.recipient, req.body_instruction)

    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO drafts (type, recipient, subject, body) VALUES (?, ?, ?, ?)",
            ("email", req.recipient, subject, body),
        )
        await db.commit()
        row = await (await db.execute(
            "SELECT id, type, recipient, subject, body, created_at FROM drafts WHERE id = ?",
            (cursor.lastrowid,)
        )).fetchone()

    return DraftOut(id=row[0], type=row[1], recipient=row[2], subject=row[3], body=row[4], created_at=row[5])


@router.post("/message", response_model=DraftOut, status_code=201)
async def create_message_draft(req: MessageDraftCreate):
    """
    Formuliert einen kurzen Nachrichten-Entwurf per LLM und speichert ihn.
    WICHTIG: Die Nachricht wird NICHT gesendet – nur als Entwurf gespeichert.
    """
    body = await _generate_message_body(req.recipient, req.body_instruction)

    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO drafts (type, recipient, subject, body) VALUES (?, ?, ?, ?)",
            ("message", req.recipient, None, body),
        )
        await db.commit()
        row = await (await db.execute(
            "SELECT id, type, recipient, subject, body, created_at FROM drafts WHERE id = ?",
            (cursor.lastrowid,)
        )).fetchone()

    return DraftOut(id=row[0], type=row[1], recipient=row[2], subject=row[3], body=row[4], created_at=row[5])


@router.delete("/{draft_id}")
async def delete_draft(draft_id: int):
    """Löscht einen Entwurf anhand der ID."""
    async with get_db() as db:
        result = await db.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entwurf nicht gefunden.")
    return {"status": "ok", "deleted_id": draft_id}


# ─── LLM-Hilfsfunktionen ──────────────────────────────────────────────────────

async def _generate_email_body(recipient: str, instruction: str) -> str:
    try:
        msg = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            system=(
                "Du schreibst kurze, professionelle E-Mails auf Deutsch. "
                "Gib NUR den E-Mail-Text zurück, keine Erklärungen."
            ),
            messages=[{
                "role": "user",
                "content": f"Empfänger: {recipient}\nAnweisung: {instruction}"
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"E-Mail konnte nicht formuliert werden: {str(e)}")


async def _generate_subject(instruction: str, recipient: str) -> str:
    try:
        msg = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=50,
            system="Formuliere einen kurzen E-Mail-Betreff (max. 8 Wörter) auf Deutsch. NUR der Betreff, kein weiterer Text.",
            messages=[{"role": "user", "content": f"Empfänger: {recipient}, Inhalt: {instruction}"}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return "Kein Betreff"


async def _generate_message_body(recipient: str, instruction: str) -> str:
    try:
        msg = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=150,
            system=(
                "Du schreibst kurze, natürliche Nachrichten auf Deutsch (wie SMS oder WhatsApp). "
                "Gib NUR den Nachrichtentext zurück."
            ),
            messages=[{
                "role": "user",
                "content": f"Empfänger: {recipient}\nAnweisung: {instruction}"
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nachricht konnte nicht formuliert werden: {str(e)}")
