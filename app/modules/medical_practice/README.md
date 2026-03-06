# Medical Practice Module

## Purpose
Doctor/specialist-specific client profile and assessment module.
Highest-priority customer segment — non-technical, high income, regulated.

## Compliance
- HPCSA (Health Professions Council of South Africa)
- POPIA (Protection of Personal Information Act)
- National Health Act
All reports must reference applicable regulations.

## Common Software Stack
GoodX, Elixir, HealthBridge, Best Practice, Dragon Dictate, scribing tools (ChatGPT/Heidi)

## API Prefix
`/api/v1/medical/`

## Endpoints
| Method | Path | Description |
|---|---|---|
| POST | /practices/ | Create practice profile |
| GET | /practices/ | List all practices |
| GET | /practices/{id} | Get practice |
| GET | /practices/by-client/{client_id} | Lookup by client_id |
| POST | /assessments/ | Record assessment (scored 0-100 per domain) |
| GET | /assessments/{practice_id} | List assessments |
| GET | /compliance/{practice_id} | Latest compliance summary |

## Tables
- `medical_practices` — practice profile (type, HPCSA, doctor count, software stack)
- `medical_assessments` — scored assessment (network/device/software/backup/compliance) + grade A–F

## Assessment Domains
1. **Network** — router security, Wi-Fi segmentation, firewall
2. **Devices** — OS currency, encryption, patch status
3. **Software** — practice management software, licensing, compatibility
4. **Backup** — CCC + Time Machine + offsite (all three required for full score)
5. **Compliance** — POPIA data handling, HPCSA record keeping, encryption

## Grading
- A: 90–100 | B: 75–89 | C: 60–74 | D: 45–59 | F: 0–44

## Migration
`migrations/020_medical_practice.sql`
