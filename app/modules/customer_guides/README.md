# Customer Guides Module

Centralised knowledge base of how-to guides linked to client profiles.

## Purpose
- Courtney creates guides during/after client sessions
- Guides are emailed to clients with a feedback prompt
- "Not helpful" feedback triggers a Courtney follow-up task
- Shared knowledge base: guides reused across clients

## Endpoints
- GET  /api/v1/guides               List guides (search/filter)
- POST /api/v1/guides               Create guide (auth required)
- GET  /api/v1/guides/{id}          Get guide
- PATCH /api/v1/guides/{id}         Update guide (auth required)
- DELETE /api/v1/guides/{id}        Delete guide (auth required)
- POST /api/v1/guides/{id}/send     Email guide to client (auth required)
- POST /api/v1/guides/{id}/feedback Submit client feedback
- GET  /api/v1/guides/client/{id}   All guides sent to a client (auth required)
- POST /api/v1/guides/{id}/viewed   Mark guide as viewed

## Tables
- guides — knowledge base entries
- guide_client_links — sent history per client
- guide_feedback — helpful/not helpful per guide per client

## Storage
Guides are stored in the database (markdown). Client-facing copies are emailed.
Future: upload PDF versions to OneDrive via Microsoft Graph API.
