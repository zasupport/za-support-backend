import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from app.modules.sales_crm.models import (
    CRMContact, CRMOpportunity, CRMActivity,
    UpsellProduct, UpsellRecommendation, SalesOutcome,
)
from app.modules.sales_crm.schemas import (
    ContactIn, OpportunityIn, OpportunityStageUpdate,
    ActivityIn, ProductIn, RecommendationIn, RecommendationStatusUpdate,
    OutcomeIn,
)

logger = logging.getLogger(__name__)


# ── Contacts ──────────────────────────────────────────────────────────────────

def create_contact(db: Session, payload: ContactIn) -> CRMContact:
    contact = CRMContact(**payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    logger.info(f"CRM contact: {contact.first_name} {contact.last_name} ({contact.segment})")
    return contact


def list_contacts(db: Session, segment: Optional[str] = None, investec_only: bool = False,
                  page: int = 1, per_page: int = 50) -> dict:
    q = db.query(CRMContact)
    if segment:
        q = q.filter(CRMContact.segment == segment)
    if investec_only:
        q = q.filter(CRMContact.investec_client == True)
    total = q.count()
    items = q.order_by(CRMContact.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": items, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_contact(db: Session, contact_id: str) -> Optional[CRMContact]:
    return db.query(CRMContact).filter(CRMContact.id == contact_id).first()


def flag_investec(db: Session, contact_id: str) -> Optional[CRMContact]:
    contact = get_contact(db, contact_id)
    if contact:
        contact.investec_client = True
        contact.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(contact)
    return contact


# ── Opportunities ─────────────────────────────────────────────────────────────

def create_opportunity(db: Session, payload: OpportunityIn) -> CRMOpportunity:
    opp = CRMOpportunity(**payload.model_dump())
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def list_opportunities(db: Session, stage: Optional[str] = None,
                       page: int = 1, per_page: int = 50) -> dict:
    q = db.query(CRMOpportunity)
    if stage:
        q = q.filter(CRMOpportunity.stage == stage)
    total = q.count()
    items = q.order_by(CRMOpportunity.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": items, "meta": {"page": page, "per_page": per_page, "total": total}}


def update_opportunity_stage(db: Session, opp_id: str, payload: OpportunityStageUpdate) -> Optional[CRMOpportunity]:
    opp = db.query(CRMOpportunity).filter(CRMOpportunity.id == opp_id).first()
    if not opp:
        return None
    opp.stage = payload.stage
    if payload.notes:
        opp.notes = payload.notes
    if payload.value_rand is not None:
        opp.value_rand = payload.value_rand
    if payload.stage in ("closed_won", "closed_lost"):
        opp.closed_at = datetime.now(timezone.utc)
    opp.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(opp)
    return opp


# ── Activities ────────────────────────────────────────────────────────────────

def create_activity(db: Session, payload: ActivityIn) -> CRMActivity:
    activity = CRMActivity(**payload.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def list_activities(db: Session, opportunity_id: str) -> List[CRMActivity]:
    return db.query(CRMActivity).filter(
        CRMActivity.opportunity_id == opportunity_id
    ).order_by(CRMActivity.created_at.desc()).all()


# ── Product Catalog ───────────────────────────────────────────────────────────

def list_products(db: Session, category: Optional[str] = None) -> List[UpsellProduct]:
    q = db.query(UpsellProduct).filter(UpsellProduct.active == True)
    if category:
        q = q.filter(UpsellProduct.category == category)
    return q.order_by(UpsellProduct.name).all()


def create_product(db: Session, payload: ProductIn) -> UpsellProduct:
    product = UpsellProduct(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def seed_default_products(db: Session):
    """Seed default hardware product catalog if empty."""
    if db.query(UpsellProduct).count() > 0:
        return

    defaults = [
        dict(name="Battery Replacement", category="repair",
             description="Replace degraded battery. NOT warrantable — batteries always degrade.",
             price_rand=1800, warranty_risk="high",
             applicable_segments=["individual", "family", "sme", "medical_practice"],
             diagnostic_triggers=["battery_health_pct < 80"]),
        dict(name="Screen Protector", category="accessory",
             description="Tempered glass. Near-zero failure rate. High attach on first visit.",
             price_rand=350, warranty_risk="low",
             applicable_segments=["individual", "family", "sme", "medical_practice"],
             diagnostic_triggers=[]),
        dict(name="Laptop Cover / Shell", category="accessory",
             description="Hard shell case. Cosmetic protection.", price_rand=450, warranty_risk="low",
             applicable_segments=["individual", "family", "sme", "medical_practice"],
             diagnostic_triggers=[]),
        dict(name="Extended Warranty — Keyboard", category="warranty",
             description="Extended cover on keyboard. Very low failure rate on M-series.",
             price_rand=800, warranty_risk="low",
             applicable_segments=["individual", "family", "sme", "medical_practice"],
             diagnostic_triggers=[]),
        dict(name="Extended Warranty — Trackpad", category="warranty",
             description="Extended cover on trackpad.", price_rand=600, warranty_risk="low",
             applicable_segments=["individual", "family", "sme", "medical_practice"],
             diagnostic_triggers=[]),
        dict(name="Extended Warranty — Screen", category="warranty",
             description="Extended cover on display. Screen repair R 6,000–15,000 out of warranty.",
             price_rand=1200, warranty_risk="low",
             applicable_segments=["sme", "medical_practice"],
             diagnostic_triggers=[]),
        dict(name="MagSafe Port Repair", category="repair",
             description="MagSafe connector repair. Moderate failure rate on older machines.",
             price_rand=1500, warranty_risk="medium",
             applicable_segments=["individual", "family", "sme", "medical_practice"],
             diagnostic_triggers=["magsafe_fault_detected"]),
        dict(name="SSD Upgrade (Intel Macs)", category="repair",
             description="SSD upgrade on eligible Intel Macs. NOT for M-series (storage is soldered).",
             price_rand=2500, warranty_risk="low",
             applicable_segments=["individual", "sme"],
             diagnostic_triggers=["storage_free_gb < 20"]),
        dict(name="RAM Upgrade (Intel Macs only)", category="repair",
             description="RAM upgrade for Intel Macs only. M-series RAM is soldered to SoC.",
             price_rand=1800, warranty_risk="low",
             applicable_segments=["individual", "sme"],
             diagnostic_triggers=["memory_pressure_high"]),
        dict(name="Logic Board Repair", category="repair",
             description="Selected logic board repairs. Assess per-device. Exclude liquid damage.",
             price_rand=4500, warranty_risk="medium",
             applicable_segments=["sme", "medical_practice"],
             diagnostic_triggers=["logic_board_fault_detected"]),
    ]

    for d in defaults:
        db.add(UpsellProduct(**d))
    db.commit()
    logger.info("Seeded default upsell product catalog (10 products)")


# ── Recommendations ───────────────────────────────────────────────────────────

def generate_recommendations(db: Session, client_id: str, snapshot_data: dict) -> List[UpsellRecommendation]:
    """Match diagnostic data against product triggers. Skip duplicates."""
    products = list_products(db)
    recs = []

    battery_pct = snapshot_data.get("battery_health_pct", 100)
    storage_free = snapshot_data.get("storage_free_gb", 100)
    memory_pressure = snapshot_data.get("memory_pressure", "normal")

    trigger_map = {
        "battery_health_pct < 80": battery_pct < 80,
        "storage_free_gb < 20": storage_free < 20,
        "memory_pressure_high": memory_pressure in ("warn", "critical"),
    }

    for product in products:
        if not any(trigger_map.get(t, False) for t in (product.diagnostic_triggers or [])):
            continue

        existing = db.query(UpsellRecommendation).filter(
            UpsellRecommendation.client_id == client_id,
            UpsellRecommendation.product_id == product.id,
            UpsellRecommendation.status == "pending",
        ).first()
        if existing:
            continue

        triggered = [t for t in (product.diagnostic_triggers or []) if trigger_map.get(t)]
        rec = UpsellRecommendation(
            client_id=client_id,
            product_id=product.id,
            product_name=product.name,
            trigger_field=triggered[0] if triggered else None,
            trigger_value=str(snapshot_data.get(triggered[0].split(" ")[0], "")) if triggered else None,
            roi_description=f"R {product.price_rand} investment vs significantly higher repair/replacement cost",
            rand_value=product.price_rand,
        )
        db.add(rec)
        recs.append(rec)

    db.commit()
    return recs


def list_recommendations(db: Session, client_id: str,
                         status: Optional[str] = None) -> List[UpsellRecommendation]:
    q = db.query(UpsellRecommendation).filter(UpsellRecommendation.client_id == client_id)
    if status:
        q = q.filter(UpsellRecommendation.status == status)
    return q.order_by(UpsellRecommendation.created_at.desc()).all()


def update_recommendation_status(db: Session, rec_id: str,
                                  payload: RecommendationStatusUpdate) -> Optional[UpsellRecommendation]:
    rec = db.query(UpsellRecommendation).filter(UpsellRecommendation.id == rec_id).first()
    if not rec:
        return None
    rec.status = payload.status
    rec.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rec)
    return rec


# ── Outcomes (learning store) ─────────────────────────────────────────────────

def record_outcome(db: Session, payload: OutcomeIn) -> SalesOutcome:
    outcome = SalesOutcome(**payload.model_dump())
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome


def get_conversion_stats(db: Session) -> dict:
    """Outcome breakdown by segment and product for dashboard."""
    from sqlalchemy import func
    rows = db.query(
        SalesOutcome.segment,
        SalesOutcome.product,
        SalesOutcome.outcome,
        func.count().label("count"),
        func.sum(SalesOutcome.revenue_rand).label("total_rand"),
    ).group_by(SalesOutcome.segment, SalesOutcome.product, SalesOutcome.outcome).all()

    return [
        {"segment": r.segment, "product": r.product, "outcome": r.outcome,
         "count": r.count, "total_rand": float(r.total_rand or 0)}
        for r in rows
    ]
