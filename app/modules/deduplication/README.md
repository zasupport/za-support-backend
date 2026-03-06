# Deduplication Module

## Purpose
Track and report on duplicate file findings (especially photos) per client.
Primary use: internal tooling + high-level client reporting.
NEVER auto-deletes — always generates review list for explicit approval.

## Open Source Engine
`rmlint` or `jdupes` — run locally during site visits or remotely via Scout.
Results POSTed to this API.

## API Prefix
`/api/v1/dedup/`

## Endpoints
| Method | Path | Description |
|---|---|---|
| POST | /scans/ | Record scan result |
| GET | /scans/{client_id} | List scans for client |
| GET | /scans/{scan_id}/items | List duplicate item groups |
| POST | /scans/{scan_id}/items | Bulk add items |
| POST | /scans/{scan_id}/complete | Mark scan complete |
| PATCH | /items/{id}/action | Set action: keep/delete/review |
| GET | /summary/{client_id} | Plain-English summary for client report |

## Tables
- `dedup_scans` — scan record per client (totals: files, sets, recoverable_gb)
- `dedup_items` — individual duplicate groups (hash, paths, file_type, action)

## Client Report Integration
`GET /summary/{client_id}` returns `client_facing_summary` — plain English text
ready to drop into IT assessment report Section: "Storage & Files".
Example: "Your Mac has 4.2 GB of duplicate files that can be safely removed..."

## Scout Integration
Future: `duplicate_gb_recoverable` field added to diagnostic JSON output.
Dashboard metric: shows recoverable space as a selling point.

## Migration
`migrations/021_deduplication.sql`
