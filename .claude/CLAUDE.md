# INSTRUCTIONS.md — ZA Support Master Reference

**Version:** 3.2  
**Date:** 06/03/2026  
**Scope:** ALL Claude Code projects, ALL Claude.ai project chats  
**Owner:** Courtney Bentley, ZA Support

---

## ⚠️ CROSS-PROJECT SYNCHRONISATION RULE

This INSTRUCTIONS.md MUST be identical across every project:
- Health Check AI (backend platform)
- Health Check Scout (diagnostic engine)
- Workshop PKG (repair management)
- Forensic Software (forensic recovery)
- Any new ZA Support project

When updated, output: "INSTRUCTIONS.md updated — sync required across all projects."

---

## Company Identity

- **Company:** ZA Support (Vizibiliti Intelligent Solutions (Pty) Ltd)
- **CC Entity:** ZASUPPORT I.T. SUPPORT SYSTEMS CC
- **Tagline:** Practice IT. Perfected.
- **Address:** 1 Hyde Park Lane, Hyde Park, Johannesburg, 2196
- **Email:** admin@zasupport.com | courtney@zasupport.com | mary@zasupport.com
- **Phone:** 064 529 5863
- **Owner:** Courtney Bentley | ID: 9004175217085 | Cell: 079 053 9964
- **Rate:** R 899/hour (excl. VAT) | VAT: 436-026-0014
- **Banking:** FNB | Account: 62651791446 | Branch: 254605 | SWIFT: Firnzajj
- **Team:** Courtney (owner/technician), Mary (PA — admin, marketing, non-technical)

---

## Standards

- **Currency:** R with space (R 4,499)
- **Dates:** DD/MM/YYYY | Filenames: DD MM YYYY with spaces
- **Paper:** A4 | **Language:** UK English
- **Filenames:** ALWAYS spaces, never underscores or hyphens
- **Tone:** Measured, factual. Never "enterprise-grade", "best-in-class", "cutting-edge", "game-changer"
- **WhatsApp:** Numbered lists, blank line between items, no bullets/dashes
- **Terminal:** Code blocks with "Copy only this line:" prefix
- **Compliance:** POPIA, ECTA, Cybercrimes Act, Consumer Protection Act, HPCSA, National Health Act. NEVER reference HIPAA or US regulations.

---

## ⚠️ COMPETITIVE INTELLIGENCE & FEATURE MINING (CRITICAL — ALWAYS APPLY)

### Rule
**Whenever ANY third-party software is encountered on a client machine — whether during a service audit, diagnostic, repair, or assessment — ALWAYS analyse it for features, data collection methods, value propositions, and capabilities that ZA Support's own products (Health Check Scout, Health Check AI, CyberShield, Workshop PKG) should incorporate or compete against.**

### Why This Exists
On 06/03/2026, an ESET Cyber Security audit on Gillian Pearson's machine revealed 12 data collection gaps in Health Check Scout. ESET was collecting process ancestry, outbound network connections, DNS queries, crash telemetry, code signing verification, and firmware status — none of which Scout captured. Reverse-engineering ESET's approach produced an entire new diagnostic phase (Phase 19) and significant enhancements to Phase 13 and Phase 18.

Every third-party application on a client machine is a product built by a team that solved problems we may not have considered yet. Their approach, features, data collection, and user experience are free competitive intelligence.

### Trigger Conditions
This analysis activates when:
- A service audit identifies third-party software (any category)
- A client mentions software they use or rely on
- A diagnostic detects an application with significant resource usage
- A new software product is encountered during any ZA Support work
- A competitor product or service is mentioned in conversation

### Analysis Framework
For every third-party application encountered, answer these questions:

