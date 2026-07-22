# E2E / Testing Enablement — optional bible layer (`50-e2e-enablement.md`)

**Optional. Offer it; do not build by default.** The reference bible (routes → API →
controller → model → table) is the *backbone* an end-to-end test needs; this layer adds
the *last mile* — how to actually drive the app — that plain reference docs omit.

Motivated by real usage: writing Playwright tests repeatedly stalled because the bible
did not record selectors, test accounts, per-role journeys, or which flows are
destructive. Each test session re-derived them from scratch. This captures them once.

## Hard rule — secrets
Reference test accounts **by env-key name or source `file:line` only**. NEVER copy secret
values (passwords, tokens, OTP secrets) into the bible. `email = <see AUTH_TEST_USER>` /
"credentials seeded in `database/seeders/…:NN`" — never the literal password. Same `.env`
prohibition as the rest of the skill.

## Sections

### 1. Environment
- Base URL(s) per environment (local / staging), API prefix, how the FE reaches the BE
  (proxy, `server/api`, direct). Config **keys** only, no values.

### 2. Roles & test accounts
- One row per role: role code · what it can do (one line) · account reference (env-key or
  seeder `file:line`) · login path · post-login landing route.
- Note the auth mechanism (password / OTP / SSO) and any step a headless test must fake
  or bypass (e.g. OTP — point at the dev bypass if one exists, by location).

### 3. Selector strategy  ⚠️ the most-requested, least-documented thing
- State whether `data-testid` (or equivalent stable hook) **exists** in the codebase.
  Grep for it — do not assume.
- If ABSENT: record the fallback ladder per key page — label-based (`getByLabel`),
  placeholder, role (`getByRole`), button text; last resort component-internal selectors
  (mark fragile). Name the UI library (its components decide what selectors are stable).
- Recommend, as a finding, adding stable hooks to login + key dashboard elements — cheap,
  high-leverage first improvement. Do not add them yourself unless asked.

### 4. Journeys per role (tag every one)
- Step-by-step happy path as an HTTP/nav sequence: `GET /login → POST /auth/login →
  redirect /dashboard → …`.
- **Tag each journey `READ-ONLY` or `MUTATING (DANGER)`.** Mutating journeys change data
  and must never run against shared/staging/prod without an explicit, isolated test DB.
  This tag is a safety control, not a nicety.
- Link each step to its bible anchor (endpoint → be-domain, page → fe-page).

### 5. Seed / state prerequisites
- What data must exist for each journey to run (a pending application, a paid invoice, a
  reserved number). Point at the seeder / factory (`file:line`) that creates it, or note
  "must be created by an earlier journey."

## Cross-links & stamp
Every page/endpoint/table mention links to its reference anchor. Stamp `Audited:`.
This doc drifts fastest (UI changes) — flag it for refresh whenever FE pages change.
