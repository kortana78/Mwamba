"""Admin: users, audit log, API keys. Document OCR + review queue live here too
(documents endpoints are functional without any LLM key; LLM extraction is an
optional enhancement that never bypasses review)."""
from __future__ import annotations
import hashlib
import os
import secrets
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..deps import current_user, guard_write, require_role, audit
from ..config import settings

router = APIRouter(tags=["admin"])


@router.get("/admin/users")
async def users(user: models.User = Depends(require_role("admin")),
                db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.User).where(models.User.org_id == user.org_id))
    return {"items": [{"id": u.id, "email": u.email, "role": u.role} for u in res.scalars().all()]}


@router.get("/admin/audit")
async def audit_log(limit: int = Query(100, le=500), offset: int = 0,
                    user: models.User = Depends(require_role("admin")),
                    db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.AuditLog).where(models.AuditLog.org_id == user.org_id)
                           .order_by(models.AuditLog.created_at.desc()).limit(limit).offset(offset))
    return {"items": [{"id": a.id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
                       "detail": a.detail, "user_id": a.user_id,
                       "at": a.created_at.isoformat() if a.created_at else None}
                      for a in res.scalars().all()]}


@router.post("/admin/api-keys")
async def create_key(user: models.User = Depends(require_role("admin", "geologist", "analyst")),
                     db: AsyncSession = Depends(get_db)):
    secret = secrets.token_urlsafe(32)
    prefix = "mk" + secrets.token_hex(4)
    raw = f"mw_{prefix}.{secret}"
    h = hashlib.sha256(raw.encode()).hexdigest()
    k = models.ApiKey(org_id=user.org_id, user_id=user.id, prefix=f"mw_{prefix}", key_hash=h)
    db.add(k)
    await db.flush()
    await audit(db, user, "apikey.create", "api_key", k.id, prefix)
    await db.commit()
    return {"api_key": raw, "prefix": f"mw_{prefix}",
            "note": "Store once — only the hash is kept. Pass as Bearer token."}


@router.post("/documents/upload")
async def upload_doc(file: UploadFile = File(...),
                     user: models.User = Depends(guard_write),
                     db: AsyncSession = Depends(get_db)):
    raw = await file.read()
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF reports accepted here (OCR pipeline: pypdf text layer; scanned-image OCR via ocrmypdf documented in docs/)")
    texts = os.path.join(settings.MWAMBA_STORAGE_DIR, "texts")
    os.makedirs(texts, exist_ok=True)
    did = uuid.uuid4().hex[:12]
    pdf_path = os.path.join(texts, did + ".pdf")
    with open(pdf_path, "wb") as f:
        f.write(raw)
    # text extraction via pypdf (works for born-digital PDFs; scanned pages noted)
    pages, full = 0, ""
    try:
        from pypdf import PdfReader
        import io as _io
        reader = PdfReader(_io.BytesIO(raw))
        pages = len(reader.pages)
        chunks = []
        for i, pg in enumerate(reader.pages):
            try:
                chunks.append(f"\n--- page {i+1} ---\n" + (pg.extract_text() or ""))
            except Exception:
                chunks.append(f"\n--- page {i+1} ---\n[unreadable]")
        full = "\n".join(chunks)
    except Exception as e:
        full = f"[text extraction failed: {e}]"
    tp = os.path.join(texts, did + ".txt")
    with open(tp, "w", encoding="utf-8") as f:
        f.write(full)
    doc = models.Document(org_id=user.org_id, filename=file.filename or "report.pdf",
                          pages=pages, text_path=tp, status="stored")
    db.add(doc)
    await db.flush()
    # naive candidate extraction (regex for coordinates + Au mentions) -> REVIEW QUEUE
    import re
    cands = 0
    coord_re = re.compile(r"(-?\d{1,2}\.\d+)\s*[,;/]\s*(-?\d{1,2}\.\d+)")
    for m in coord_re.finditer(full[:200000]):
        lat_s, lon_s = m.group(1), m.group(2)
        try:
            a, b = float(lat_s), float(lon_s)
        except ValueError:
            continue
        # guess order: Malawi lon 32.6..35.9, lat -17.2..-9.3
        lon, lat = (a, b) if 32.0 <= a <= 36.5 else (b, a)
        if not (32.6 <= lon <= 35.9 and -17.2 <= lat <= -9.3):
            continue
        page = full[:m.start()].count("--- page") + 1
        db.add(models.Extraction(doc_id=doc.id, kind="candidate_coordinate",
                                 payload={"lon": lon, "lat": lat, "status_label": "MODEL OUTPUT"},
                                 page=page, snippet=full[max(0, m.start()-160):m.start()+160],
                                 review_state="pending"))
        cands += 1
        if cands >= 50:
            break
    if settings.LLM_EXTRACTION_ENABLED and settings.OPENAI_API_KEY:
        doc.status = "stored+llm_pending"
    await audit(db, user, "document.upload", "document", doc.id,
                f"{doc.filename} pages={pages} candidates={cands}")
    await db.commit()
    return {"id": doc.id, "pages": pages, "candidates": cands,
            "note": "All extracted records enter the REVIEW QUEUE as unverified. "
                    "Accept/edit/reject before analysis. LLM output never enters analysis directly."}


@router.get("/documents")
async def list_docs(user: models.User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.Document).where(models.Document.org_id == user.org_id)
                           .order_by(models.Document.created_at.desc()))
    return {"items": [{"id": d.id, "filename": d.filename, "pages": d.pages, "status": d.status} for d in res.scalars().all()]}


@router.get("/extractions")
async def list_extractions(review_state: str | None = None,
                           user: models.User = Depends(current_user),
                           db: AsyncSession = Depends(get_db)):
    docs = (await db.execute(select(models.Document).where(models.Document.org_id == user.org_id))).scalars().all()
    dids = {d.id for d in docs}
    q = select(models.Extraction).order_by(models.Extraction.created_at.desc())
    if review_state:
        q = q.where(models.Extraction.review_state == review_state)
    items = [e for e in (await db.execute(q)).scalars().all() if e.doc_id in dids]
    return {"items": [{"id": e.id, "doc_id": e.doc_id, "kind": e.kind, "payload": e.payload,
                       "page": e.page, "snippet": e.snippet, "review_state": e.review_state} for e in items],
            "note": "Review queue — nothing here enters analysis until accepted."}


@router.patch("/extractions/{eid}")
async def review_extraction(eid: str, body: schemas.ExtractionReviewIn,
                            user: models.User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    if user.role not in ("admin", "geologist"):
        raise HTTPException(403, "Only Admin/Geologist can review extractions")
    e = await db.get(models.Extraction, eid)
    if e is None:
        raise HTTPException(404, "Extraction not found")
    e.review_state = body.review_state
    await audit(db, user, "extraction.review", "extraction", eid, body.review_state)
    await db.commit()
    return {"id": e.id, "review_state": e.review_state}
