# Architecture notes

## Accounts and tenancy

`users` carry a password hash (PBKDF2-HMAC-SHA256, 210k rounds), an `account_type` (creator | business) and an
optional `platform_role` (admin | support). `organizations` are the tenant boundary and hold the plan. A
`membership` joins them with a role. Sign-up creates both: a creator gets a personal brand plus a draft policy;
a business gets an empty workspace and invites members.

Sessions are an HMAC-SHA256 signed token in an HttpOnly cookie (or a bearer header for API clients). The
signing secret comes from `SECRET_KEY` or is generated once into `backend/.secret`. `get_ctx` resolves user →
membership → org on every request and every query filters by `org_id`; a cross-tenant id returns 404.

The first account on a fresh database becomes the platform admin (`FIRST_USER_IS_ADMIN`, default true).
`/api/admin/*` is gated on `platform_role`, never on the workspace role.

## Plans and metering

`services/plans.py` holds the catalogue and the metering. Usage is computed from records, not counters:
reviews in the current calendar month, brands, members, AI calls and tokens from `review_runs.ai_meta`.
Quota breaches return 402 with the upgrade text at the three points that matter: creating a review, creating
a brand, adding a member.

## Legal engine

`legal/guidelines.py` is a frozen registry (versioned `REGISTRY_VERSION`) of guidelines with authority,
citation, obligation, severity, remediation, sector/channel scope and trigger patterns.
`legal/checker.py` is the deterministic scan (owns `critical`). `legal/ai.py` is the Sarvam pass: it may only
cite codes in scope, must quote an exact substring, and its severity is clamped to the guideline's own
ceiling; `critical` is never issued by the model. Findings persist the citation fields on `agent_findings`,
so a review remains explainable after the registry moves on.

## Media

`services/media.py` parses SRT/VTT/timed text into `{start, end, text}` segments and calls Sarvam
`saaras:v3` with `with_timestamps=true` for word-level timings, grouping words into caption-sized segments.
A content version stores `transcript` and `duration_s`; `attach_timecodes()` maps each finding's character
span back to a segment, so a flag carries the seconds it is spoken. Video containers are converted with
ffmpeg when it is on the host; otherwise the API returns a typed error with the transcript alternative.

## Frontend

`web/index.html` + `web/css/app.css` + `web/js/**` — ES modules loaded directly by the browser. `js/views/`
holds auth, the two dashboards, the admin console, the legal library and the review surfaces. FastAPI
serves `web/` as static files at `/`, so the app and the API share one origin (no CORS, no proxy, no build).
`js/core.js` holds the API client, a small `el()` DOM builder, formatters and shared components;
`js/router.js` holds shell state and a hash router; `js/views/` holds one module per screen group. Adding a
screen means adding a view function and a route regex — nothing else.

## Request path

1. `Ctx` dependency resolves the user, workspace and role from `X-User-Email`, and every query filters by
   `org_id`. Cross-tenant reads return 404, not 403, so existence is not leaked.
2. A review is created for a `content_version`, which is immutable. Editing content creates a new version
   and invalidates any clearance bound to the old hash.
3. The graph runs: `preprocess` (sensitivity, redaction) → `retrieve` (policy rules, claims, products,
   assets, glossary) → `check` (parallel, isolated) → `reconcile` (dedupe, keep contradictions) →
   `patches` → `score` (risk + routing).
4. Findings, patches, a drift preview, a routing decision, a disclosure row and coaching signals are
   persisted in one transaction, with an audit event.

## Data model

`organizations · users · memberships · brands · policy_versions · brand_rules · products · approved_claims ·
assets · content_items · content_versions · review_runs · agent_findings · agent_disagreements ·
rewrite_patches · drift_checks · risk_policies · routing_decisions · approvals · clearances · audit_events ·
ai_disclosures · coaching_events · glossary_terms`

Rules carry `code, category, severity, scope, source_ref, evidence_ref, is_authoritative`. A rule proposed
by the model is `is_authoritative = false` until a policy version is published.

## AI layer

Two Sarvam calls per review, both on `sarvam-105b-conversations`:

1. **Classification** (`services/classify.py`) — language, content type, category, audience, sensitivity,
   PII, claims, promises, tone, risk hints. Guards: a returned claim must be an exact substring; the language
   is cross-checked against the script; the sensitivity label can only be raised; PII is the union of the
   model's list and a deterministic detector.
2. **Semantic review** (`services/ai_review.py`) — one batched call across the six checkers, restricted to
   claims / tone / language. `verify_ai_finding()` then enforces agent ownership, rule-in-force, exact span,
   promise language or an independent claim classification, no re-accusation of an approved claim, and
   `clamp_severity()` keeps the model away from `critical`.

Model findings are merged after the deterministic ones, deduplicated by agent + span, and tagged
`source="sarvam"`. Risk scoring sees the merged set. Rejections are recorded in `review_runs.ai_meta` and
shown in the UI, so the verifier's behaviour is auditable rather than invisible.

`services/sarvam.py` owns transport: 2 retries on 5xx/429, 45 s timeout, 5-minute response cache keyed by
prompt, circuit breaker (3 failures → 60 s open), token accounting, and `health()` for the Privacy Center.

## Risk model

```
score = min(100, severity_base + claim_sensitivity + evidence_gaps
                + 9×disagreements + asset_novelty + coverage_penalty + sensitivity_penalty)
```

* `severity_base` — highest confirmed severity: critical 100, high 32, medium 18, low 5.
* `claim_sensitivity` — 14 when a claim finding exists, else 3.
* `evidence_gaps` — 8 per blocking finding with no cited source.
* Bands: `<25 low`, `<55 medium`, `<80 high`, else `critical`; `incomplete` when a checker is missing.
* Any confirmed `critical` finding sets `hard_blocker`, which blocks approval regardless of the score.

## Routing

| Condition | Route |
|---|---|
| hard blocker or regulated sector | legal |
| incomplete checks | specialist |
| disagreement or missing evidence | specialist |
| low score + trusted creator + complete | fast track (auto-clear only if the org enabled it) |
| otherwise | manager |

## Drift invariants

`cta_preserved`, `audience_preserved`, `key_facts_unchanged`, `disclaimers_unchanged`, `no_new_promises`,
`qualifiers_preserved`. Numbers inside an intentionally edited span are excluded. Similarity is reported
separately as a warning only.

## Production path

| Now | Production |
|---|---|
| static ES modules | optional SSR framework if a team wants it |
| SQLite | PostgreSQL + pgvector, row-level tenant policy |
| in-process graph runner | LangGraph with a durable checkpointer |
| synchronous review | Celery/Redis queue with job ids and progress events |
| header-based identity | OIDC/SSO with role claims |
| two synchronous Sarvam calls | queued batched inference with per-tenant quotas |
| local file read | S3-compatible signed uploads, MIME sniffing, antivirus |
| heuristic visual checks | vision model + OpenCV, behind a separate privacy review |
| stdout logs | OpenTelemetry traces + Sentry |

## Evaluation plan

Labelled multi-brand, multi-language set. Report precision/recall/FPR per category and per language,
evidence-citation accuracy (every confirmed finding must link to an applicable approved rule), drift
false-negative rate per invariant, reviewer-agreement rate, median review time and rework cycles. The
numbers in `/insights` are computed from the live workspace, never published as benchmarks.
