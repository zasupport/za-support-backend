"""
setup_formbricks.py — Automated Formbricks form creation for ZA Support.

Creates Form 1 (New Client Intake) and Form 2 (Pre-Visit Check-In) via the
Formbricks Management API, then patches service.py with the real question IDs
and prints the webhook secret to set on Render.

Usage:
    FORMBRICKS_API_KEY=your_key FORMBRICKS_ENVIRONMENT_ID=your_env_id python3 setup_formbricks.py

Get these from: formbricks.com → Settings → API Keys / Environment ID

After running:
    1. Copy FORMBRICKS_WEBHOOK_SECRET to Render env vars
    2. Redeploy (bash deploy.sh) so service.py picks up the patched IDs
"""
import os
import re
import sys
import json
import httpx

API_KEY = os.environ.get("FORMBRICKS_API_KEY", "")
ENV_ID  = os.environ.get("FORMBRICKS_ENVIRONMENT_ID", "")
BASE    = "https://app.formbricks.com/api/v1/management"
H11_URL = "https://api.zasupport.com"

if not API_KEY or not ENV_ID:
    print("ERROR: Set FORMBRICKS_API_KEY and FORMBRICKS_ENVIRONMENT_ID environment variables.")
    print("  Get them from: formbricks.com → Settings → API Keys / Environment ID")
    sys.exit(1)

headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}


def api(method: str, path: str, body: dict = None) -> dict:
    url = f"{BASE}/{path}"
    resp = httpx.request(method, url, headers=headers, json=body, timeout=30)
    if resp.status_code >= 400:
        print(f"API error {resp.status_code}: {resp.text}")
        sys.exit(1)
    return resp.json()


def create_survey(title: str, questions: list, thank_you: str) -> dict:
    return api("POST", f"environments/{ENV_ID}/surveys", {
        "name": title,
        "type": "link",
        "status": "inProgress",
        "questions": questions,
        "thankYouCard": {
            "enabled": True,
            "headline": {"default": "Thank you!"},
            "subheader": {"default": thank_you},
        },
        "closeOnDate": None,
        "autoClose": None,
    })


def create_webhook(survey_id: str, url: str, triggers: list) -> dict:
    return api("POST", f"environments/{ENV_ID}/webhooks", {
        "url": url,
        "triggers": triggers,
        "surveyIds": [survey_id],
    })


# ── FORM 1: NEW CLIENT INTAKE ─────────────────────────────────────────────────

print("\n=== Creating Form 1: New Client Intake ===")

