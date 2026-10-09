import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CertificateStatus
from app.schemas.job import (
    CertificateListResponse,
    CertificateSummary,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
)
from app.services import job_service
from app.workers import job_processor

router = APIRouter(tags=["jobs"])


@router.post(
    "/jobs",
    response_model=JobCreateResponse,
    status_code=202,
    summary="Create a bulk certificate generation job",
)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobCreateResponse:
    job = job_service.create_job(
        db,
        payload.recipients,
        certificate_title=payload.certificate_title,
        event_name=payload.event_name,
    )
    background_tasks.add_task(job_processor.process_job, job.id)
    return JobCreateResponse(
        job_id=job.id, status=job.status, total_count=job.total_count
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, summary="Get job status and progress")
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        total_count=job.total_count,
        processed_count=job.processed_count,
        succeeded_count=job.succeeded_count,
        failed_count=job.failed_count,
        progress=job_service.job_progress(job),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get(
    "/jobs/{job_id}/certificates",
    response_model=CertificateListResponse,
    summary="List certificates for a job",
)
def list_job_certificates(
    job_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: CertificateStatus | None = None,
    db: Session = Depends(get_db),
) -> CertificateListResponse:
    if job_service.get_job(db, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    items, total = job_service.list_certificates(
        db, job_id, page=page, page_size=page_size, status=status
    )
    return CertificateListResponse(
        job_id=job_id,
        items=[
            CertificateSummary(
                certificate_id=certificate.id,
                recipient_name=certificate.recipient_name,
                email=certificate.email,
                status=certificate.status,
                error_code=certificate.error_code,
                generated_at=certificate.generated_at,
            )
            for certificate in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
