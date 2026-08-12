# Automated Job Application Engine — Requirements & Architecture Plan

**Owner:** Sivasuthakaran Sanjeev
**Purpose:** Automatically discover, score, and apply to Junior Developer / Associate Developer / High-paid Internship roles, with instant Telegram notifications, with the goal of landing 2–3 interview offers within a 5–10 day sprint.
**Build target:** Antigravity (agentic build), Python backend, Convex as DB, OpenRouter for LLM calls.

---

## 1. Goal & Success Criteria

- **Primary goal:** 2–3 interview invitations within 5–10 days of the engine running.
- **Secondary goal:** A reusable engine that keeps running after the sprint, so this isn't a one-off.
- **Target roles:** Junior Developer, Associate Developer, high-paid Internships.
- **Target scope:** Remote-first, globally-hiring companies. (Sri Lanka has no structured/legal job-data source — see Section 4.)
- **Definition of done for MVP:** engine runs unattended, sources jobs daily, scores them, auto-generates a tailored cover letter, auto-submits via Playwright on supported ATS platforms, logs everything to Convex, and pings Telegram per application + daily summary.

---

## 2. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.11+ | Core engine language |
| Backend / Database | Convex | Jobs, applications, resume versions, logs — real-time sync, hosted |
| LLM Provider | OpenRouter | Model-agnostic; swap between models for scoring vs. cover-letter generation |
| Browser automation | Playwright (Python) | Auto-fills and submits Greenhouse/Lever/Ashby application forms |
| Job data sources | Greenhouse Job Board API, Lever Postings API, Ashby Job Board API, RemoteOK API, Arbeitnow API, Himalayas API | All public/documented JSON endpoints — no scraping of protected sites |
| Notifications | Telegram Bot API (via @BotFather) | Instant per-application alerts + daily digest |
| Scheduling | Python `cron`/`schedule` loop (or OS-level cron) | Runs the pipeline every few hours |
| CV parsing | `pdfplumber` / `PyPDF2` | Extracts CV text for LLM prompting |
| HTTP client | `requests` / `httpx` | Calls job board APIs and OpenRouter |
| Env/secrets | `.env` + `python-dotenv` | OpenRouter key, Convex deploy key, Telegram bot token |
| Build/dev environment | Antigravity | Agentic build tool executing this spec |
| Hosting (engine runtime) | TBD — options: local machine w/ cron, small VPS, or serverless cron (e.g. GitHub Actions scheduled workflow) | Needs a decision — see Section 12 |

---

## 3. Hard Constraints (non-negotiable, agreed before build)

1. **No scraping or auto-submitting on LinkedIn or Indeed.** Both actively detect and block this; it risks account bans and IP blocks. Excluded from scope entirely.
2. **Only auto-apply on platforms with stable, scrapeable/structured forms:** Greenhouse, Lever, Ashby (and similar ATS platforms with consistent HTML/JSON structure).
3. **Rate limiting:** max 15–20 applications/day. No burst-applying to everything at once — this looks like bot traffic and can get the source IP flagged.
4. **Hard filters before any LLM scoring:**
   - Auto-reject titles containing "Senior", "Lead", "Staff", "Principal", "Manager", "Head of"
   - Auto-reject postings requiring 3+ years experience (regex + LLM check)
5. **Full auto-submit, no human review step** (per user decision) — but every submission is logged to Convex with the exact payload sent, so it's fully auditable after the fact.

---

## 4. Job Sourcing Strategy

### Why not Sri Lanka-local jobs
No structured/legal API exists for the Sri Lankan job market (topjobs.lk, xpress.lk have no public API; scraping them carries the same ToS/anti-bot risk flagged above). **Decision: target remote-first, globally-hiring roles instead** — these are more abundant, more automatable, and commonly open to Sri Lanka-based applicants.

### Data sources (all legitimate APIs, no scraping of protected sites)
| Source | Type | Notes |
|---|---|---|
| Greenhouse Job Board API | Public JSON API | `boards-api.greenhouse.io/v1/boards/{company}/jobs` — no auth needed |
| Lever Postings API | Public JSON API | `api.lever.co/v0/postings/{company}` — no auth needed |
| Ashby Job Board API | Public JSON API | Per-company public endpoint |
| RemoteOK API | Public JSON | Remote-only listings |
| Arbeitnow API | Public JSON | Free, includes remote + visa-sponsor tagging |
| Himalayas API | Public JSON | Remote-first roles |

**Approach:** maintain a list of target companies (curated + discoverable via aggregator search) known to use Greenhouse/Lever/Ashby, poll their public job APIs directly — this is not scraping, it's calling documented public endpoints.

---

## 5. System Architecture

```
┌─────────────────┐
│  Scheduler       │  (cron / loop, runs every few hours)
└────────┬─────────┘
         │
┌────────▼─────────┐
│ Job Sourcing      │  Greenhouse / Lever / Ashby / RemoteOK / Arbeitnow / Himalayas
│ (Python, requests)│  → normalize into common schema
└────────┬─────────┘
         │
┌────────▼─────────┐
│ Convex: jobs table│  dedupe by (source, external_id)
└────────┬─────────┘
         │
┌────────▼─────────┐
│ Hard Filters      │  title regex, experience regex
└────────┬─────────┘
         │
┌────────▼─────────┐
│ LLM Match Scoring │  OpenRouter — cheap/fast model
│ (score 0–100)      │  compares JD vs CV + target roles
└────────┬─────────┘
         │  score >= threshold
┌────────▼─────────┐
│ Cover Letter Gen   │  OpenRouter — stronger model
│                    │  tailored 150–200 words, per JD
└────────┬─────────┘
         │
┌────────▼─────────┐
│ Auto-Apply Engine  │  Playwright — fills native
│ (Playwright)       │  Greenhouse/Lever/Ashby forms
└────────┬─────────┘
         │
┌────────▼─────────┐
│ Convex: applications│ log status, payload, timestamp
│ table               │
└────────┬─────────┘
         │
┌────────▼─────────┐
│ Telegram Bot       │  instant ping per application
│                    │  + daily summary digest
└───────────────────┘
```

