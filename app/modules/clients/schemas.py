from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime


# ── Intake Form (Form 1) ──────────────────────────────────────────────────────

class ClientSetupIn(BaseModel):
    primary_computer:    Optional[str] = None
    form_factor:         Optional[str] = None
    computer_age:        Optional[str] = None
    computer_model_hint: Optional[str] = None
    has_external_backup: Optional[str] = None
    other_devices:       Optional[List[str]] = None
    isp:                 Optional[str] = None
    cloud_services:      Optional[List[str]] = None
    email_clients:       Optional[List[str]] = None
    has_google_account:  Optional[str] = None
    has_apple_id:        Optional[str] = None


class ClientIntakePayload(BaseModel):
    first_name:                     str
    last_name:                      str
    email:                          str
    phone:                          str
    preferred_contact:              str
    address:                        Optional[str] = None
    referral_source:                Optional[str] = None
    referred_by:                    Optional[str] = None
    urgency_level:                  Optional[str] = None
    concerns:                       Optional[List[str]] = None
    concerns_detail:                Optional[str] = None
    has_business:                   bool = False
    business_name:                  Optional[str] = None
    business_type:                  Optional[str] = None
    business_staff_count:           Optional[str] = None
    business_device_count:          Optional[str] = None
    business_health_check_interest: Optional[str] = None
    popia_consent:                  bool
    marketing_consent:              bool = False
    setup:                          Optional[ClientSetupIn] = None

    @field_validator("popia_consent")
    @classmethod
    def must_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("POPIA consent is required")
        return v


# ── Formbricks Webhook (Form 1) ───────────────────────────────────────────────
# Formbricks field IDs are configured in FORMBRICKS_FIELD_MAP env or defaults below.
# Update these IDs after creating the form in Formbricks.

class FormbricksResponse(BaseModel):
    """Raw Formbricks webhook payload — data.data contains field_id: value pairs."""
    class Config:
        extra = "allow"


# ── Check-In Form (Form 2) ────────────────────────────────────────────────────

class ClientCheckinPayload(BaseModel):
    client_id:              str
    working_well:           Optional[str] = None
    changes_since_last:     Optional[str] = None
    focus_today:            str
    issues_noted:           Optional[str] = None
    backup_drive_connected: Optional[str] = None
    pre_visit_notes:        Optional[str] = None


# ── Task Updates ──────────────────────────────────────────────────────────────

class TaskStatusUpdate(BaseModel):
    status: str
    notes:  Optional[str] = None


# ── Response Schemas ──────────────────────────────────────────────────────────

class ClientTaskOut(BaseModel):
    id:           int
    client_id:    str
    task:         str
    status:       str
    notes:        Optional[str]
    created_at:   datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class ClientOut(BaseModel):
    id:                             int
    client_id:                      str
    first_name:                     str
    last_name:                      str
    email:                          str
    phone:                          str
    preferred_contact:              str
    address:                        Optional[str]
    referral_source:                Optional[str]
    urgency_level:                  Optional[str]
    concerns:                       Optional[List[str]]
    has_business:                   bool
    business_name:                  Optional[str]
    business_health_check_interest: Optional[str]
    status:                         str
    created_at:                     datetime

    class Config:
        from_attributes = True


class ClientDetailOut(ClientOut):
    referred_by:                    Optional[str]
    concerns_detail:                Optional[str]
    business_type:                  Optional[str]
    business_staff_count:           Optional[str]
    business_device_count:          Optional[str]
    marketing_consent:              bool
    popia_consent:                  bool
    updated_at:                     datetime

    class Config:
        from_attributes = True


class CheckinOut(BaseModel):
    id:                     int
    client_id:              str
    working_well:           Optional[str]
    changes_since_last:     Optional[str]
    focus_today:            Optional[str]
    issues_noted:           Optional[str]
    backup_drive_connected: Optional[str]
    pre_visit_notes:        Optional[str]
    created_at:             datetime

    class Config:
        from_attributes = True
