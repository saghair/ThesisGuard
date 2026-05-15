from __future__ import annotations
import json, uuid
from pathlib import Path
from zipfile import BadZipFile

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, Response, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import REPORT_DIR, UPLOAD_DIR, settings
from app.database import Base, engine, get_db
from app.models import Submission, Template, User
from app.schemas import (
    LoginRequest, ReviewerNoteUpdate, SignupRequest, SubmissionListItem,
    SubmissionReport, SubmissionResponse, TemplateCreate, TemplateResponse,
    UserResponse, UserUpdate,
)
from app.auth import (
    create_access_token, get_current_user, hash_password, verify_password,
    require_admin, require_teacher, require_any,
)
from app.services.ai_detector import build_ai_risk_report
from app.services.compliance import build_compliance_report
from app.services.grammar import build_grammar_report
from app.services.integrity import sha256_for_file
from app.services.parser import parse_document
from app.services.plagiarism import build_plagiarism_report
from app.services.pdf_report import generate_pdf_report
from app.services.reporting import build_final_summary, save_report

Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ALLOWED_EXTENSIONS = {".docx", ".pdf"}
ALLOWED_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream", "application/pdf",
}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# ── Frontend ──────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def root():
    index = STATIC_DIR / "index.html"
    return FileResponse(str(index)) if index.exists() else {"message": "ThesisGuard API"}

@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}

