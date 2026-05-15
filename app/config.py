from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
import secrets

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
REPORT_DIR = BASE_DIR / "reports"
for d in (DATA_DIR, UPLOAD_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

class Settings(BaseSettings):
    app_name: str = "ThesisGuard"
    database_url: str = f"sqlite:///{(DATA_DIR / 'thesisguard.db').as_posix()}"
    secret_key: str = secrets.token_hex(32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    # Gmail SMTP
    gmail_user: str | None = None
    gmail_password: str | None = None
    app_base_url: str = "http://localhost:8000"
    # Sapling
    sapling_api_key: str | None = None
    # LanguageTool
    languagetool_url: str = "https://api.languagetool.org/v2/check"
    # Plagiarism
    plagiarism_api_key: str | None = None
    plagiarism_api_url: str | None = None
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
