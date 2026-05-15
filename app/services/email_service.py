from __future__ import annotations
from app.config import settings


async def send_magic_link(email: str, token: str) -> bool:
    """Send magic link email. Returns True if sent, False if email not configured."""
    link = f"{settings.app_base_url}/auth/verify?token={token}"

    if not settings.resend_api_key:
        # Dev mode — print to console
        print(f"\n{'='*60}")
        print(f"MAGIC LINK FOR: {email}")
        print(f"Link: {link}")
        print(f"(Expires in {settings.magic_link_expire_minutes} minutes, single use)")
        print(f"{'='*60}\n")
        return True

    try:
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.email_from,
            "to": email,
            "subject": "Your ThesisGuard Login Link",
            "html": f"""
            <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 32px;">
              <h2 style="color:#7c6af7;">ThesisGuard</h2>
              <p>Click the button below to log in. This link expires in
                <strong>{settings.magic_link_expire_minutes} minutes</strong>
                and can only be used <strong>once</strong>.</p>
              <a href="{link}"
                 style="display:inline-block; background:#7c6af7; color:#fff;
                        padding:12px 28px; border-radius:8px; text-decoration:none;
                        font-weight:bold; margin:16px 0;">
                Log in to ThesisGuard
              </a>
              <p style="color:#999; font-size:12px;">
                If you didn't request this, you can safely ignore this email.
              </p>
            </div>
            """,
        })
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


async def send_report_ready(email: str, submission_id: int, filename: str) -> None:
    """Notify student that their report is ready."""
    link = f"{settings.app_base_url}/#report"

    if not settings.resend_api_key:
        print(f"\nREPORT READY notification for {email} — submission #{submission_id}")
        return

    try:
        import resend
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.email_from,
            "to": email,
            "subject": f"Your ThesisGuard report is ready — {filename}",
            "html": f"""
            <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto; padding: 32px;">
              <h2 style="color:#7c6af7;">ThesisGuard</h2>
              <p>Your thesis <strong>{filename}</strong> has been verified.</p>
              <p>Submission ID: <strong>#{submission_id}</strong></p>
              <a href="{link}"
                 style="display:inline-block; background:#7c6af7; color:#fff;
                        padding:12px 28px; border-radius:8px; text-decoration:none;
                        font-weight:bold; margin:16px 0;">
                View Report
              </a>
            </div>
            """,
        })
    except Exception as e:
        print(f"Report notification failed: {e}")
