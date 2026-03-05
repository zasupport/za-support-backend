import re
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.modules.clients.models import Client, ClientSetup, ClientOnboardingTask, ClientCheckin
from app.modules.clients.schemas import ClientIntakePayload, ClientCheckinPayload, TaskStatusUpdate

logger = logging.getLogger(__name__)

# Standard onboarding tasks created for every new client
_BASE_TASKS = [
    "Run Health Check Scout diagnostic on client machine",
    "Generate Health Check Assessment report",
    "Deliver report to client and walk through findings",
    "Set up client in ZA Vault (password manager)",
    "Verify backup setup: CCC (bootable clone) + Time Machine (versioned history)",
    "Complete cloud storage audit (Google Drive, Dropbox, iCloud — gaps and overlaps)",
    "Audit Google account setup — what's backing up, what's missing",
    "Audit Apple services — iCloud Drive, Photos, Keychain, Find My",
    "Check other devices in household — iPhone, iPad, second Mac (scope for SLA)",
    "Pitch SLA — frame as staying ahead of problems, not reacting to them",
    "Ecosystem map — document household and business connections",
]

_BUSINESS_TASK = "Offer SME Health Check for client's business — schedule separate assessment"


def _generate_client_id(first: str, last: str, db: Session) -> str:
    """Generate slug like 'gillian-pearson', handling collisions with suffix."""
    def slugify(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")

    base = f"{slugify(first)}-{slugify(last)}"
    candidate = base
    suffix = 1
    while db.query(Client).filter(Client.client_id == candidate).first():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def create_client(db: Session, payload: ClientIntakePayload) -> Client:
    # Check for duplicate email
    existing = db.query(Client).filter(Client.email == payload.email).first()
    if existing:
        logger.warning(f"Intake ignored — email already registered: {payload.email}")
        return existing

    client_id = _generate_client_id(payload.first_name, payload.last_name, db)

    client = Client(
        client_id=client_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        preferred_contact=payload.preferred_contact,
        address=payload.address,
        referral_source=payload.referral_source,
        referred_by=payload.referred_by,
        urgency_level=payload.urgency_level,
        concerns=payload.concerns or [],
        concerns_detail=payload.concerns_detail,
        has_business=payload.has_business,
        business_name=payload.business_name,
        business_type=payload.business_type,
        business_staff_count=payload.business_staff_count,
        business_device_count=payload.business_device_count,
        business_health_check_interest=payload.business_health_check_interest,
        popia_consent=payload.popia_consent,
        marketing_consent=payload.marketing_consent,
        status="new",
    )
    db.add(client)
    db.flush()  # get client.id before referencing client_id

    # Save device/environment setup if provided
    if payload.setup:
        s = payload.setup
        setup = ClientSetup(
            client_id=client_id,
            primary_computer=s.primary_computer,
            form_factor=s.form_factor,
            computer_age=s.computer_age,
            computer_model_hint=s.computer_model_hint,
            has_external_backup=s.has_external_backup,
            other_devices=s.other_devices or [],
            isp=s.isp,
            cloud_services=s.cloud_services or [],
            email_clients=s.email_clients or [],
            has_google_account=s.has_google_account,
            has_apple_id=s.has_apple_id,
        )
        db.add(setup)

    # Auto-populate standard onboarding checklist
    tasks = list(_BASE_TASKS)
    if payload.has_business:
        tasks.append(_BUSINESS_TASK)

    for task_text in tasks:
        db.add(ClientOnboardingTask(client_id=client_id, task=task_text))

    db.commit()
    db.refresh(client)
    logger.info(f"New client created: {client_id} ({payload.email})")
    return client


def get_client(db: Session, client_id: str) -> Optional[Client]:
    return db.query(Client).filter(Client.client_id == client_id).first()


def list_clients(db: Session, status: Optional[str] = None, search: Optional[str] = None, page: int = 1, per_page: int = 50) -> dict:
    q = db.query(Client)
    if status:
        q = q.filter(Client.status == status)
    if search:
        like = f"%{search}%"
        from sqlalchemy import or_
        q = q.filter(or_(
            Client.first_name.ilike(like),
            Client.last_name.ilike(like),
            Client.email.ilike(like),
            Client.client_id.ilike(like),
        ))
    total = q.count()
    items = q.order_by(Client.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": items, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_tasks(db: Session, client_id: str) -> List[ClientOnboardingTask]:
    return (
        db.query(ClientOnboardingTask)
        .filter(ClientOnboardingTask.client_id == client_id)
        .order_by(ClientOnboardingTask.id)
        .all()
    )


def update_task(db: Session, task_id: int, update: TaskStatusUpdate) -> Optional[ClientOnboardingTask]:
    task = db.query(ClientOnboardingTask).filter(ClientOnboardingTask.id == task_id).first()
    if not task:
        return None
    task.status = update.status
    if update.notes:
        task.notes = update.notes
    if update.status == "completed" and not task.completed_at:
        task.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    return task


def create_checkin(db: Session, payload: ClientCheckinPayload) -> ClientCheckin:
    checkin = ClientCheckin(
        client_id=payload.client_id,
        working_well=payload.working_well,
        changes_since_last=payload.changes_since_last,
        focus_today=payload.focus_today,
        issues_noted=payload.issues_noted,
        backup_drive_connected=payload.backup_drive_connected,
        pre_visit_notes=payload.pre_visit_notes,
    )
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    logger.info(f"Pre-visit check-in received for client: {payload.client_id}")
    return checkin


def get_checkins(db: Session, client_id: str) -> List[ClientCheckin]:
    return (
        db.query(ClientCheckin)
        .filter(ClientCheckin.client_id == client_id)
        .order_by(ClientCheckin.created_at.desc())
        .all()
    )


def get_site_visit_brief(db: Session, client_id: str) -> Optional[Dict[str, Any]]:
    """
    Assemble a pre-visit context brief for Courtney:
    client record, devices + latest snapshot per device,
    open onboarding tasks, latest check-in, open workshop jobs.
    """
    client = get_client(db, client_id)
    if not client:
        return None

    # Devices registered for this client
    devices_rows = db.execute(
        text("SELECT * FROM client_devices WHERE client_id = :cid ORDER BY last_seen DESC"),
        {"cid": client_id},
    ).fetchall()

    devices = []
    for dev in devices_rows:
        d = dict(dev._mapping)
        # Latest snapshot for this device
        snap_row = db.execute(
            text("""
                SELECT id, scan_date, risk_score, risk_level, recommendation_count,
                       version, reason
                FROM diagnostic_snapshots
                WHERE serial = :serial
                ORDER BY scan_date DESC LIMIT 1
            """),
            {"serial": d["serial"]},
        ).fetchone()
        d["latest_snapshot"] = dict(snap_row._mapping) if snap_row else None
        devices.append(d)

    # Open onboarding tasks
    all_tasks = get_tasks(db, client_id)
    open_tasks = [t for t in all_tasks if t.status != "completed"]
    completed_tasks = [t for t in all_tasks if t.status == "completed"]

    # Latest check-in
    checkins = get_checkins(db, client_id)
    latest_checkin = checkins[0] if checkins else None

    # Open workshop jobs (not done/cancelled)
    jobs_rows = db.execute(
        text("""
            SELECT job_ref, title, status, priority, source, serial, created_at, scheduled_date
            FROM workshop_jobs
            WHERE client_id = :cid AND status NOT IN ('done', 'cancelled')
            ORDER BY created_at DESC
        """),
        {"cid": client_id},
    ).fetchall()
    open_jobs = [dict(r._mapping) for r in jobs_rows]

    return {
        "client": client,
        "devices": devices,
        "open_tasks": open_tasks,
        "completed_task_count": len(completed_tasks),
        "latest_checkin": latest_checkin,
        "open_workshop_jobs": open_jobs,
    }


def map_formbricks_intake(raw: dict) -> Optional[ClientIntakePayload]:
    """
    Map a raw Formbricks webhook payload to ClientIntakePayload.
    The `data.data` object contains question_id: answer pairs.
    Update FORMBRICKS_INTAKE_FIELD_IDS in this function once form is created in Formbricks
    and the question IDs are known.
    """
    try:
        fields = raw.get("data", {}).get("data", {})

        # TODO: Replace these placeholder keys with actual Formbricks question IDs
        # after creating the form. Keys below are the question IDs Formbricks assigns.
        # Example: if Formbricks gives first_name question ID "q1abc123", use that.
        # For now, also accepts direct field names (for testing without Formbricks).
        def get(field_id: str, fallback: str) -> any:
            return fields.get(field_id) or fields.get(fallback)

        first_name = get("FORMBRICKS_FIELD_FIRST_NAME", "first_name")
        last_name  = get("FORMBRICKS_FIELD_LAST_NAME",  "last_name")
        email      = get("FORMBRICKS_FIELD_EMAIL",       "email")
        phone      = get("FORMBRICKS_FIELD_PHONE",       "phone")

        if not all([first_name, last_name, email, phone]):
            logger.error(f"Formbricks intake missing required fields. Keys received: {list(fields.keys())}")
            return None

        setup_data = {
            "primary_computer":    get("FORMBRICKS_FIELD_PRIMARY_COMPUTER",    "primary_computer"),
            "form_factor":         get("FORMBRICKS_FIELD_FORM_FACTOR",         "form_factor"),
            "computer_age":        get("FORMBRICKS_FIELD_COMPUTER_AGE",        "computer_age"),
            "computer_model_hint": get("FORMBRICKS_FIELD_COMPUTER_MODEL",      "computer_model_hint"),
            "has_external_backup": get("FORMBRICKS_FIELD_EXTERNAL_BACKUP",     "has_external_backup"),
            "other_devices":       get("FORMBRICKS_FIELD_OTHER_DEVICES",       "other_devices"),
            "isp":                 get("FORMBRICKS_FIELD_ISP",                 "isp"),
            "cloud_services":      get("FORMBRICKS_FIELD_CLOUD_SERVICES",      "cloud_services"),
            "email_clients":       get("FORMBRICKS_FIELD_EMAIL_CLIENTS",       "email_clients"),
            "has_google_account":  get("FORMBRICKS_FIELD_GOOGLE_ACCOUNT",      "has_google_account"),
            "has_apple_id":        get("FORMBRICKS_FIELD_APPLE_ID",            "has_apple_id"),
        }

        concerns_raw = get("FORMBRICKS_FIELD_CONCERNS", "concerns")
        concerns = concerns_raw if isinstance(concerns_raw, list) else ([concerns_raw] if concerns_raw else [])

        has_business_raw = get("FORMBRICKS_FIELD_HAS_BUSINESS", "has_business")
        has_business = str(has_business_raw).lower() in ("yes", "true", "1") if has_business_raw else False

        popia_raw = get("FORMBRICKS_FIELD_POPIA_CONSENT", "popia_consent")
        popia = str(popia_raw).lower() in ("yes", "true", "1", "accepted") if popia_raw else False

        marketing_raw = get("FORMBRICKS_FIELD_MARKETING_CONSENT", "marketing_consent")
        marketing = str(marketing_raw).lower() in ("yes", "true", "1", "accepted") if marketing_raw else False

        from app.modules.clients.schemas import ClientSetupIn
        return ClientIntakePayload(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            preferred_contact=get("FORMBRICKS_FIELD_PREFERRED_CONTACT", "preferred_contact") or "email",
            address=get("FORMBRICKS_FIELD_ADDRESS", "address"),
            referral_source=get("FORMBRICKS_FIELD_REFERRAL_SOURCE", "referral_source"),
            referred_by=get("FORMBRICKS_FIELD_REFERRED_BY", "referred_by"),
            urgency_level=get("FORMBRICKS_FIELD_URGENCY", "urgency_level"),
            concerns=concerns,
            concerns_detail=get("FORMBRICKS_FIELD_CONCERNS_DETAIL", "concerns_detail"),
            has_business=has_business,
            business_name=get("FORMBRICKS_FIELD_BUSINESS_NAME", "business_name"),
            business_type=get("FORMBRICKS_FIELD_BUSINESS_TYPE", "business_type"),
            business_staff_count=get("FORMBRICKS_FIELD_STAFF_COUNT", "business_staff_count"),
            business_device_count=get("FORMBRICKS_FIELD_DEVICE_COUNT", "business_device_count"),
            business_health_check_interest=get("FORMBRICKS_FIELD_HC_INTEREST", "business_health_check_interest"),
            popia_consent=popia,
            marketing_consent=marketing,
            setup=ClientSetupIn(**{k: v for k, v in setup_data.items() if v is not None}),
        )
    except Exception as e:
        logger.error(f"Failed to map Formbricks intake payload: {e}", exc_info=True)
        return None


def map_formbricks_checkin(raw: dict) -> Optional[ClientCheckinPayload]:
    """Map Formbricks pre-visit check-in webhook to ClientCheckinPayload."""
    try:
        fields = raw.get("data", {}).get("data", {})

        def get(field_id: str, fallback: str) -> any:
            return fields.get(field_id) or fields.get(fallback)

        client_id  = get("FORMBRICKS_CHECKIN_CLIENT_ID",  "client_id")
        focus      = get("FORMBRICKS_CHECKIN_FOCUS",       "focus_today")

        if not client_id or not focus:
            logger.error(f"Formbricks check-in missing required fields. Keys: {list(fields.keys())}")
            return None

        return ClientCheckinPayload(
            client_id=client_id,
            working_well=get("FORMBRICKS_CHECKIN_WORKING_WELL",  "working_well"),
            changes_since_last=get("FORMBRICKS_CHECKIN_CHANGES", "changes_since_last"),
            focus_today=focus,
            issues_noted=get("FORMBRICKS_CHECKIN_ISSUES",        "issues_noted"),
            backup_drive_connected=get("FORMBRICKS_CHECKIN_BACKUP", "backup_drive_connected"),
            pre_visit_notes=get("FORMBRICKS_CHECKIN_NOTES",      "pre_visit_notes"),
        )
    except Exception as e:
        logger.error(f"Failed to map Formbricks check-in payload: {e}", exc_info=True)
        return None