```
1. WHAT DOES IT DO?
   - Core function and value proposition
   - What problem does it solve for the user?
   - What data does it collect or generate?

2. HOW DOES IT WORK?
   - What system resources does it use? (processes, RAM, CPU, kexts, network)
   - Where does it store data? (local paths, cloud endpoints, databases)
   - What macOS APIs or frameworks does it hook into?
   - What permissions does it require? (TCC, root, kernel)

3. WHAT CAN WE LEARN?
   - What data is it collecting that Health Check Scout should also collect?
   - What features does it offer that Health Check AI should replicate or improve?
   - What is its pricing model and how does it compare to ZA Support products?
   - What is its weakness that ZA Support can exploit as a differentiator?

4. WHAT SHOULD WE BUILD?
   - Specific data collection gaps identified
   - Specific features to add to Scout/AI/CyberShield
   - New diagnostic sections or phases needed
   - New upsell or service opportunities identified

5. WHAT IS THE CLIENT IMPACT?
   - Resource cost of this software on the client's machine
   - Can ZA Support provide the same value with less resource impact?
   - Is there a CyberShield or Health Check AI upsell angle?
   - Can we replace this software entirely with our own solution?
```

### Output Format
When this analysis is performed, output a structured block:

```
═══ COMPETITIVE INTELLIGENCE: [Software Name] ═══
Source: [Client name / machine / audit date]

WHAT IT DOES:
[Description]

RESOURCE COST:
[Processes, RAM, CPU, kexts — quantified]

GAPS IDENTIFIED FOR ZA SUPPORT:
1. [Gap description] → Add to Phase [N]
2. [Gap description] → New module needed
3. [Gap description] → Enhances [product]

DIFFERENTIATOR OPPORTUNITY:
[How ZA Support can position against this product]

ACTION ITEMS:
1. [Specific code/feature to build]
2. [Specific data point to capture]
3. [Specific upsell to create]
═══════════════════════════════════════════════════
```

### Examples of High-Value Targets for Analysis
When encountered on client machines, these categories warrant deep analysis:

**Security software** (ESET, Norton, McAfee, Sophos, CrowdStrike, Malwarebytes):
What they scan, how they scan it, what telemetry they collect, what reports they generate, how they alert, what their resource cost is. Every feature they have that CyberShield or Scout doesn't is a gap.

**Backup software** (CCC, SuperDuper, Backblaze, Arq, ChronoSync):
What they back up, how they schedule, what verification they perform, what reports they generate, how they handle versioning. Every feature is potential Health Check AI integration.

**System utilities** (CleanMyMac, DaisyDisk, OnyX, TinkerTool, iStat Menus):
What metrics they display, what cleanup they perform, what maintenance they automate. These are direct competitors to Health Check Scout's storage and performance phases.

**Remote access** (TeamViewer, AnyDesk, LogMeIn, Chrome Remote Desktop):
How they authenticate, what access they provide, what logging they maintain. Relevant for CyberShield network monitoring and our own remote support capability.

**Productivity/office** (Microsoft 365, Google Workspace, Slack, Zoom, Teams):
Integration opportunities, licensing models, compliance features. Relevant for M365 Business Premium upsell and IT assessment value propositions.

**Monitoring/management** (Jamf, Mosyle, Kandji, Addigy, Munki):
MDM and endpoint management features. These are the enterprise competitors to Health Check AI. Their feature sets define what our platform should eventually match for SME clients.

**Medical/industry-specific** (Vericlaim, medical billing, practice management):
Workflow dependencies, data storage, integration requirements. Directly relevant to Dr Templates assessments and medical practice onboarding.

### Standing Instruction
This is not a one-time analysis. Every time software is encountered on a client machine, the competitive intelligence framework runs automatically. Findings accumulate in the INSTRUCTIONS.md under Key Learnings and feed into the Health Check Scout phase specifications. Over time, this builds a comprehensive understanding of every product category we compete with or complement.

---

## ⚠️ EMAIL FORMATTING RULE (CRITICAL — ALWAYS APPLY)

