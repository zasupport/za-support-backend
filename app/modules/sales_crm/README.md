# Sales CRM Module

## Purpose
CRM + upsell recommendation engine. Tracks every opportunity from first contact to closed.
Identifies Investec clients, recommends hardware/service upsells based on diagnostic findings,
and learns from outcomes over time.

## API Prefix
`/api/v1/sales/`

## Endpoints
| Method | Path | Description |
|---|---|---|
| POST | /contacts/ | Create CRM contact |
| GET | /contacts/ | List contacts (filter: segment, investec_only) |
| GET | /contacts/{id} | Get contact |
| POST | /contacts/{id}/flag-investec | Flag as Investec client |
| POST | /opportunities/ | Create opportunity |
| GET | /opportunities/ | List opportunities (filter: stage) |
| PATCH | /opportunities/{id}/stage | Update stage |
| POST | /activities/ | Log activity |
| GET | /activities/{opp_id} | List activities for opportunity |
| GET | /products/ | List upsell product catalog |
| POST | /products/ | Add product |
| POST | /recommend/{client_id} | Generate recommendations from diagnostic data |
| GET | /recommendations/{client_id} | List recommendations |
| PATCH | /recommendations/{id}/status | Update outcome (accepted/declined/deferred) |
| POST | /outcomes/ | Record sales outcome (feeds learning loop) |
| GET | /outcomes/stats | Conversion stats by segment + product |

## Tables
- `crm_contacts` — contacts with segment tag + Investec flag
- `crm_opportunities` — pipeline stages: lead → qualified → proposed → closed_won/lost
- `crm_activities` — call/visit/email/demo log per opportunity
- `upsell_products` — hardware catalog (seeded with 12 default products)
- `upsell_recommendations` — triggered recs per client from diagnostic data
- `sales_outcomes` — outcome store for ML learning loop

## Key Business Rules
- Batteries: NEVER warrantable (warranty_risk = 'never') — they always degrade
- RAM upgrades: Intel Macs only — M-series RAM is soldered
- SSD upgrades: Intel Macs only — M-series storage is soldered
- Investec scanner: daily Graph API email scan → auto-flag + trigger outreach within 24h
- Every opportunity requires scheduled in-person follow-up (non-negotiable sales rule)

## Migration
`migrations/019_sales_crm.sql` — includes product catalog seed (idempotent)
