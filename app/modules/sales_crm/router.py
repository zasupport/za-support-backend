from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.agent_auth import verify_agent_token
from app.modules.sales_crm import service
from app.modules.sales_crm.schemas import (
    ContactIn, ContactOut, OpportunityIn, OpportunityOut, OpportunityStageUpdate,
    ActivityIn, ActivityOut, ProductIn, ProductOut,
    RecommendationIn, RecommendationOut, RecommendationStatusUpdate,
    OutcomeIn, OutcomeOut,
)

router = APIRouter(prefix="/api/v1/sales", tags=["Sales CRM"])
auth = [Depends(verify_agent_token)]


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.post("/contacts/", response_model=ContactOut, dependencies=auth)
def create_contact(payload: ContactIn, db: Session = Depends(get_db)):
    return service.create_contact(db, payload)


@router.get("/contacts/", dependencies=auth)
def list_contacts(segment: Optional[str] = None, investec_only: bool = False,
                  page: int = 1, per_page: int = 50, db: Session = Depends(get_db)):
    return service.list_contacts(db, segment, investec_only, page, per_page)


@router.get("/contacts/{contact_id}", response_model=ContactOut, dependencies=auth)
def get_contact(contact_id: str, db: Session = Depends(get_db)):
    c = service.get_contact(db, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    return c


@router.post("/contacts/{contact_id}/flag-investec", dependencies=auth)
def flag_investec(contact_id: str, db: Session = Depends(get_db)):
    c = service.flag_investec(db, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    return {"status": "flagged", "contact_id": contact_id}


# ── Opportunities ─────────────────────────────────────────────────────────────

@router.post("/opportunities/", response_model=OpportunityOut, dependencies=auth)
def create_opportunity(payload: OpportunityIn, db: Session = Depends(get_db)):
    return service.create_opportunity(db, payload)


@router.get("/opportunities/", dependencies=auth)
def list_opportunities(stage: Optional[str] = None, page: int = 1, per_page: int = 50,
                       db: Session = Depends(get_db)):
    return service.list_opportunities(db, stage, page, per_page)


@router.patch("/opportunities/{opp_id}/stage", response_model=OpportunityOut, dependencies=auth)
def update_stage(opp_id: str, payload: OpportunityStageUpdate, db: Session = Depends(get_db)):
    opp = service.update_opportunity_stage(db, opp_id, payload)
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    return opp


# ── Activities ────────────────────────────────────────────────────────────────

@router.post("/activities/", response_model=ActivityOut, dependencies=auth)
def create_activity(payload: ActivityIn, db: Session = Depends(get_db)):
    return service.create_activity(db, payload)


@router.get("/activities/{opportunity_id}", dependencies=auth)
def list_activities(opportunity_id: str, db: Session = Depends(get_db)):
    return service.list_activities(db, opportunity_id)


# ── Product Catalog ───────────────────────────────────────────────────────────

@router.get("/products/", dependencies=auth)
def list_products(category: Optional[str] = None, db: Session = Depends(get_db)):
    service.seed_default_products(db)
    return service.list_products(db, category)


@router.post("/products/", response_model=ProductOut, dependencies=auth)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    return service.create_product(db, payload)


# ── Recommendations ───────────────────────────────────────────────────────────

@router.post("/recommend/{client_id}", dependencies=auth)
def generate_recommendations(client_id: str, snapshot_data: dict, db: Session = Depends(get_db)):
    recs = service.generate_recommendations(db, client_id, snapshot_data)
    return {"generated": len(recs), "recommendations": recs}


@router.get("/recommendations/{client_id}", dependencies=auth)
def list_recommendations(client_id: str, status: Optional[str] = None, db: Session = Depends(get_db)):
    return service.list_recommendations(db, client_id, status)


@router.patch("/recommendations/{rec_id}/status", dependencies=auth)
def update_recommendation_status(rec_id: str, payload: RecommendationStatusUpdate,
                                  db: Session = Depends(get_db)):
    rec = service.update_recommendation_status(db, rec_id, payload)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    return rec


# ── Outcomes ──────────────────────────────────────────────────────────────────

@router.post("/outcomes/", response_model=OutcomeOut, dependencies=auth)
def record_outcome(payload: OutcomeIn, db: Session = Depends(get_db)):
    return service.record_outcome(db, payload)


@router.get("/outcomes/stats", dependencies=auth)
def conversion_stats(db: Session = Depends(get_db)):
    return service.get_conversion_stats(db)
