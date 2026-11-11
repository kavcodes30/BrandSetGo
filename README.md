# BrandSetGo

**Brand governance for creators and teams — check it before you publish it.**

BrandSetGo turns a brand's approved identity into a versioned, evidence-backed review policy, then checks
content against it: AI classification, six independent reviewers, a legal guideline registry with citations,
intent-preserving fixes, risk-based human routing and a version-locked Brand Passport.

Two account types, one platform:

| | Creator | Business |
|---|---|---|
| Workspace | One personal brand, one seat | Many brands, team seats, roles |
| Dashboard | `/creator` — my brand, my checks, my coaching | `/business` — brand health, team, approvals |
| Approvals | Self-approval | Manager / legal routing, review queue |
| Plan | Creator Free → Creator Pro | Business Starter → Business Growth → Enterprise |

Plus a **platform admin console** (`/admin`) for the operator: every account, workspace, plan, usage figure
and MRR.

**No Node.js, no build step.** Python 3.11+ and a browser. The UI is plain HTML/CSS/JS served by FastAPI on
the same origin as the API.

---

## Deploy it

The app is one process serving both the API and the UI, so any Python host works.

**Render** — push the repo, then New → Blueprint and pick `render.yaml`. It provisions the service, a 1 GB
disk at `/var/data` (SQLite + uploads), a generated `SECRET_KEY`, and asks you for `SARVAM_API_KEY` and
`PUBLIC_BASE_URL`. **Railway / Heroku** — the `Procfile` is included. **Docker** — `docker compose up --build`.

| Env var | Why |
|---|---|
| `SARVAM_API_KEY` | Enables live classification, semantic and legal review. Without it the app runs deterministically. |
| `SECRET_KEY` | Signs session cookies. Generate it (`generateValue: true` on Render) so logins survive deploys. |
| `COOKIE_SECURE=true` | Required on HTTPS. Leave `false` for `http://localhost`. |
| `PUBLIC_BASE_URL` | Used in password-reset links. Set it to your real URL. |
| `DATABASE_URL` | `sqlite:////var/data/brandsetgo.db` on a host with a disk, or a Postgres URL. |
| `UPLOAD_DIR` | Where uploaded images/audio are stored; point it at the persistent disk. |
| `FIRST_USER_IS_ADMIN` | The first sign-up becomes platform admin. Set `false` once you have yours. |

**About the key.** It is pre-wired in `backend/sarvam.key` and the app reads it at boot (`/health` reports
`key_source`). An env var `SARVAM_API_KEY` overrides it. The key is deliberately a config file and not source
code: if you ever push this repo publicly, GitHub secret scanning revokes a committed key within minutes.
If you deploy from GitHub rather than uploading the folder, set `SARVAM_API_KEY` in the host dashboard (one
field) or copy `backend/sarvam.key` onto the server. Rotate the key in the Sarvam dashboard whenever you share
the archive.

## Run it

### Windows — double-click `run.bat`

Finds Python, creates `backend\.venv`, installs dependencies, checks the AI connection, starts the server and
opens http://localhost:8000. One process, one window. **Nothing to configure and no key to paste** — the
workspace ships with the Sarvam key already wired in `backend/sarvam.key`, so classification, the semantic
reviewer and the legal pass are live from the first run.

```
run.bat            normal start
run.bat seed       create demo accounts (passwords printed once), then start
run.bat reset      wipe the database, then start empty
```

The **first account you create becomes the platform admin**. After that, sign up normally as a creator or a
business.

### macOS / Linux — `./run.sh [seed|reset]`

### Docker

```bash
docker compose up --build
```

