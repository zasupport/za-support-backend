# Clients Module

Handles client onboarding from Formbricks form submissions. Stores client profiles,
device/environment setup, onboarding task checklists, and pre-visit check-ins.

## Endpoints

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/clients/intake/webhook` | Formbricks HMAC | Form 1 webhook receiver |
| POST | `/api/v1/clients/checkin/webhook` | Formbricks HMAC | Form 2 webhook receiver |
| POST | `/api/v1/clients/intake` | Agent token | Direct intake (testing/internal) |
| POST | `/api/v1/clients/checkin` | Agent token | Direct check-in |
| GET | `/api/v1/clients` | Agent token | List all clients (paginated) |
| GET | `/api/v1/clients/{client_id}` | Agent token | Client detail |
| GET | `/api/v1/clients/{client_id}/tasks` | Agent token | Onboarding task checklist |
| PATCH | `/api/v1/clients/{client_id}/tasks/{task_id}` | Agent token | Update task status |
| GET | `/api/v1/clients/{client_id}/checkins` | Agent token | Check-in history |

## Formbricks Setup

1. Create form at formbricks.com
2. Set webhook URL: `https://api.zasupport.com/api/v1/clients/intake/webhook`
3. Copy the webhook secret from Formbricks → set `FORMBRICKS_WEBHOOK_SECRET` on Render
4. Note the question IDs Formbricks assigns to each field
5. Update the field ID mappings in `service.py` → `map_formbricks_intake()`

## Events Emitted

- `client.created` — fired after successful intake, payload: `{client_id, email, has_business, urgency_level}`

## Tables

- `clients` — main client record
- `client_setup` — form-captured environment (ISP, cloud services, devices owned)
- `client_onboarding_tasks` — auto-populated checklist (11 tasks + business task if applicable)
- `client_checkins` — pre-visit check-in responses

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `FORMBRICKS_WEBHOOK_SECRET` | Recommended | HMAC signature verification for webhooks |