Equal spacing throughout. One blank line between every paragraph. No extra gaps between sections, before/after lists, or around sign-offs. Every paragraph break is identical.

```
CORRECT:
Hi Gillian, I hope you're well.

Following the audit we found several items. Below is a summary.

Services removed:
Adobe update services — three services running at startup.
CleanMyMac — background service consuming resources.
TechTool Pro — three services no longer in use.

Items needing your input:
ESET — is your licence current?
TeamViewer — did you install this?

Please let us know so we can complete the cleanup.

Kind regards,
Courtney Bentley
ZA Support
064 529 5863
```

INCORRECT: double blank lines between sections, blank lines between list items, extra spacing around greetings or sign-offs.

---

## Deployment — Health Check AI Backend (Render)

- **Service:** za-health-check-v11 | ID: srv-d6k5eu7tskes73bec2vg
- **Runtime:** Python 3, Free tier | **Deploy:** Manual
- **Repo:** zasupport/za-support-backend (main) | **Domain:** api.zasupport.com
- **Env vars:** AGENT_AUTH_TOKEN, AGENT_AUTH_TOKEN_OLD, ALLOWED_ORIGINS, FORENSICS_OUTPUT_DIR, HC_NOTIFY_EMAIL_FROM, HC_NOTIFY_EMAIL_TO, HC_NOTIFY_SMTP_HOST, HC_NOTIFY_SMTP_PORT, HC_NOTIFY_SMTP_USER

---

## ⚠️ HARDWARE VERIFICATION MANDATE (CRITICAL — ALWAYS APPLY)

**NEVER assume hardware specs. ALWAYS read from captured data.**
Source priority: Scout JSON → system_profiler → About This Mac screenshot → client record.
If unavailable: "Hardware specifications not confirmed — estimates pending verification."

Verification checklist before any analysis:
```
□ RAM confirmed from [source]? □ Storage confirmed?
□ Processor confirmed? □ macOS confirmed?
□ All percentages from confirmed values? □ ZA Support software checked?
```

---

## ⚠️ SOFTWARE ARCHITECTURE VERIFICATION (CRITICAL — ALWAYS APPLY)

**NEVER assume 32-bit/64-bit from version number. Verify with `file` command on binary.**
Catalina+ = 64-bit proof. 64-bit ≠ newer macOS compatible (framework dependencies).
Movie Magic 6.2: confirmed 64-bit, confirmed Ventura-incompatible (framework issue).

---

## ZA SUPPORT INSTALLED SOFTWARE — CHECK BEFORE FLAGGING

```
Macs Fan Control, CCC, Malwarebytes, iStat Menus, DriveDx,
coconutBattery, EtreCheck, AppCleaner, OnyX, TinkerTool, Homebrew, OCLP
```

Default: LEGITIMATE — POSSIBLE ZA SUPPORT INSTALLATION. Always ask before removal.
Macs Fan Control: ALWAYS ask "Did we install this?"

---

## Product Ecosystem

### Health Check Scout (19 phases)
1-11: Core diagnostics | 12: External Drive Analytics | 13: Software Compatibility (architecture verify, XProtect, crashes, auto-updates) | 14: Cloud & Sync | 15: Apple Services & Data Map | 16: Storage & Duplicates | 17: Client Profile & Opportunity | 18: Service & Security (18A-18Z + AV profiling + outbound + power/thermal) | 19: Deep Security Intelligence (process ancestry, code signing, DYLD, DNS, firmware)

### Health Check AI
PostgreSQL/TimescaleDB, FastAPI, Redis. api.zasupport.com.

### Other
Workshop PKG, CyberShield Medical (R 3,500/R 4,500), CyberShield Home (R 799/R 1,199/R 1,499), Dr Templates.

---

## Security Software Profiling

ESET on 16 GB machine: 446 MB (2.7%), ~2% CPU, 9 processes, 2 kexts, 6 crashes.
CyberShield: 0 MB, 0% CPU, network-level.
Upsell trigger: AV >200 MB or >1% CPU detected.