intake_questions = [
    # Page 1: About You
    {"id": "q_first_name",        "type": "openText",    "headline": {"default": "First name"},           "required": True,  "inputType": "text"},
    {"id": "q_last_name",         "type": "openText",    "headline": {"default": "Last name"},            "required": True,  "inputType": "text"},
    {"id": "q_email",             "type": "openText",    "headline": {"default": "Email address"},        "required": True,  "inputType": "email"},
    {"id": "q_phone",             "type": "openText",    "headline": {"default": "WhatsApp / Mobile number"}, "required": True, "inputType": "phone"},
    {"id": "q_preferred_contact", "type": "singleSelect","headline": {"default": "Preferred contact method"}, "required": True,
     "choices": [{"id": "c1","label": {"default": "WhatsApp"}}, {"id": "c2","label": {"default": "Email"}}, {"id": "c3","label": {"default": "Phone call"}}]},
    {"id": "q_address",           "type": "openText",    "headline": {"default": "Home or office address (for site visits)"}, "required": True, "inputType": "text"},
    {"id": "q_referral_source",   "type": "singleSelect","headline": {"default": "How did you hear about ZA Support?"}, "required": True,
     "choices": [{"id": "r1","label": {"default": "Referred by a client"}}, {"id": "r2","label": {"default": "Google"}},
                 {"id": "r3","label": {"default": "Social media"}},         {"id": "r4","label": {"default": "Word of mouth"}},
                 {"id": "r5","label": {"default": "Other"}}]},
    {"id": "q_referred_by",       "type": "openText",    "headline": {"default": "Who referred you?"}, "required": False, "inputType": "text"},

    # Page 2: Your Devices
    {"id": "q_primary_computer",  "type": "singleSelect","headline": {"default": "What is your main computer?"}, "required": True,
     "choices": [{"id": "pc1","label": {"default": "Mac"}}, {"id": "pc2","label": {"default": "Windows PC"}},
                 {"id": "pc3","label": {"default": "Both"}}, {"id": "pc4","label": {"default": "Other"}}]},
    {"id": "q_form_factor",       "type": "singleSelect","headline": {"default": "Laptop, desktop, or both?"}, "required": True,
     "choices": [{"id": "ff1","label": {"default": "Laptop"}}, {"id": "ff2","label": {"default": "Desktop"}}, {"id": "ff3","label": {"default": "Both"}}]},
    {"id": "q_computer_age",      "type": "singleSelect","headline": {"default": "How old is your main computer?"}, "required": True,
     "choices": [{"id": "a1","label": {"default": "Less than 2 years"}}, {"id": "a2","label": {"default": "2–4 years"}},
                 {"id": "a3","label": {"default": "4–6 years"}},          {"id": "a4","label": {"default": "6+ years"}},
                 {"id": "a5","label": {"default": "Not sure"}}]},
    {"id": "q_computer_model",    "type": "openText",    "headline": {"default": "Mac model (if you know it — e.g. MacBook Pro, iMac)"}, "required": False, "inputType": "text"},
    {"id": "q_other_devices",     "type": "multipleChoiceMulti","headline": {"default": "Other devices you use"},  "required": False,
     "choices": [{"id": "d1","label": {"default": "iPhone"}}, {"id": "d2","label": {"default": "iPad"}},
                 {"id": "d3","label": {"default": "Android phone"}}, {"id": "d4","label": {"default": "Android tablet"}},
                 {"id": "d5","label": {"default": "Second Mac"}},    {"id": "d6","label": {"default": "Windows PC"}},
                 {"id": "d7","label": {"default": "None"}}]},
    {"id": "q_external_backup",   "type": "singleSelect","headline": {"default": "Do you use an external hard drive for backups?"}, "required": True,
     "choices": [{"id": "b1","label": {"default": "Yes"}}, {"id": "b2","label": {"default": "No"}}, {"id": "b3","label": {"default": "Not sure"}}]},

    # Page 3: Your Setup
    {"id": "q_isp",              "type": "singleSelect","headline": {"default": "Who is your internet provider?"}, "required": True,
     "choices": [{"id": "i1","label": {"default": "Openserve"}}, {"id": "i2","label": {"default": "Vumatel"}},
                 {"id": "i3","label": {"default": "Frogfoot"}},  {"id": "i4","label": {"default": "Octotel"}},
                 {"id": "i5","label": {"default": "MFN"}},       {"id": "i6","label": {"default": "LiquidHome"}},
                 {"id": "i7","label": {"default": "Telkom"}},    {"id": "i8","label": {"default": "Other"}},
                 {"id": "i9","label": {"default": "I don't know"}}]},
    {"id": "q_cloud_services",   "type": "multipleChoiceMulti","headline": {"default": "Do you use cloud storage?"}, "required": True,
     "choices": [{"id": "cl1","label": {"default": "Google Drive"}}, {"id": "cl2","label": {"default": "Dropbox"}},
                 {"id": "cl3","label": {"default": "iCloud"}},       {"id": "cl4","label": {"default": "OneDrive"}},
                 {"id": "cl5","label": {"default": "None"}},         {"id": "cl6","label": {"default": "Not sure"}}]},
    {"id": "q_email_clients",    "type": "multipleChoiceMulti","headline": {"default": "How do you access your email?"}, "required": True,
     "choices": [{"id": "em1","label": {"default": "Gmail (browser)"}}, {"id": "em2","label": {"default": "Apple Mail app"}},
                 {"id": "em3","label": {"default": "Outlook"}},          {"id": "em4","label": {"default": "Other"}}]},
    {"id": "q_google_account",   "type": "singleSelect","headline": {"default": "Do you have a Google account (Gmail)?"}, "required": True,
     "choices": [{"id": "g1","label": {"default": "Yes"}}, {"id": "g2","label": {"default": "No"}}, {"id": "g3","label": {"default": "Not sure"}}]},
    {"id": "q_apple_id",         "type": "singleSelect","headline": {"default": "Do you have an Apple ID (iCloud)?"}, "required": True,
     "choices": [{"id": "ap1","label": {"default": "Yes"}}, {"id": "ap2","label": {"default": "No"}}, {"id": "ap3","label": {"default": "Not sure"}}]},

    # Page 4: Concerns
    {"id": "q_concerns",         "type": "multipleChoiceMulti","headline": {"default": "What is your main concern right now?"}, "required": True,
     "choices": [{"id": "co1","label": {"default": "My computer is slow"}},
                 {"id": "co2","label": {"default": "I'm worried about security or viruses"}},
                 {"id": "co3","label": {"default": "Something isn't working properly"}},
                 {"id": "co4","label": {"default": "I want to make sure I'm properly backed up"}},
                 {"id": "co5","label": {"default": "I've had data loss before"}},
                 {"id": "co6","label": {"default": "I want someone to manage my tech properly"}},
                 {"id": "co7","label": {"default": "My email isn't working"}},
                 {"id": "co8","label": {"default": "I want a professional assessment"}},
                 {"id": "co9","label": {"default": "Other"}}]},
    {"id": "q_concerns_detail",  "type": "openText",    "headline": {"default": "Tell us more in your own words (optional)"}, "required": False, "inputType": "text"},
    {"id": "q_urgency",          "type": "singleSelect","headline": {"default": "How urgent is this?"}, "required": True,
     "choices": [{"id": "u1","label": {"default": "No rush, just getting sorted"}},
                 {"id": "u2","label": {"default": "Soon — it's affecting my work"}},
                 {"id": "u3","label": {"default": "Urgent — I need help now"}}]},

    # Page 5: Business (optional)
    {"id": "q_has_business",     "type": "singleSelect","headline": {"default": "Do you own or run a business?"}, "required": True,
     "choices": [{"id": "hb1","label": {"default": "Yes"}}, {"id": "hb2","label": {"default": "No"}}]},
    {"id": "q_business_name",    "type": "openText",    "headline": {"default": "Business name"},           "required": False, "inputType": "text"},
    {"id": "q_business_type",    "type": "openText",    "headline": {"default": "Type of business / industry (e.g. Medical practice, retail)"}, "required": False, "inputType": "text"},
    {"id": "q_staff_count",      "type": "singleSelect","headline": {"default": "Approximate number of staff"}, "required": False,
     "choices": [{"id": "s1","label": {"default": "Just me"}}, {"id": "s2","label": {"default": "2–5"}},
                 {"id": "s3","label": {"default": "6–15"}},    {"id": "s4","label": {"default": "16–50"}},
                 {"id": "s5","label": {"default": "50+"}}]},
    {"id": "q_device_count",     "type": "singleSelect","headline": {"default": "Computers in the business"}, "required": False,
     "choices": [{"id": "dv1","label": {"default": "1"}}, {"id": "dv2","label": {"default": "2–5"}},
                 {"id": "dv3","label": {"default": "6–10"}}, {"id": "dv4","label": {"default": "10+"}}]},
    {"id": "q_hc_interest",      "type": "singleSelect","headline": {"default": "Interested in a technology health check for your business?"}, "required": False,
     "choices": [{"id": "hci1","label": {"default": "Yes, definitely"}},
                 {"id": "hci2","label": {"default": "Maybe, tell me more"}},
                 {"id": "hci3","label": {"default": "Not right now"}}]},

    # Page 6: POPIA Consent
    {"id": "q_popia_consent",    "type": "consent",     "headline": {"default": "I consent to ZA Support (trading as Vizibiliti Intelligent Solutions (Pty) Ltd) storing and processing my personal information for the purpose of providing IT support services, in accordance with POPIA."}, "required": True, "label": {"default": "I agree"}},
    {"id": "q_age_confirm",      "type": "consent",     "headline": {"default": "I confirm I am 18 years or older."}, "required": True, "label": {"default": "Confirmed"}},
    {"id": "q_marketing_consent","type": "consent",     "headline": {"default": "I'm happy to receive service-related updates from ZA Support. (Optional)"}, "required": False, "label": {"default": "Yes, keep me updated"}},
]

