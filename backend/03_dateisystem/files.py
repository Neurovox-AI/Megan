import os
import subprocess
import platform
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from config import SEARCH_PATHS

router = APIRouter(prefix="/files", tags=["Dateisystem"])


class FileItem(BaseModel):
    name: str
    path: str
    modified_at: Optional[str] = None
    filetype: str


class OpenFileRequest(BaseModel):
    path: str


@router.get("/search", response_model=list[FileItem])
async def search_files(q: str = Query(..., description="Suchbegriff"), filetype: Optional[str] = None):
    """
    Sucht nach Dateien auf dem Computer des Nutzers.
    Durchsucht Desktop, Downloads, Dokumente und Home.
    """
    if len(q) < 2:
        raise HTTPException(status_code=400, detail="Suchbegriff muss mindestens 2 Zeichen lang sein.")

    results = []
    q_lower = q.lower()

    for base_path in SEARCH_PATHS:
        if not os.path.exists(base_path):
            continue
        try:
            for root, dirs, files in os.walk(base_path):
                # Versteckte Ordner überspringen
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                for filename in files:
                    if filename.startswith("."):
                        continue

                    name_lower = filename.lower()
                    if q_lower not in name_lower:
                        continue

                    ext = Path(filename).suffix.lower().lstrip(".")
                    if filetype and ext != filetype.lower():
                        continue

                    full_path = os.path.join(root, filename)
                    try:
                        mtime = os.path.getmtime(full_path)
                        from datetime import datetime
                        modified = datetime.fromtimestamp(mtime).isoformat()
                    except OSError:
                        modified = None

                    results.append(FileItem(
                        name=filename,
                        path=full_path,
                        modified_at=modified,
                        filetype=ext or "unbekannt",
                    ))

                    if len(results) >= 10:
                        return _sort_by_modified(results)
        except PermissionError:
            continue

    return _sort_by_modified(results)


@router.get("/recent", response_model=list[FileItem])
async def get_recent_files():
    """
    Gibt die zuletzt verwendeten Dateien zurück (macOS: aus NSRecentDocuments).
    """
    results = []

    if platform.system() == "Darwin":
        results = _get_recent_macos()

    # Fallback: Neueste Dateien aus Standard-Ordnern
    if not results:
        results = _get_recent_fallback()

    return results[:10]


@router.post("/open")
async def open_file(req: OpenFileRequest):
    """
    Öffnet eine Datei oder einen Ordner mit der Standard-App des Systems.
    """
    if not os.path.exists(req.path):
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {req.path}")

    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", req.path])
        elif platform.system() == "Windows":
            os.startfile(req.path)
        else:
            subprocess.Popen(["xdg-open", req.path])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Datei konnte nicht geöffnet werden: {str(e)}")

    return {"status": "ok", "opened": req.path}


def _get_recent_macos() -> list[FileItem]:
    """Liest Recent Items auf macOS via plist."""
    try:
        import plistlib
        recent_plist = os.path.expanduser(
            "~/Library/Application Support/com.apple.sharedfilelist/com.apple.LSSharedFileList.RecentDocuments.sfl2"
        )
        if not os.path.exists(recent_plist):
            return []

        with open(recent_plist, "rb") as f:
            data = plistlib.load(f)

        items = []
        for item in data.get("items", [])[:10]:
            url = item.get("URL", "")
            if url.startswith("file://"):
                path = url.replace("file://", "").rstrip("/")
                if os.path.exists(path):
                    name = os.path.basename(path)
                    ext = Path(name).suffix.lower().lstrip(".")
                    items.append(FileItem(name=name, path=path, filetype=ext or "unbekannt"))
        return items
    except Exception:
        return []


def _get_recent_fallback() -> list[FileItem]:
    """Fallback: Neueste Dateien aus Standard-Ordnern nach Änderungsdatum."""
    from datetime import datetime
    all_files = []
    for base_path in SEARCH_PATHS[:2]:  # Nur Desktop + Downloads
        if not os.path.exists(base_path):
            continue
        try:
            for f in os.listdir(base_path):
                if f.startswith("."):
                    continue
                full = os.path.join(base_path, f)
                if os.path.isfile(full):
                    mtime = os.path.getmtime(full)
                    all_files.append((mtime, full, f))
        except PermissionError:
            continue

    all_files.sort(reverse=True)
    result = []
    for mtime, path, name in all_files[:10]:
        ext = Path(name).suffix.lower().lstrip(".")
        result.append(FileItem(
            name=name,
            path=path,
            modified_at=datetime.fromtimestamp(mtime).isoformat(),
            filetype=ext or "unbekannt",
        ))
    return result


def _sort_by_modified(items: list[FileItem]) -> list[FileItem]:
    return sorted(items, key=lambda x: x.modified_at or "", reverse=True)
