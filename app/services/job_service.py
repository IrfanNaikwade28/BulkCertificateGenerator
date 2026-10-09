"""Business logic for generation jobs and certificate records.

All functions here take an explicit session; no HTTP concerns and no PDF work.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas.job import RecipientInput


def create_job(
    db: Session,
    recipients: Sequence[RecipientInput],
    *,
    certificate_title: str,
    event_name: str,
) -> Job:
    """Persist a job plus one pending certificate row per recipient.

    Runs as a single short transaction containing only inserts (no PDF work).
    """
    job = Job(
        total_count=len(recipients),
        status=JobStatus.PENDING,
        certificate_title=certificate_title,
        event_name=event_name,
    )
    db.add(job)
    db.flush()
    db.add_all(
        Certificate(
            job_id=job.id,
            recipient_name=recipient.name,
            email=str(recipient.email).lower(),
            status=CertificateStatus.PENDING,
        )
        for recipient in recipients
    )
    db.commit()
    return job


def get_job(db: Session, job_id: uuid.UUID) -> Job | None:
    return db.get(Job, job_id)


def get_certificate(db: Session, certificate_id: uuid.UUID) -> Certificate | None:
    return db.get(Certificate, certificate_id)


def list_certificates(
    db: Session,
    job_id: uuid.UUID,
    *,
    page: int,
    page_size: int,
    status: CertificateStatus | None = None,
) -> tuple[list[Certificate], int]:
    filters = [Certificate.job_id == job_id]
    if status is not None:
        filters.append(Certificate.status == status)

    total = db.scalar(
        select(func.count()).select_from(Certificate).where(*filters)
    ) or 0
    items = list(
        db.scalars(
            select(Certificate)
            .where(*filters)
            .order_by(Certificate.created_at, Certificate.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def job_progress(job: Job) -> float:
    """Fraction of recipients processed (succeeded or failed), from 0.0 to 1.0."""
    if job.total_count == 0:
        return 0.0
    return job.processed_count / job.total_count


def final_job_status(*, total_count: int, failed_count: int) -> JobStatus:
    if failed_count > 0:
        return JobStatus.COMPLETED_WITH_ERRORS
    return JobStatus.COMPLETED
