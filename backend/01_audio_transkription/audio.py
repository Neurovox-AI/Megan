import io
import tempfile
import os
from faster_whisper import WhisperModel
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/transcribe", tags=["Audio & Transkription"])

# Modell wird einmalig geladen (beim ersten Aufruf) und dann im Speicher gehalten
# "small" = gute Balance aus Geschwindigkeit und Qualität für Deutsch
# "medium" = besser für Deutsch, etwas langsamer
_model = None

def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print("Whisper Modell wird geladen (einmalig)...")
        _model = WhisperModel("small", device="cpu", compute_type="int8")
        print("Whisper Modell bereit.")
    return _model


class TranscriptionResult(BaseModel):
    text: str
    confidence: float
    language: str


@router.post("", response_model=TranscriptionResult)
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Nimmt eine Audio-Datei entgegen und gibt den transkribierten Text zurück.
    Läuft vollständig lokal – kein Internet nötig.
    Unterstützte Formate: mp3, mp4, wav, m4a, webm
    """
    audio_bytes = await file.read()

    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Audio zu kurz oder leer.")

    # Temporäre Datei anlegen damit faster-whisper lesen kann
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        model = _get_model()
        segments, info = model.transcribe(
            tmp_path,
            language="de",
            beam_size=5,
            vad_filter=True,          # Stille automatisch herausfiltern
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        text_parts = [seg.text for seg in segments]
        full_text = " ".join(text_parts).strip()

        if not full_text:
            raise HTTPException(status_code=422, detail="Keine Sprache erkannt – bitte erneut versuchen.")

        # Konfidenz aus den Segmenten berechnen
        confidence = _estimate_confidence(segments)

    finally:
        os.unlink(tmp_path)

    return TranscriptionResult(
        text=full_text,
        confidence=confidence,
        language=info.language,
    )


def _estimate_confidence(segments) -> float:
    """Durchschnittliche Konfidenz aus den Whisper-Segmenten."""
    import math
    scores = []
    for seg in segments:
        if hasattr(seg, "avg_logprob") and seg.avg_logprob is not None:
            score = math.exp(seg.avg_logprob)
            scores.append(min(max(score, 0.0), 1.0))
    return round(sum(scores) / len(scores), 2) if scores else 0.8
