from typing import Any
from pydantic import BaseModel, Field, EmailStr

class Margins(BaseModel):
    top: float; bottom: float; left: float; right: float

class TemplateCreate(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    document_type: str = Field(default="thesis")
    allowed_fonts: list[str] = Field(default_factory=lambda: ["Times New Roman"])
    allowed_font_sizes: list[int] = Field(default_factory=lambda: [12])
    line_spacing: float = 1.5
    margins_cm: Margins
    required_sections: list[str] = Field(default_factory=list)
    heading_patterns: list[str] = Field(default_factory=list)
    citation_style: str | None = None
    notes: str | None = None

class TemplateResponse(TemplateCreate):
    id: int
    model_config = {"from_attributes": True}

class SectionFlag(BaseModel):
    label: str; severity: str; details: str; location_hint: str | None = None

class GrammarSuggestion(BaseModel):
    message: str; short_message: str; original: str; suggestions: list[str]
    offset: int; length: int; rule_id: str; category: str; context: str

class GrammarReport(BaseModel):
    total_issues: int; error_count: int; warning_count: int; suggestion_count: int
    issues: list[GrammarSuggestion]; notes: list[str]

class ComplianceReport(BaseModel):
    compliance_score: float; passed_checks: list[str]
    warnings: list[SectionFlag]; errors: list[SectionFlag]; extracted_sections: list[str]

class AIRiskReport(BaseModel):
    risk_level: str; risk_score: float; flagged_segments: list[SectionFlag]; notes: list[str]

class PlagiarismReport(BaseModel):
    similarity_score: float; exact_match_score: float; near_match_score: float
    flagged_sources: list[dict[str, Any]]; notes: list[str]

class SubmissionReport(BaseModel):
    submission_id: int; template_name: str; original_filename: str
    file_hash_sha256: str; created_at: str | None = None
    compliance: ComplianceReport; ai_risk: AIRiskReport
    plagiarism: PlagiarismReport; grammar: GrammarReport | None = None
    final_summary: str

class SubmissionResponse(BaseModel):
    id: int; original_filename: str; status: str
    template_id: int; file_hash_sha256: str; version: int
    model_config = {"from_attributes": True}

# Auth
class SignupRequest(BaseModel):
    email: str; password: str = Field(min_length=8); full_name: str | None = None

class LoginRequest(BaseModel):
    email: str; password: str

class UserResponse(BaseModel):
    id: int; email: str; full_name: str | None = None
    role: str; is_active: bool
    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    full_name: str | None = None; role: str | None = None; is_active: bool | None = None

class SubmissionListItem(BaseModel):
    id: int; original_filename: str; status: str; template_id: int
    file_hash_sha256: str; version: int; created_at: str | None = None
    user_email: str | None = None; compliance_score: float | None = None
    ai_risk_level: str | None = None
    model_config = {"from_attributes": True}

class ReviewerNoteUpdate(BaseModel):
    reviewer_notes: str