intake_survey = create_survey(
    "ZA Support — New Client Intake",
    intake_questions,
    "Thank you. We'll be in touch shortly to arrange your first visit. Urgent? Call or WhatsApp: 064 529 5863.",
)
intake_id = intake_survey.get("data", {}).get("id") or intake_survey.get("id")
print(f"  ✓ Form 1 created: {intake_id}")

# ── FORM 2: PRE-VISIT CHECK-IN ────────────────────────────────────────────────

print("\n=== Creating Form 2: Pre-Visit Check-In ===")

checkin_questions = [
    {"id": "cq_client_id",       "type": "openText",    "headline": {"default": "Your client ID (we'll fill this in for you when we send the link)"}, "required": True,  "inputType": "text"},
    {"id": "cq_working_well",    "type": "openText",    "headline": {"default": "What's been working well since we last spoke?"}, "required": False, "inputType": "text"},
    {"id": "cq_changes",         "type": "openText",    "headline": {"default": "Has anything changed on your computer since our last visit? (new apps, updates, anything different)"}, "required": False, "inputType": "text"},
    {"id": "cq_focus_today",     "type": "openText",    "headline": {"default": "What would you most like us to focus on today?"}, "required": True,  "inputType": "text"},
    {"id": "cq_issues",          "type": "openText",    "headline": {"default": "Have you noticed any issues or unusual behaviour? (slowness, pop-ups, errors)"}, "required": False, "inputType": "text"},
    {"id": "cq_backup_connected","type": "singleSelect","headline": {"default": "Is your backup drive connected and accessible today?"}, "required": True,
     "choices": [{"id": "bc1","label": {"default": "Yes"}}, {"id": "bc2","label": {"default": "No"}}, {"id": "bc3","label": {"default": "I don't have one"}}]},
    {"id": "cq_notes",           "type": "openText",    "headline": {"default": "Anything else we should know before we arrive? (access codes, parking, etc.)"}, "required": False, "inputType": "text"},
]