# ── One-time admin setup (remove after first use) ─────────────────
@app.get("/setup-admin")
def setup_admin(email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Sign up first.")
    user.role = "admin"
    db.commit()
    return {"message": f"{email} is now admin!"}

# ── Auth ──────────────────────────────────────────────────────────
@app.post("/auth/signup", response_model=UserResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    user = User(
        email=payload.email.lower().strip(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="student",
    )
    db.add(user); db.commit(); db.refresh(user)
    return user

@app.post("/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your account has been deactivated.")
    token = create_access_token(user.id, user.email, user.role)
    response.set_cookie(key="access_token", value=token, httponly=True,
                        max_age=60*60*24, samesite="lax")
    return {"message": "Logged in.", "role": user.role, "email": user.email, "full_name": user.full_name}

@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out."}

@app.get("/auth/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user

# ── Users (admin only) ────────────────────────────────────────────
@app.get("/users", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()

@app.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, payload: UserUpdate,
                db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.full_name is not None: user.full_name = payload.full_name
    if payload.role is not None:
        if payload.role not in ("admin", "teacher", "student"):
            raise HTTPException(status_code=400, detail="Invalid role.")
        user.role = payload.role
    if payload.is_active is not None: user.is_active = payload.is_active
    db.commit(); db.refresh(user)
    return user

# ── Templates ─────────────────────────────────────────────────────
@app.post("/templates", response_model=TemplateResponse)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(require_teacher)):
    if db.query(Template).filter(Template.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Template with this name already exists.")
    t = Template(name=payload.name, document_type=payload.document_type,
                 config_json=payload.model_dump_json(), created_by=current_user.id)
    db.add(t); db.commit(); db.refresh(t)
    return TemplateResponse(id=t.id, **payload.model_dump())

@app.get("/templates", response_model=list[TemplateResponse])
def list_templates(db: Session = Depends(get_db)):
    return [TemplateResponse(id=t.id, **json.loads(t.config_json))
            for t in db.query(Template).filter(Template.is_active == True).order_by(Template.id).all()]

@app.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_teacher)):
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t: raise HTTPException(status_code=404, detail="Template not found.")
    t.is_active = False; db.commit()
    return {"message": "Template deactivated."}

# ── Submissions ───────────────────────────────────────────────────
@app.get("/submissions", response_model=list[SubmissionListItem])
def list_submissions(db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    q = db.query(Submission)
    if current_user.role == "student":
        q = q.filter(Submission.user_id == current_user.id)
    result = []
    for s in q.order_by(Submission.id.desc()).all():
        score, ai_level = None, None
        if s.report_path:
            try:
                d = json.loads(Path(s.report_path).read_text())
                score = d.get("compliance", {}).get("compliance_score")
                ai_level = d.get("ai_risk", {}).get("risk_level")
            except: pass
        result.append(SubmissionListItem(
            id=s.id, original_filename=s.original_filename, status=s.status,
            template_id=s.template_id, file_hash_sha256=s.file_hash_sha256,
            version=s.version, created_at=str(s.created_at) if s.created_at else None,
            user_email=s.user.email if s.user else None,
            compliance_score=score, ai_risk_level=ai_level,
        ))
    return result

@app.post("/submissions/upload", response_model=SubmissionResponse)
async def upload_submission(
    template_id: int = Query(...),
    file: UploadFile = File(...),
    resubmit_of: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any),
):
    db_template = db.query(Template).filter(Template.id == template_id, Template.is_active == True).first()
    if not db_template: raise HTTPException(status_code=404, detail="Template not found.")

    original_name = file.filename or "submission.docx"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only DOCX and PDF files are accepted.")

    unique_id = uuid.uuid4().hex
    destination = UPLOAD_DIR / f"{unique_id}_{Path(original_name).stem[:80]}{suffix}"

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit.")
    destination.write_bytes(content)

    try:
        parsed = parse_document(destination)
    except BadZipFile:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="File could not be read as a valid DOCX.")
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Failed to parse document: {exc}")

    file_hash = sha256_for_file(destination)
    template_config = json.loads(db_template.config_json)

    compliance = build_compliance_report(parsed, template_config)
    ai_risk    = await build_ai_risk_report(parsed)
    plagiarism = await build_plagiarism_report(parsed)
    grammar    = await build_grammar_report(parsed)

    version, parent_id = 1, None
    if resubmit_of:
        parent = db.query(Submission).filter(Submission.id == resubmit_of).first()
        if parent: parent_id, version = resubmit_of, parent.version + 1

    submission = Submission(
        original_filename=original_name, stored_path=str(destination),
        file_hash_sha256=file_hash, content_type=file.content_type,
        status="processed", template_id=template_id, user_id=current_user.id,
        version=version, parent_submission_id=parent_id,
    )
    db.add(submission); db.commit(); db.refresh(submission)

    report = SubmissionReport(
        submission_id=submission.id, template_name=db_template.name,
        original_filename=original_name, file_hash_sha256=file_hash,
        created_at=str(submission.created_at), compliance=compliance,
        ai_risk=ai_risk, plagiarism=plagiarism, grammar=grammar, final_summary="",
    )
    report.final_summary = build_final_summary(report)
    report_path = REPORT_DIR / f"submission_{submission.id}_report.json"
    save_report(report, report_path)

    try:
        generate_pdf_report(report, REPORT_DIR / f"submission_{submission.id}_report.pdf")
    except Exception as e:
        print(f"PDF generation failed: {e}")

    submission.report_path = str(report_path)
    db.commit()
    return SubmissionResponse.model_validate(submission)

@app.get("/submissions/{submission_id}/report", response_model=SubmissionReport)
def get_report(submission_id: int, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s: raise HTTPException(status_code=404, detail="Submission not found.")
    if current_user.role == "student" and s.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied.")
    if not s.report_path or not Path(s.report_path).exists():
        raise HTTPException(status_code=404, detail="Report not available.")
    return SubmissionReport.model_validate_json(Path(s.report_path).read_text(encoding="utf-8"))

@app.get("/submissions/{submission_id}/report/pdf")
def download_pdf(submission_id: int, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s: raise HTTPException(status_code=404, detail="Not found.")
    if current_user.role == "student" and s.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied.")
    pdf = REPORT_DIR / f"submission_{submission_id}_report.pdf"
    if not pdf.exists(): raise HTTPException(status_code=404, detail="PDF not available.")
    return FileResponse(str(pdf), media_type="application/pdf",
                        filename=f"report_{submission_id}.pdf")

@app.patch("/submissions/{submission_id}/notes")
def update_notes(submission_id: int, payload: ReviewerNoteUpdate,
                 db: Session = Depends(get_db), _: User = Depends(require_teacher)):
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s: raise HTTPException(status_code=404, detail="Not found.")
    s.reviewer_notes = payload.reviewer_notes; db.commit()
    return {"message": "Notes saved."}

@app.get("/stats")
def get_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Submission)
    if current_user.role == "student":
        q = q.filter(Submission.user_id == current_user.id)
    submissions = q.all()
    scores, ai_levels = [], {"low": 0, "medium": 0, "high": 0}
    for s in submissions:
        if s.report_path:
            try:
                d = json.loads(Path(s.report_path).read_text())
                sc = d.get("compliance", {}).get("compliance_score")
                ai = d.get("ai_risk", {}).get("risk_level", "low")
                if sc is not None: scores.append(sc)
                if ai in ai_levels: ai_levels[ai] += 1
            except: pass
    users = db.query(User).count() if current_user.role in ("admin", "teacher") else None
    return {
        "total_submissions": len(submissions),
        "avg_compliance_score": round(sum(scores)/len(scores), 1) if scores else 0,
        "ai_risk_distribution": ai_levels,
        "total_templates": db.query(Template).filter(Template.is_active == True).count(),
        "total_users": users,
    }


# ── Extract template from example file ───────────────────────────
@app.post("/templates/extract", response_model=TemplateResponse)
async def extract_template(
    name: str = Query(..., description="Name for the new template"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_teacher),
):
    """Upload an example thesis file and auto-extract formatting rules as a template."""
    from app.services.template_extractor import extract_template_from_file

    original_name = file.filename or "example.docx"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only DOCX and PDF files are accepted.")

    if db.query(Template).filter(Template.name == name).first():
        raise HTTPException(status_code=400, detail="A template with this name already exists.")

    # Save file temporarily
    unique_id = uuid.uuid4().hex
    destination = UPLOAD_DIR / f"template_extract_{unique_id}{suffix}"
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit.")
    destination.write_bytes(content)

    try:
        config = extract_template_from_file(destination, name)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Could not extract template: {exc}")
    finally:
        destination.unlink(missing_ok=True)

    import json as _json
    t = Template(
        name=name,
        document_type="thesis",
        config_json=_json.dumps(config),
        created_by=current_user.id,
    )
    db.add(t); db.commit(); db.refresh(t)

    from app.schemas import TemplateCreate, Margins
    payload = TemplateCreate(**{k: v for k, v in config.items() if k != "name"},
                              name=name, margins_cm=Margins(**config["margins_cm"]))
    return TemplateResponse(id=t.id, **payload.model_dump())


# ── Password Reset ────────────────────────────────────────────────
from app.schemas import PasswordResetRequest, PasswordResetConfirm
from app.models import PasswordResetToken
import secrets as _secrets
from datetime import datetime, timedelta, timezone as _tz

@app.post("/auth/forgot-password")
def forgot_password(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """Generate a reset token. In dev mode prints to console. In prod sends email."""
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    # Always return success to prevent email enumeration
    if not user:
        return {"message": "If this email exists, a reset link has been sent."}

    # Invalidate old tokens
    db.query(PasswordResetToken).filter(
        PasswordResetToken.email == user.email,
        PasswordResetToken.used == False
    ).delete()

    token = _secrets.token_urlsafe(48)
    expires = datetime.now(_tz.utc) + timedelta(minutes=30)
    db.add(PasswordResetToken(token=token, email=user.email, expires_at=expires))
    db.commit()

    reset_link = f"{settings.app_base_url}/reset-password?token={token}"

    # Try to send email via Gmail if configured
    if settings.gmail_user and settings.gmail_password:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(f"""
Hi,

You requested a password reset for your ThesisGuard account.

Click this link to reset your password (expires in 30 minutes):
{reset_link}

If you didn't request this, ignore this email.

— ThesisGuard
            """)
            msg['Subject'] = 'ThesisGuard — Reset your password'
            msg['From'] = settings.gmail_user
            msg['To'] = user.email
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(settings.gmail_user, settings.gmail_password)
                smtp.send_message(msg)
        except Exception as e:
            print(f"Email failed: {e}")

    # Always print to console for dev/admin visibility
    print(f"\n{'='*60}")
    print(f"PASSWORD RESET for: {user.email}")
    print(f"Link: {reset_link}")
    print(f"Expires in 30 minutes, single use")
    print(f"{'='*60}\n")

    return {"message": "If this email exists, a reset link has been sent.", "dev_token": token}


@app.post("/auth/reset-password")
def reset_password(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    """Verify token and set new password."""
    token_record = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == payload.token
    ).first()

    if not token_record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    if token_record.used:
        raise HTTPException(status_code=400, detail="This reset link has already been used.")
    if datetime.now(_tz.utc) > token_record.expires_at.replace(tzinfo=_tz.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")

    # Mark token as used immediately
    token_record.used = True
    db.commit()

    # Update password
    user = db.query(User).filter(User.email == token_record.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    from app.auth import hash_password
    user.password_hash = hash_password(payload.new_password)
    db.commit()

    return {"message": "Password updated successfully. You can now log in."}


@app.get("/reset-password", include_in_schema=False)
def reset_password_page():
    """Serve the frontend for the reset password flow."""
    index = STATIC_DIR / "index.html"
    return FileResponse(str(index)) if index.exists() else {"message": "Not found"}