---

## Business Strategy

Repairs 50-65% margin (core). New machines 25-40% bundled (capture). Recurring 85% (grow).
50%+ clients buy machines elsewhere — address at every touchpoint.
Device lifecycle tracking. 3-month Health Check trial. M365 BP, UniFi, CyberShield, TM+CCC+iCloud.
Password vault for passwords WE set only. Never bank/financial.

---

## Client Engagement

Apple-style. Speed: report within 1 hour. Wow factor: quantified productivity from diagnostic data.
IT assessment: photos + voice + recording + Scout + network + red team → report 1 hour → shareable link → instant activation.

---

## Audiences

Medical (POPIA/HPCSA, doctor-language), SME (7+, Investec = auto-qualify), Individual (tip-box upsell), Family (CyberShield Home Intelligence).

---

## Investec Detection

Branch 580105, SWIFT IVESZAJJ. Scan courtney@/mary@ for POPs. Auto-elevate HIGH.

---

## Agents

Phase 1: Claude Projects + PostgreSQL. Phase 2: FastAPI + Claude API. Phase 3: Autonomous + MCP + Redis.
Scout, Client Intel, Medical, SME, Consumer/Family, Upsell, Marketing, Reports, Warranty, Site Visit, Verification.

---

## Warranty

GREEN (<1%): Trackpad, Speakers, MagSafe, Display, USB-C, WiFi, Touch ID, Camera
YELLOW (1-3%): Keyboard scissor, Fan, SSD
ORANGE (3-8%): Logic Board AS
RED (>10% NEVER): Battery, Cable, Butterfly KB

---

## Documents

Apple → Apple Experts letterhead. Non-Apple → IT Specialist. Medical → IT Specialist + Medical logo.
TEAL #27504D, GREEN #0FEA7A. ReportLab, A4, no orphaned headings. No brand names in client reports.

---

## Key Learnings

Movie Magic 6.2: 64-bit confirmed, Ventura-incompatible (framework). Architecture: never assume, use `file`. OCLP: disable auto-updates + LaunchDaemon, Ventura > Sonoma for legacy. A1278 keyboard riveted. T2/AS write blockers useless. `createinstallmedia` no `--applicationpath`. Use `MyVolume`. Service audits: check ZA Support list, Macs Fan Control ask first, TeamViewer flag, expired AV remove, enterprise kexts quarantine, _ZA_Quarantine folders. Emails: equal spacing, one blank line, no extra gaps. Competitive intelligence: analyse every third-party app for features we should build.

---

## Active Clients

### Gillian Pearson
```
MacBook Pro 13" Mid 2012, MacBookPro9,2, A1278, C1MKNNLCDTY3
2.5 GHz i5, 16 GB DDR3, Intel HD 4000, Catalina 10.15.8
Movie Magic 6.2: 64-BIT, cannot go Ventura (framework).
ESET: 446 MB (2.7%), 9 proc, 6 crashes. TeamViewer: SUSPICIOUS.
Macs Fan Control: CHECK ZA. CCC: working.
Seagate 2TB + 3TB HDDs. Norman: paint store, SME lead.
Job: clean, keyboard, diagnostic, CCC (done), audit (R 449.50), email 8 GB.
```

Others: Dr Evan Shoul, Neil Brandt, Roger Naidoo, Kim Ayoub, Steve Pillinger, Richard Meade, Linda Forrest, Dr Anton Meyberg, Charles Chemel, Zoë Jewell.

---

## Priority

1. Scout 1-19 (dev) | 2. PostgreSQL (done) | 3. Dr Templates (P1 done) | 4. Claude Projects (ready) | 5. FastAPI upload (next) | 6-16. CRM, assessment, upsell, audit, reports, marketing, contracts, portal, Gmail MCP, orchestrator, agents.
