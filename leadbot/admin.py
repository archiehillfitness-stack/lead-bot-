"""Password-protected lead dashboard."""
import csv
import io
import secrets
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from .db import STATUSES, Database

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
basic = HTTPBasic()


def require_admin(request: Request, creds: HTTPBasicCredentials = Depends(basic)) -> None:
    settings = request.app.state.settings
    if not settings.admin_password:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD to use the dashboard")
    ok_user = secrets.compare_digest(creds.username.encode(), settings.admin_username.encode())
    ok_pass = secrets.compare_digest(creds.password.encode(), settings.admin_password.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    # Browsers resend Basic auth automatically, so block form posts from other sites.
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(status_code=403, detail="Cross-site request blocked")


def get_db(request: Request) -> Database:
    return request.app.state.db


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def leads(request: Request, status: str = "", view: str = "", db: Database = Depends(get_db)):
    rows = db.list_leads(status=status or None, needs_reply=view == "needs_reply",
                         follow_up_due=view == "follow_up")
    return templates.TemplateResponse(request, "leads.html", {
        "leads": rows, "counts": db.counts(), "statuses": STATUSES,
        "status": status, "view": view, "today": date.today().isoformat(),
    })


@router.get("/export.csv", dependencies=[Depends(require_admin)])
def export(request: Request, db: Database = Depends(get_db)):
    rows = db.list_leads()
    keys = sorted({k for r in rows for k in r["answers"]})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["username", "ig_id", "source", "stage", "status", "consent_at",
                     *keys, "notes", "follow_up_on", "created_at"])
    for r in rows:
        writer.writerow([r["username"], r["ig_id"], r["source"], r["stage"], r["status"],
                         r["consent_at"], *[r["answers"].get(k, "") for k in keys],
                         r["notes"], r["follow_up_on"], r["created_at"]])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=leads.csv"})


@router.get("/leads/{ig_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def lead_detail(request: Request, ig_id: str, db: Database = Depends(get_db)):
    lead = db.get_lead(ig_id)
    if not lead:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "lead.html", {
        "lead": lead, "messages": db.messages_for(ig_id), "statuses": STATUSES,
    })


@router.post("/leads/{ig_id}", dependencies=[Depends(require_admin)])
def update_lead(ig_id: str, status: str = Form(...), notes: str = Form(""),
                follow_up_on: str = Form(""), needs_reply: str = Form(""),
                db: Database = Depends(get_db)):
    if not db.get_lead(ig_id):
        raise HTTPException(status_code=404)
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    if follow_up_on:
        try:
            date.fromisoformat(follow_up_on)
        except ValueError:
            raise HTTPException(status_code=400, detail="Follow-up date must be YYYY-MM-DD")
    db.update_lead(ig_id, status=status, notes=notes, follow_up_on=follow_up_on or None,
                   needs_reply=1 if needs_reply else 0)
    return RedirectResponse(f"/admin/leads/{ig_id}", status_code=303)


@router.post("/leads/{ig_id}/delete", dependencies=[Depends(require_admin)])
def delete_lead(ig_id: str, db: Database = Depends(get_db)):
    db.delete_lead(ig_id)
    return RedirectResponse("/admin", status_code=303)