### Manual

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# app: http://localhost:8000      API docs: http://localhost:8000/docs
```

### Accounts

Nothing is hardcoded. There is no seeded user, no default password and no bypass header. Options:

1. **Sign up in the UI.** The first account on a fresh database becomes platform admin.
2. **`python -m app.scripts.seed_demo`** — creates an admin, a business owner and a creator with randomly
   generated passwords printed once. It also builds a brand, a policy, and three submissions: a caption, a
   30-second video with a transcript, and a creator post with a paid-partnership disclosure gap.
3. **`python -m app.scripts.create_admin you@example.com [password]`** — create or promote an admin on an
   existing database.

Set `FIRST_USER_IS_ADMIN=false` if you do not want the first sign-up to be an admin.

---

## What the review actually does

**Classification runs at ingest, not during review.** When content is submitted, Sarvam classifies it once
(language, type, category, audience, sensitivity, PII, claims, risk hints) and the answer is stored on that
content version, keyed to its hash. A review reads the stored classification instead of paying for it again;
`POST /api/content/{id}/classify` re-runs it explicitly, and any edit re-classifies on the next submit. That
keeps review latency and API spend down, which matters when the app is hosted.

A submission runs through: privacy label → stored AI classification → policy snapshot → evidence retrieval →
six checkers → reconciliation → patches → drift check → risk score → routing → human decision → passport.

**A draft policy never blocks a check.** If the owner has not published a policy yet, the review runs against
the latest draft: brand-rule findings are marked provisional, and the statutory legal guidelines are checked
regardless, because they do not depend on your approval. Every review reports the state it was judged under:

```json
"policy_state": { "version": 1, "status": "draft", "enforced": false, "rules": 5, "proposed_rules": 5 }
```

Approve the policy whenever you are ready — it changes what is *enforceable*, not what can be *checked*.

| Checker | What it judges | Layer |
|---|---|---|
| **Tone** | voice, restricted words, approved examples | deterministic |
| **Facts** | sizes, prices, quantities against the product sheet | deterministic |
| **Claims** | duration, efficacy, clinical, absolute promises vs approved claims | deterministic |
| **Visual** | approved assets, palette, logo lockup | deterministic |
| **Accessibility** | measured WCAG contrast, alt text | deterministic |
| **Language** | glossary terms and disclaimer survival in HI/MR | deterministic |
| **Legal** | the guideline registry, with the exact citation | deterministic **+** AI |

### The legal engine

`backend/app/legal/guidelines.py` is a versioned registry of 21 guidelines mapped to Indian frameworks —
DMR Act 1954 (cure claims), Cosmetics Rules 2020, ASCI Code (substantiation, comparisons, influencers),
Consumer Protection Act 2019 and the CCPA misleading-ads guidelines 2022, Legal Metrology packaged
commodities rules, FSSAI advertising regulations 2018, DPDP Act 2023, IT Rules on synthetic media, Trade
Marks Act, BIS Act, SEBI/RBI return claims, CCPA greenwashing guidelines 2024, COTPA.

Each entry carries: authority, citation, the obligation in plain words, severity, and **what to change**. A
finding shows all of it:

> **IN-DMR-S3 · Claim to cure or treat a disease** — *Drugs and Magic Remedies (Objectionable Advertisements)
> Act, 1954 — Section 3(d) read with Schedule I.* “cure anxiety” engages this. Advertisements may not claim
> a product cures a condition in Schedule I… **What to change:** remove the disease claim entirely; describe
> the cosmetic or sensory benefit instead.

Legal checking is independent of brand policy: it runs on the sector and channel, not on whether you have
approved your own rules.

Two layers produce legal findings:

* the **deterministic scan** matches trigger patterns and owns `critical` severity;
* the **Sarvam pass** finds implied violations and must cite a guideline *from the registry*, quote an exact
  substring, and can never exceed the guideline's own severity or issue `critical`.

The registry version is recorded on every review, and the UI repeats the boundary: **reviewer assistance,
not legal advice.**

### Video and audio

Video upload works out of the box: `imageio-ffmpeg` ships an ffmpeg binary as a pip dependency, so the audio
track is extracted and sent to Sarvam with no system install. Media is reviewed through its words, with the
seconds attached:

1. Upload audio → Sarvam `saaras:v3` returns a transcript **with word-level timings**.
2. Or paste an SRT/VTT/timestamped transcript (what Instagram/YouTube auto-captions give you).
3. Segments are checked individually; every finding carries `timecode_start`/`timecode_end`.
4. The review page renders a timeline: click a flag to jump to the finding.

A 30-second reel with “clinically proven to cure anxiety” produces a `critical` DMR finding pinned to
**00:03–00:08**, a duration claim at **00:08–00:12**, and bait-urgency wording at **00:12–00:17**.

When Sarvam returns usable word timings the review is word-accurate; when it returns one block for the whole
clip, segment boundaries are spread across the exact runtime (read from the WAV header) and the response is
labelled `timing: "estimated"`. Frame-level visual detection is roadmap; Sarvam's vision endpoint is beta and
not enabled on this key, so images are measured rather than read.

---

## Screens

| Screen | Route |
|---|---|
| Sign in / sign up (creator or business) | `/login`, `/signup` |
| Creator dashboard | `/creator` |
| Business dashboard (brands, team, approvals) | `/business` |
| Platform admin console (users, workspaces, plans, MRR) | `/admin` |
| Brand dashboard | `/dashboard` |
| Brand Genesis (5-step wizard) | `/genesis` |
| Brand DNA Studio (+ guideline import) | `/brands/[id]/dna` |
| Content Studio (text, image, video, audio) | `/studio` |
| Explainable review + AI classification + timeline | `/reviews/[id]` |
| Reviewer panel | `/reviews/[id]/panel` |
| Rewrite & meaning drift | `/reviews/[id]/rewrite` |
| Risk & routing | `/reviews/[id]/risk` |
| Approvals | `/approvals` |
| Brand Passport + public verification (no login needed) | `/passport`, `/verify/[id]` |
| Legal library + copy scanner | `/legal` |
| Creator coaching | `/coaching` |
| Multilingual consistency | `/multilingual` |
| Privacy & AI disclosure | `/privacy` |
| Analytics | `/insights` |
| State machine & failure paths | `/workflow` |

---

## Plans, limits and the pricing model

`backend/app/services/plans.py` is the single source of pricing. Limits are enforced, not decorative:

| Plan | ₹ / month | Brands | Seats | Reviews / month |
|---|---|---|---|---|
| Creator Free | 0 | 1 | 1 | 20 |
| Creator Pro | 499 | 3 | 1 | 300 |
| Business Starter | 2,499 | 5 | 5 | 800 |
| Business Growth | 7,999 | 25 | 20 | 4,000 |
| Enterprise | custom | 200 | 100 | 50,000 |

* Exceeding the review quota returns **402** with the upgrade message.
* Adding a brand beyond the plan returns **402**.
* Adding a seat beyond the plan returns **402**; creator workspaces are single-seat by design.
* The admin console shows live MRR/ARR, revenue mix, sign-ups per week, busiest workspaces and per-plan
  workspace counts, and can move a workspace between plans (with an audit entry).

Usage is measured from real records — reviews this month, AI calls, tokens in/out — never from a counter
someone has to maintain.

---

## Sarvam AI

Set `SARVAM_API_KEY` in `backend/.env` (git-ignored), or let `run.bat` ask for it. Default model:
`sarvam-105b-conversations` for structured output, `saaras:v3` for speech.

| Layer | What the model does | Guard |
|---|---|---|
| Classification | language, type, category, audience, sensitivity, PII, claims, risk hints | claims must be exact substrings; language cross-checked against script; label can only be raised |
| Semantic review | implied promises, voice drift, translation gaps | agent must match the rule's category; approved claims can't be re-accused; never `critical` |
| Legal review | implied violations mapped to registry codes | code must be in scope; span must be in the copy; severity capped at the guideline's |
| Rewrite | one minimal replacement | may not add a number or a new promise |
| Rule extraction | guidelines → draft policy | still a draft a human must approve |

Without a key the platform runs deterministically: classification falls back to script + PII patterns, and
the six checkers are unchanged. The UI says which mode it is in, and every review records the model that
actually ran, with token counts in the disclosure log.

Calls retry twice, cache for five minutes, and sit behind a circuit breaker (3 failures → 60s open), so a
provider outage degrades to deterministic review instead of failing.

---

## Billing, email and workspaces

**Self-serve plans.** `GET /api/billing/summary` shows the current plan, usage and invoices;
`POST /api/billing/checkout` moves the workspace, writes a numbered invoice (`BSP-INV-YYYY-NNNN`), an audit
entry, and updates seats. A 402 anywhere in the product deep-links to `/billing`. Downgrades are allowed and
flag any usage above the new limits.

**Email without a mail server.** Every message (password reset, team invite) is written to an outbox table and
readable in the admin console. With `SMTP_HOST`/`SMTP_USER` set it is also sent. Password reset is a
single-use token (30 minutes, hashed at rest), and the endpoint answers identically for unknown emails so it
cannot be used to enumerate accounts.

**Multiple workspaces.** A person can own several workspaces (a personal brand plus a client, say). The
session token carries the workspace, the top bar switches between them, and `POST /api/auth/workspaces`
creates another. Cross-workspace ids still return 404.

**Images.** `POST /api/content/upload-image` stores the file and measures it: dimensions, palette from pixels,
dominant text/background pair, WCAG contrast and layout density. Those measurements are what the visual and
accessibility checkers use, so an image is judged on its real colours rather than metadata someone typed.

## Resilience

* **Review timeout** — a review that exceeds `REVIEW_TIMEOUT_SECONDS` returns a *partial* review
  (`needs_human`, band `incomplete`, routed to a specialist) instead of hanging.
* **Idempotent writes** — `POST /api/content` and `POST /api/reviews` accept an `Idempotency-Key` header and
  return the first result on retry, so a flaky network cannot duplicate content.
* **Rate limiting** — sign-in, reset requests and review creation are limited per IP/workspace.
* **Session revocation** — changing or resetting a password bumps `token_version`, which invalidates every
  token issued before it.
* **Policy changes invalidate passports** — publishing a new policy version voids clearances issued under the
  old one, with the reason recorded on each record.

## Security

* Passwords: PBKDF2-HMAC-SHA256, 210k rounds, per-user salt.
* Sessions: HMAC-SHA256 signed token in an HttpOnly, SameSite=Lax cookie (7 days), or `Authorization: Bearer`.
* Signing secret: `SECRET_KEY` env, else generated once into `backend/.secret` (chmod 600). Never committed.
* Every query is scoped to `ctx.org.id`; cross-tenant reads return 404, not 403.
* Roles: owner, admin, manager, legal, reviewer, creator, viewer — checked server-side per endpoint.
* Platform admin is a separate `platform_role`; the admin API is gated on it, and an admin cannot suspend
  themselves.
* Suspending a user blocks login immediately; suspending a workspace blocks every member.
* Legal overrides require the `legal` role **and** a written justification, and are written to the audit log.

---

## Tests

```bash
cd backend && pytest -q      # 78 tests, no network required
```

| File | Covers |
|---|---|
| `test_auth.py` | sign-up rules, duplicate email, weak password, login/logout, cookie flags, password change, first-user admin |
| `test_tenancy.py` | workspace isolation, creator vs business dashboards, admin gating |
| `test_plans.py` | brand, seat and review-quota limits |
| `test_legal.py` | registry integrity, citations, cure claims, influencer disclosure, AI guard rails |
| `test_media.py` | SRT/VTT parsing, transcription errors, second-accurate video flags |
| `test_admin.py` | MRR, users list, plan change, suspension |
| `test_ai_layer.py` | classification, semantic and legal guards, outage fallback |
| `test_demo_path.py` | the full customer path, plus draft-policy reviews that still flag legal issues |
| `test_gaps_closed.py` | billing, password reset, session revocation, rate limits, workspaces, image review, policy invalidation, timeout, idempotency |
| `test_ingest_classification.py` | classification stored at ingest and reused, key from env or file |

---

## API surface

Auth: `POST /api/auth/signup|login|logout|forgot-password|reset-password|switch-workspace|workspaces`,
`GET /api/auth/me`, `GET /api/auth/plans`, `PATCH /api/auth/profile`, `POST /api/auth/password`.
Billing: `GET /api/billing/plans|summary`, `POST /api/billing/checkout`. Media: `POST /api/content/upload-image`,
`GET /api/assets/{id}/file`. Admin: `GET /api/admin/invoices|mail`.

Workspaces: `GET /api/workspace/creator|business|members|activity`, `POST|PATCH|DELETE /api/workspace/members`.

Admin: `GET /api/admin/overview|users|orgs`, `PATCH /api/admin/users/{id}`, `PATCH /api/admin/orgs/{id}/plan`.

Review: `GET|POST /api/brands`, `GET /api/brands/{id}`, `POST /api/brands/{id}/policies/import|approve`,
`GET|POST /api/content`, `POST /api/content/transcript|transcribe|extract`,
`GET|POST /api/reviews`, `GET /api/reviews/{id}/panel|risk|drift` (a review carries `policy_state`), `POST /api/reviews/{id}/revise|override`,
`POST /api/rewrite-patches/{id}/decision`, `GET|POST /api/approvals`, `POST /api/approvals/{id}/decision`,
`GET /api/passports`, `GET /api/passports/{id}`, `GET /api/verify/{id}`,
`GET /api/privacy/disclosures|summary`, `POST /api/privacy/preview`,
`GET /api/legal/guidelines`, `POST /api/legal/preview`, `GET /api/ai/status`.

---

## What this build is not

* **Not legal advice.** The registry maps obligations to frameworks for reviewer assistance; applicability is
  a human decision, ideally with counsel. Rules and citations change — pin the registry version in any audit.
* Visual and accessibility checks cover what is measurable: approved assets, palette, logo presence, WCAG
  contrast, alt text. Frame-level image understanding needs a vision model and its own privacy review.
* Images: palette and contrast are measured from real pixels; text baked into a picture is not OCR'd (Sarvam
  vision is beta-gated). Paste the on-screen copy to have it reviewed for claims.
* Billing is test mode: plan changes and invoices are real, no card is charged.
* No card processing yet: checkout applies the plan and writes an invoice, but money movement needs
  Razorpay/Stripe plus webhooks and dunning.
* Not yet: SSO, Postgres + pgvector, Celery workers, malware scanning, per-tenant rate limits, audit export.
  `docs/ARCHITECTURE.md` sketches the production path.

---

## Roadmap to a product

1. **Billing** — Razorpay subscriptions, plan changes with proration, invoice + GST details, dunning.
2. **Retention loop** — weekly brand-health email, "your top recurring issue", one-click recheck.
3. **Integrations** — Instagram/YouTube/LinkedIn pre-publish check, Canva/Figma plugin, CMS webhooks.
4. **Deeper media** — frame sampling + OCR for on-screen text, subtitle diffing, voice-claim detection.
5. **Enterprise** — SSO, self-hosted model option, retention policies per tenant, audit exports.
6. **Accuracy programme** — labelled multi-language set, per-language precision/recall, native-speaker review.
