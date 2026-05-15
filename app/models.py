from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    # roles: admin, teacher, student
    role = Column(String(20), nullable=False, default="student")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    submissions = relationship("Submission", back_populates="user")

class Template(Base):
    __tablename__ = "templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    document_type = Column(String(100), nullable=False)
    config_json = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    submissions = relationship("Submission", back_populates="template")

class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    file_hash_sha256 = Column(String(64), nullable=False, index=True)
    content_type = Column(String(120), nullable=True)
    status = Column(String(50), nullable=False, default="processed")
    report_path = Column(String(500), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    version = Column(Integer, default=1)
    parent_submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    template = relationship("Template", back_populates="submissions")
    user = relationship("User", back_populates="submissions")
    resubmissions = relationship("Submission", backref="parent", remote_side="Submission.id", foreign_keys="Submission.parent_submission_id")
