"""Maturity-assessment and consulting-inquiry endpoints.

The public `/api/demo/chat` endpoints used to live here too. They were removed
when the free hosted tier replaced the public demo — every signed-up user now
gets a "Demo: RetailFlow" warehouse auto-attached and uses the regular chat
flow.
"""

import html
import logging

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import RESEND_API_KEY, NOTIFICATION_EMAIL, RESEND_FROM_EMAIL
from app.core.dependencies import require_auth
from app.models.user import User
from app.models.demo import DataMaturityAssessment, ConsultingInquiry
from app.schemas.demo import (
    MaturityAssessmentRequest, MaturityAssessmentResponse,
    ConsultingInquiryRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["demo"])


@router.get("/api/maturity-assessment/status")
async def get_maturity_assessment_status(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Check if user has completed maturity assessment."""
    assessment = db.query(DataMaturityAssessment).filter(
        DataMaturityAssessment.user_id == user.id
    ).first()

    return {
        "completed": assessment is not None,
        "routing_result": assessment.routing_result if assessment else None,
    }


@router.post("/api/maturity-assessment", response_model=MaturityAssessmentResponse)
async def submit_maturity_assessment(
    request: MaturityAssessmentRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Submit data maturity assessment and get routing result."""
    if request.has_warehouse == "yes" and request.dbt_status == "mature":
        routing_result = "ready"
    elif request.has_warehouse == "yes" and request.dbt_status in ["basic", "none", "unknown"]:
        routing_result = "needs_dbt"
    else:
        routing_result = "needs_full_stack"

    assessment = DataMaturityAssessment(
        user_id=user.id,
        company_size=request.company_size,
        has_warehouse=request.has_warehouse,
        dbt_status=request.dbt_status,
        data_sources=request.data_sources,
        routing_result=routing_result,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    return MaturityAssessmentResponse(
        id=assessment.id,
        routing_result=routing_result,
    )


@router.post("/api/consulting-inquiry")
async def submit_consulting_inquiry(
    request: ConsultingInquiryRequest,
    db: Session = Depends(get_db),
):
    """Submit a consulting inquiry (no auth required)."""
    inquiry = ConsultingInquiry(
        name=request.name,
        email=request.email,
        company=request.company,
        message=request.message,
        maturity_assessment_id=request.maturity_assessment_id,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)

    if RESEND_API_KEY:
        # Escape every interpolated user input — the recipient is a human reading
        # this in a webmail client and `<img src=x onerror=...>` in the message
        # body would otherwise render as a real tag.
        safe_name = html.escape(request.name or "")
        safe_email = html.escape(request.email or "")
        safe_company = html.escape(request.company or "Not provided")
        safe_message = html.escape(request.message or "No message provided")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": RESEND_FROM_EMAIL,
                        "to": [NOTIFICATION_EMAIL],
                        "reply_to": request.email,
                        "subject": "Datachat Consulting Inquiry",
                        "html": f"""
                        <p><strong>Name:</strong> {safe_name}</p>
                        <p><strong>Email:</strong> {safe_email}</p>
                        <p><strong>Company:</strong> {safe_company}</p>
                        <p><strong>Message:</strong></p>
                        <p>{safe_message}</p>
                        """,
                    },
                    timeout=10.0,
                )
                if response.status_code != 200:
                    logger.error(
                        "Resend API error sending consulting inquiry: %s - %s",
                        response.status_code, response.text,
                    )
        except Exception:
            logger.exception("Failed to send consulting-inquiry email")

    return {"success": True, "id": inquiry.id}