---

## 6. Convex Schema (draft)

```ts
// jobs table
{
  _id: Id<"jobs">,
  source: string,            // "greenhouse" | "lever" | "ashby" | "remoteok" | ...
  external_id: string,       // dedupe key
  company: string,
  title: string,
  location: string,
  remote: boolean,
  description: string,
  apply_url: string,
  posted_at: number,
  match_score: number | null,
  status: "new" | "filtered_out" | "scored" | "applied" | "skipped" | "error",
  created_at: number,
}

// applications table
{
  _id: Id<"applications">,
  job_id: Id<"jobs">,
  cover_letter: string,
  submitted_at: number,
  submission_status: "success" | "failed",
  error_message: string | null,
  form_payload: any,         // full audit trail of what was submitted
}

// resume_versions table
{
  _id: Id<"resume_versions">,
  version_label: string,
  content_text: string,      // parsed CV text used for LLM matching
  file_url: string,          // stored resume file (Convex file storage)
  active: boolean,
}

// logs table
{
  _id: Id<"logs">,
  level: "info" | "warn" | "error",
  message: string,
  context: any,
  created_at: number,
}
```

---

## 7. LLM Usage (via OpenRouter)

| Task | Model tier | Input | Output |
|---|---|---|---|
| Match scoring | Fast/cheap (e.g. small model) | JD text + CV summary + target role list | Score 0–100 + one-line reasoning |
| Cover letter generation | Stronger model | Full CV + JD + company name | 150–200 word tailored cover letter |
| Experience-requirement sanity check | Fast/cheap | JD text | Boolean: exceeds 2 yrs required? |

API keys needed: **OpenRouter API key** (user will provide). Model selection configurable — plan allows swapping between OpenRouter models to compare cost/quality (per user's earlier note about testing multiple models).

---

## 8. Auto-Apply Engine (Playwright)

- One handler per ATS type: `apply_greenhouse()`, `apply_lever()`, `apply_ashby()` — each knows that platform's standard form field structure.
- Fields auto-filled: name, email, phone, resume upload (from Convex file storage), cover letter (LLM-generated), LinkedIn/portfolio links if fields exist.
- Screenshot + full form payload saved to `applications` table for every submission (successful or failed) for audit/debugging.
- Retry logic: 1 retry on transient failure, then mark `error` and notify via Telegram.

---

## 9. Telegram Notifications

- **Setup:** create bot via @BotFather (5 min), get bot token, get chat_id of your personal chat or group.
- **Per-application message:** company, title, match score, application status (success/fail), link to job.
- **Daily summary (once/day):** total jobs found, total scored, total applied, total failed, top 3 highest-scoring matches.
- **Alerting:** if the engine errors out or a source API goes down, send an immediate alert.

---

## 10. Rate Limiting & Anti-Detection Guardrails

- Max 15–20 applications/day (configurable).
- Randomized delay (30–90s) between Playwright submissions — no rapid-fire bot-like bursts.
- Respect `robots.txt` and documented rate limits on all public APIs used.
- No auto-apply on any platform outside Greenhouse/Lever/Ashby without explicit sign-off (LinkedIn/Indeed/company custom portals stay out of scope).

---

## 11. Build Phases

**Phase 1 — Core pipeline (Day 1–2)**
- Convex schema setup
- Job sourcing from Greenhouse + Lever public APIs (start with these two, add Ashby/RemoteOK/Arbeitnow after)
- Hard filters
- Telegram bot basic ping

**Phase 2 — Intelligence layer (Day 2–3)**
- OpenRouter integration for match scoring
- Cover letter generation
- CV parsing into structured text for prompting

**Phase 3 — Auto-apply (Day 3–5)**
- Playwright handlers for Greenhouse + Lever forms
- Convex application logging
- Daily summary digest

**Phase 4 — Run & monitor (Day 5–10)**
- Scheduler running every few hours
- Daily review of Telegram digests
- Tune match-score threshold and target company list based on real results

---

## 12. Open Items / Needs From User Before Build

- [ ] OpenRouter API key
- [ ] Confirm which OpenRouter model(s) to use for scoring vs. cover letters (cost/quality tradeoff)
- [ ] Convex project setup (new project or reuse existing Career141 one? — should be a separate project for isolation)
- [ ] Telegram bot token + chat ID (5-min setup via @BotFather)
- [ ] Confirm daily application cap (suggested: 15–20/day)
- [ ] Confirm match-score threshold for auto-apply (suggested starting point: 70/100)
- [ ] Seed list of target companies known to use Greenhouse/Lever/Ashby (or start broad via aggregator search)

---

## 13. Explicitly Out of Scope

- LinkedIn Easy Apply automation
- Indeed auto-apply
- Any company career-page portal outside Greenhouse/Lever/Ashby (e.g. Workday, custom-built portals) — can be added later per-portal, but each needs its own handler and is higher-effort
- Sri Lanka-local job boards (no automatable data source)
- Human review/approval step in the apply loop (per user decision — fully autonomous)
