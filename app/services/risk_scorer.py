"""
Risk Scorer — daily job that back-fills risk_score for diagnostic snapshots
where risk_score is NULL. Derives score from risk_level + recommendation_count.

Risk score scale: 1–10 (10 = most dangerous)
"""
import logging
from sqlalchemy import text
from app.core.database import get_session_factory

logger = logging.getLogger(__name__)

# risk_level → base score
_LEVEL_BASE = {
    "CRITICAL": 8,
    "HIGH":     6,
    "MODERATE": 3,
    "LOW":      1,
}

# Max additional points from recommendation_count
_REC_SCALE = [
    (10, 2),   # >= 10 recs → +2
    (5,  1),   # >= 5  recs → +1
]


def _compute_score(risk_level: str | None, rec_count: int) -> int | None:
    if not risk_level:
        return None
    base = _LEVEL_BASE.get((risk_level or "").upper())
    if base is None:
        return None
    bonus = 0
    for threshold, pts in _REC_SCALE:
        if (rec_count or 0) >= threshold:
            bonus = pts
            break
    return min(10, base + bonus)


def run_risk_score_computation():
    """
    Scheduled daily. Finds snapshots with NULL risk_score and computes it
    from risk_level + recommendation_count, then writes it back.
    """
    db = get_session_factory()()
    try:
        rows = db.execute(
            text("""
            SELECT id, risk_level, recommendation_count
            FROM   diagnostic_snapshots
            WHERE  risk_score IS NULL
              AND  risk_level IS NOT NULL
            ORDER  BY scan_date DESC
            LIMIT  500
            """)
        ).fetchall()

        if not rows:
            logger.info("[RiskScorer] All snapshots have risk_score — nothing to do.")
            return

        updated = 0
        for row in rows:
            score = _compute_score(row.risk_level, row.recommendation_count or 0)
            if score is None:
                continue
            db.execute(
                text("UPDATE diagnostic_snapshots SET risk_score = :score WHERE id = :id"),
                {"score": score, "id": row.id},
            )
            updated += 1

        db.commit()
        logger.info(f"[RiskScorer] Updated risk_score on {updated}/{len(rows)} snapshots.")

    except Exception as exc:
        logger.error(f"[RiskScorer] Job failed: {exc}", exc_info=True)
        db.rollback()
    finally:
        db.close()
