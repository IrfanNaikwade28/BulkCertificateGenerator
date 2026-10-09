import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.config import get_settings
from app.models import CertificateStatus, JobStatus
from templates.certificate_layout import DEFAULT_EVENT_NAME, TITLE as DEFAULT_TITLE


class RecipientInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    recipients: list[RecipientInput] = Field(min_length=1)
    certificate_title: str = Field(default=DEFAULT_TITLE, min_length=1, max_length=100)
    event_name: str = Field(default=DEFAULT_EVENT_NAME, min_length=1, max_length=150)

    @model_validator(mode="after")
    def validate_batch(self) -> "JobCreateRequest":
        settings = get_settings()
        if len(self.recipients) > settings.max_batch_size:
            raise ValueError(
                f"Batch size {len(self.recipients)} exceeds the maximum of "
                f"{settings.max_batch_size} recipients per job"
            )
        emails = [str(recipient.email).lower() for recipient in self.recipients]
        if len(set(emails)) != len(emails):
            raise ValueError("Duplicate recipient emails are not allowed in a job")
        return self


class JobCreateResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    total_count: int


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    total_count: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    progress: float
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CertificateSummary(BaseModel):
    certificate_id: uuid.UUID
    recipient_name: str
    email: str
    status: CertificateStatus
    error_code: str | None
    generated_at: datetime | None


class CertificateListResponse(BaseModel):
    job_id: uuid.UUID
    items: list[CertificateSummary]
    total: int
    page: int
    page_size: int


class CertificateDetailResponse(CertificateSummary):
    job_id: uuid.UUID
    file_size_bytes: int | None
    created_at: datetime
    download_url: str
