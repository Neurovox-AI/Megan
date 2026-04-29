import json
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from database import get_db
from config import HISTORY_DEFAULT_LIMIT

router = APIRouter(prefix="/history", tags=["Aktionsverlauf"])


class HistoryEntry(BaseModel):
    id: int
    intent: str
    parameters: Optional[dict]
    result: str
    summary: str
    created_at: str


@router.get("", response_model=list[HistoryEntry])
async def get_history(
    limit: int = Query(default=HISTORY_DEFAULT_LIMIT, ge=1, le=100),
    intent: Optional[str] = None,
):
    """
    Gibt den Aktionsverlauf zurück.
    Optional nach Intent filtern, z.B. ?intent=create_note
    """
    async with get_db() as db:
        if intent:
            cursor = await db.execute(
                "SELECT id, intent, parameters, result, summary, created_at FROM history WHERE intent = ? ORDER BY created_at DESC LIMIT ?",
                (intent, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT id, intent, parameters, result, summary, created_at FROM history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()

    return [
        HistoryEntry(
            id=r[0],
            intent=r[1],
            parameters=json.loads(r[2]) if r[2] else None,
            result=r[3],
            summary=r[4],
            created_at=r[5],
        )
        for r in rows
    ]


@router.delete("/{entry_id}")
async def delete_history_entry(entry_id: int):
    """Löscht einen einzelnen Verlaufseintrag."""
    async with get_db() as db:
        result = await db.execute("DELETE FROM history WHERE id = ?", (entry_id,))
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Verlaufseintrag nicht gefunden.")
    return {"status": "ok", "deleted_id": entry_id}


@router.delete("")
async def clear_history(confirm: bool = Query(default=False)):
    """
    Löscht den gesamten Verlauf.
    Sicherheitsprüfung: ?confirm=true muss gesetzt sein.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Sicherheitscheck: ?confirm=true setzen um den gesamten Verlauf zu löschen."
        )
    async with get_db() as db:
        await db.execute("DELETE FROM history")
        await db.commit()
    return {"status": "ok", "message": "Verlauf vollständig gelöscht."}