checkin_survey = create_survey(
    "ZA Support — Pre-Visit Check-In",
    checkin_questions,
    "Thanks — we'll see you soon. If anything changes, let us know: 064 529 5863.",
)
checkin_id = checkin_survey.get("data", {}).get("id") or checkin_survey.get("id")
print(f"  ✓ Form 2 created: {checkin_id}")

# ── CREATE WEBHOOKS ───────────────────────────────────────────────────────────

print("\n=== Setting up webhooks ===")
intake_wh  = create_webhook(intake_id,  f"{H11_URL}/api/v1/clients/intake/webhook",  ["responseCreated", "responseFinished"])
checkin_wh = create_webhook(checkin_id, f"{H11_URL}/api/v1/clients/checkin/webhook", ["responseCreated", "responseFinished"])

intake_secret  = intake_wh.get("data", {}).get("secret") or intake_wh.get("secret", "")
checkin_secret = checkin_wh.get("data", {}).get("secret") or checkin_wh.get("secret", "")
webhook_secret = intake_secret or checkin_secret
print(f"  ✓ Intake webhook:  {H11_URL}/api/v1/clients/intake/webhook")
print(f"  ✓ Check-in webhook: {H11_URL}/api/v1/clients/checkin/webhook")

# ── PATCH service.py WITH REAL QUESTION IDs ───────────────────────────────────

print("\n=== Patching service.py with question IDs ===")

SERVICE_PATH = os.path.join(os.path.dirname(__file__), "app", "modules", "clients", "service.py")

