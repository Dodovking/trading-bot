"""Chat mit dem eingebauten Assistenten. Keine externe KI: Verständnis und Antworten laufen auf diesem Server."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..assistant.brain import MAX_PENDING_AGE, execute, is_no, is_yes, respond
from ..core.db import utcnow
from ..core.models import AssistantMessage, User
from .deps import get_db, user

router = APIRouter(prefix="/api/assistent", tags=["assistent"])


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


def out(m: AssistantMessage) -> dict:
    a = m.action
    return {"id": m.id, "time": m.time, "role": m.role, "text": m.text, "state": m.action_state,
            "action": {k: a[k] for k in ("title", "changes", "warnings", "danger")} if a else None}


def _add(db: Session, u: User, role: str, text: str, action: dict | None = None) -> AssistantMessage:
    m = AssistantMessage(user_id=u.id, role=role, text=text, action=action, action_state="offen" if action else "")
    db.add(m)
    db.flush()
    return m


def _open(db: Session, u: User) -> list[AssistantMessage]:
    return list(db.scalars(select(AssistantMessage).where(AssistantMessage.user_id == u.id, AssistantMessage.action_state == "offen")
                           .order_by(AssistantMessage.id.desc())))


def _run(db: Session, u: User, m: AssistantMessage) -> AssistantMessage:
    if utcnow() - m.time > MAX_PENDING_AGE:
        m.action_state = "abgelaufen"
        return _add(db, u, "bot", "Der Vorschlag ist älter als 30 Minuten und verfallen – schreib den Auftrag bitte nochmal.")
    if m.action.get("kind") == "command":
        db.commit()  # Befehle laufen in der Engine mit eigener Sitzung
    try:
        msg = execute(db, u, m.action)
        m.action_state = "erledigt"
    except HTTPException as e:
        m.action_state = "fehler"
        msg = f"Das hat nicht geklappt: {e.detail}"
    return _add(db, u, "bot", msg)


@router.get("")
def history(u: User = Depends(user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(AssistantMessage).where(AssistantMessage.user_id == u.id).order_by(AssistantMessage.id.desc()).limit(100)))
    return [out(m) for m in reversed(rows)]


@router.post("")
def send(body: MessageIn, u: User = Depends(user), db: Session = Depends(get_db)):
    text = body.text.strip()
    mine = _add(db, u, "du", text)
    pending = _open(db, u)
    if pending and is_yes(text):
        reply = _run(db, u, pending[0])
    elif pending and is_no(text):
        pending[0].action_state = "abgebrochen"
        reply = _add(db, u, "bot", "OK, ich ändere nichts.")
    else:
        try:
            answer, action = respond(db, u, text)
        except HTTPException as e:
            answer, action = f"Das geht so nicht: {e.detail}", None
        for p in pending:  # ein neuer Auftrag ersetzt ältere, nicht bestätigte Vorschläge
            if action:
                p.action_state = "verworfen"
        if action:
            answer += "\n\nSoll ich das machen?"
        reply = _add(db, u, "bot", answer, action)
    db.commit()
    return {"messages": [out(mine), out(reply)], "changed": reply.role == "bot" and "Erledigt" in reply.text}


@router.post("/{mid}/{decision}")
def decide(mid: int, decision: str, u: User = Depends(user), db: Session = Depends(get_db)):
    m = db.get(AssistantMessage, mid)
    if m is None or m.user_id != u.id:
        raise HTTPException(404, "Nachricht nicht gefunden")
    if m.action_state != "offen":
        raise HTTPException(409, "Dieser Vorschlag ist nicht mehr offen")
    if decision == "bestaetigen":
        reply = _run(db, u, m)
    elif decision == "abbrechen":
        m.action_state = "abgebrochen"
        reply = _add(db, u, "bot", "OK, ich ändere nichts.")
    else:
        raise HTTPException(400, "Unbekannte Entscheidung")
    db.commit()
    return {"messages": [out(m), out(reply)], "changed": m.action_state == "erledigt"}


@router.delete("")
def clear(u: User = Depends(user), db: Session = Depends(get_db)):
    db.execute(delete(AssistantMessage).where(AssistantMessage.user_id == u.id))
    db.commit()
    return {"ok": True}