id_map = {
    "FORMBRICKS_FIELD_FIRST_NAME":         "q_first_name",
    "FORMBRICKS_FIELD_LAST_NAME":          "q_last_name",
    "FORMBRICKS_FIELD_EMAIL":              "q_email",
    "FORMBRICKS_FIELD_PHONE":              "q_phone",
    "FORMBRICKS_FIELD_PREFERRED_CONTACT":  "q_preferred_contact",
    "FORMBRICKS_FIELD_ADDRESS":            "q_address",
    "FORMBRICKS_FIELD_REFERRAL_SOURCE":    "q_referral_source",
    "FORMBRICKS_FIELD_REFERRED_BY":        "q_referred_by",
    "FORMBRICKS_FIELD_PRIMARY_COMPUTER":   "q_primary_computer",
    "FORMBRICKS_FIELD_FORM_FACTOR":        "q_form_factor",
    "FORMBRICKS_FIELD_COMPUTER_AGE":       "q_computer_age",
    "FORMBRICKS_FIELD_COMPUTER_MODEL":     "q_computer_model",
    "FORMBRICKS_FIELD_OTHER_DEVICES":      "q_other_devices",
    "FORMBRICKS_FIELD_EXTERNAL_BACKUP":    "q_external_backup",
    "FORMBRICKS_FIELD_ISP":                "q_isp",
    "FORMBRICKS_FIELD_CLOUD_SERVICES":     "q_cloud_services",
    "FORMBRICKS_FIELD_EMAIL_CLIENTS":      "q_email_clients",
    "FORMBRICKS_FIELD_GOOGLE_ACCOUNT":     "q_google_account",
    "FORMBRICKS_FIELD_APPLE_ID":           "q_apple_id",
    "FORMBRICKS_FIELD_CONCERNS":           "q_concerns",
    "FORMBRICKS_FIELD_CONCERNS_DETAIL":    "q_concerns_detail",
    "FORMBRICKS_FIELD_URGENCY":            "q_urgency",
    "FORMBRICKS_FIELD_HAS_BUSINESS":       "q_has_business",
    "FORMBRICKS_FIELD_BUSINESS_NAME":      "q_business_name",
    "FORMBRICKS_FIELD_BUSINESS_TYPE":      "q_business_type",
    "FORMBRICKS_FIELD_STAFF_COUNT":        "q_staff_count",
    "FORMBRICKS_FIELD_DEVICE_COUNT":       "q_device_count",
    "FORMBRICKS_FIELD_HC_INTEREST":        "q_hc_interest",
    "FORMBRICKS_FIELD_POPIA_CONSENT":      "q_popia_consent",
    "FORMBRICKS_FIELD_MARKETING_CONSENT":  "q_marketing_consent",
    "FORMBRICKS_CHECKIN_CLIENT_ID":        "cq_client_id",
    "FORMBRICKS_CHECKIN_WORKING_WELL":     "cq_working_well",
    "FORMBRICKS_CHECKIN_CHANGES":          "cq_changes",
    "FORMBRICKS_CHECKIN_FOCUS":            "cq_focus_today",
    "FORMBRICKS_CHECKIN_ISSUES":           "cq_issues",
    "FORMBRICKS_CHECKIN_BACKUP":           "cq_backup_connected",
    "FORMBRICKS_CHECKIN_NOTES":            "cq_notes",
}

with open(SERVICE_PATH, "r") as f:
    src = f.read()

for placeholder, real_id in id_map.items():
    src = src.replace(f'"{placeholder}"', f'"{real_id}"')

with open(SERVICE_PATH, "w") as f:
    f.write(src)

print(f"  ✓ Patched {len(id_map)} field IDs in service.py")

# ── SUMMARY ───────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("SETUP COMPLETE")
print("="*60)
print(f"\nForm 1 (Intake):     https://app.formbricks.com/s/{intake_id}")
print(f"Form 2 (Check-In):   https://app.formbricks.com/s/{checkin_id}")
print(f"\nWebhook Secret: {webhook_secret or '(check Formbricks dashboard)'}")
print("\nNEXT STEPS:")
print(f"  1. Set on Render: FORMBRICKS_WEBHOOK_SECRET={webhook_secret or '<from Formbricks>'}")
print(f"  2. Deploy: bash deploy.sh")
print(f"  3. Share intake form link with new clients: https://app.formbricks.com/s/{intake_id}")
print(f"  4. Use check-in form before each visit: https://app.formbricks.com/s/{checkin_id}")
print("\nDone.")
