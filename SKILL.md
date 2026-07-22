---
name: bible
description: Generate, update, or read a project "bible" — comprehensive, cross-linked onboarding/reference documentation that approximates a codebase's source of truth from three pillars — the code (frontend routes: components, nested components, BE API calls on mount vs action, role-guarded flow maps; and backend domains: models/tables/fillable/ID-gen, controllers→routes, services/repositories/factories/requests/resources, events→listeners with fire sites, queues/jobs, commands+schedule, payment-integration, configs), the requirements blueprint (URS/PRD/SRS compliance audit traced to file:line, when a spec exists), and the database schema (tables↔models, columns, _SEQ presence, unused/backup tables) — plus their cross-pillar relationships and an optional e2e/testing-enablement layer. Use when the user asks to create, update, or read a project bible / 101 / onboarding doc, or invokes /bible. Default output is an untracked docs/bible/, multi-file, fully cross-linked.
---

# /bible — Project Bible Builder

Build and maintain a "bible": living onboarding + reference documentation that acts as the compass to a codebase. Three modes: **create**, **update**, **read**. Infer the mode from the request (or ask if ambiguous).

## What a bible is (read this first)

A bible approximates a project's **source of truth** from three pillars:

- **Code = the factory.** What the system actually does right now. The ground truth of behavior.
- **URS/PRD/spec = the product blueprint.** What it was *promised* to do. Only exists if the project has a written spec.
- **Database schema = the raw material.** The shape of the data everything operates on.

The job is to depict each pillar per domain (FE, BE, DB, and — where a spec exists — compliance) **and to identify the relationships between them**: FE page → API call → controller → model → table, and requirement → the code that implements it.

The bible is **not** the absolute source of truth — it is *written and derived*, a best-effort snapshot that **drifts** the moment code changes. So: every shipped file carries an `Audited: <YYYY-MM-DD>` stamp, claims are verified against real code (not assumed), and the bible must be refreshed after significant change (see *Upkeep reminder*).

## On skill load — upkeep reminder (do this once, early)

The bible is only useful while current. On load, check whether the project has an upkeep habit wired up, and offer to add one — **without ever auto-running an update**.

1. Read `settings.json` (project `.claude/settings.json`, else user `~/.claude/settings.json`) for a `bible.upkeepReminder` key.
   - `"declined"` → the user never wants this. Skip silently. Do nothing.
   - `"installed"` → already set up. Skip.
   - **absent** → continue to step 2 (ask once).
2. Grep the project + user `CLAUDE.md` for an existing bible-upkeep rule. If one already exists, set `bible.upkeepReminder: "installed"` and skip.
3. Otherwise, **offer** (one question, respect the answer): "Add a rule reminding me to refresh the bible after major changes?" On **yes**, append to the project `CLAUDE.md` (create if absent) a rule like:

   > **Bible upkeep** — the project bible lives at `<canonical bible path>` (untracked). After a major refactor, a new feature, or a business-logic change, **ask the user** whether to refresh the bible (`/bible update`). Remind and wait — never auto-run.

   Then set `settings.json` → `"bible": { "upkeepReminder": "installed" }`.
   On **no / "never ask again"**, set `"bible": { "upkeepReminder": "declined" }`.

The rule is a soft nudge that *asks*, by design — it prevents surprise auto-execution while still catching staleness. Skip this whole block in READ mode.

## Defaults (state these, then proceed)

- **Output location:** `docs/bible/` in the root of the working directory — **kept untracked.** On create, if the repo tracks `docs/`, add `docs/bible/`, `docs/bible/_build/`, and `.DS_Store` to `.gitignore` and say so. Never commit a bible into a tracked repo unless the user names that path — a derived artifact drifting under version control rots and misleads.
- **Record the canonical location.** On first create, write a project-memory note (or a `.claude/` marker) recording the bible's path + created date, so UPDATE/READ find the *one* canonical copy instead of guessing and spawning duplicates.
- **Multi-file by default.** A single mega-file becomes unmaintainable. BUT **always ask first** whether they want one single file instead — *especially for small projects* (≲15 routes / ≲10 models, or a single-package repo). Offer single-file when the whole thing would be < ~800 lines.
- **Cross-link everything.** Every mention of a table → its schema entry; every endpoint → its BE domain section; every FE page's API call → that endpoint's anchor; every requirement → the code that implements it. The doc set is a clickable web: requirement → page → API → controller → model → table → back.
- **Cite real locations** as `path:line` (clickable). Never invent line numbers — grep for them.

## Hard rules (always)

- **NEVER read `.env`** or any secrets file. Reference config *keys by name only*, never values. This includes test credentials — reference them by env-key or seeder `file:line`, never the literal secret.
- **Do not document third-party packages**, Docker, or generic infra. Services (object storage, cache, payment gateway, mail) may be *mentioned* by role, not detailed.
- **Focus on core feature domains.** Auth, logging, and audit get a *short summary* only.
- **Do not guess.** If ID-gen, a table's purpose, a caveat, or a relationship is unclear, write an inline `> ❓ OPEN: <question>` and keep going. Surface open questions at the end for the user/dev to confirm.
- **Verify before asserting.** Reference counts, "unused" claims, fire sites, and compliance verdicts come from grep, not assumption. "Active vs unused" = does code actually reference it (`grep -r`), not just "has a model." Absence is the weakest claim — confirm a negative with a second search angle before recording it.
- **Stamp every shipped file** with `Audited: <YYYY-MM-DD>`.

## Context-window protection (this is a large task)

- **Estimate first.** Size the repo (page count, model count, route files, DB table count, DDL size, spec page count). If raw reading would blow the budget, do NOT read everything.
- **Fan out with sub-agents**, one per domain/route-file group / spec module. Each sub-agent reads raw files in *its* context and **writes its own output file**, returning only a short summary (file path + events/jobs/commands/gaps it found + open questions). Tell agents explicitly: "WRITE THE FILE YOURSELF; do not ask for approval; do not return content inline." (Agents sometimes stall otherwise.)
- **Parse big data files in a sandbox**, not into context: DDL → columns, model→table maps, event-listener maps, extracted spec text. Print only summaries; write generated docs directly to disk.
- **Give every sub-agent a shared spec file** (anchor convention + per-domain template) so output is consistent and links don't rot. Keep these specs + parsed intermediates in a `_build/` subfolder (ephemeral, gitignored — not part of the shipped bible).
- Compact at phase boundaries (BE → FE → DB → blueprint are largely independent).

---

## MODE: CREATE

### Phase 0 — Recon & plan (do before any writing)
1. Read orientation only: root + sub-package `README`/`CLAUDE.md`/`AGENTS.md`, route manifest files, the scheduler/cron file. Skip giant auto-generated READMEs (summarize in sandbox if needed).
2. **DB schema source:** prefer **DDL of the live/migrated DB** (`CREATE TABLE` + sequences) over a binary dump. If only a binary dump exists, ask the user for a DDL/`sqlfile` export (you cannot parse binary). Migrations explain *intent*; DDL is the truth.
3. **Detect a blueprint source** for the URS pillar: look for `docs/URS/`, `PRD*`, `*.srs`, `requirements*`, a specs folder, product docs. If found → the URS pillar is in scope (Phase 4b). If none → note it; offer later to derive an *inferred* blueprint from code, or skip. Never fabricate requirements.
4. Extract object inventories in a sandbox: table names, sequence names, model→`$table` map, route→controller map, events/listeners/jobs/commands lists.
5. **Propose the file structure + context plan; ask the single-file question and whether they want the optional e2e-enablement layer.** Wait for confirmation. Suggested multi-file layout (adapt names to the stack):

```
docs/bible/                    # untracked
  00-overview.md               # 101: what it is, doc map, glossary, roles, open questions, Audited date
  10-fe-routes.md              # route→role table + index to per-page detail files
  11-fe-flowmap.md             # navigation graph per role; key flows (mermaid)
  fe-pages/<group>.md          # per page: components (nested), composables, BE API (mount vs action), nav targets
  20-be-domains.md             # index + request lifecycle + endpoint-prefix→domain lookup
  be-domains/<domain>.md       # per domain: models/table/fillable/ID-gen, routes→methods+roles, services/repos, caveats
  21-be-events-jobs.md         # event→listener map (+ fire sites path:line), jobs/queues
  22-be-commands.md            # commands + signatures + schedule
  23-payments.md               # dedicated payment-integration section (gateway, webhook flow, statuses, tables)
  24-configs.md                # project-relevant config keys (no secrets)
  30-db-schema.md              # tables↔models, columns, _SEQ, active/raw/legacy/backup classification
  40-urs-compliance.md         # (if a spec exists) master compliance scorecard
  urs-audit/<mod>.md           # (if a spec exists) per-module requirement tables → file:line
  41-traceability.md           # relationship spine: requirement ↔ FE page ↔ endpoint ↔ table
  50-e2e-enablement.md         # (optional) roles/accounts, selectors, tagged journeys, env, seed prereqs
  _build/                      # specs + parsed intermediates (gitignored, NOT shipped)
```

### Phase 1 — BE domains (sub-agents, one per route-file/domain group)
Per domain, the section must cover:
- **Models:** class, `$table`, **ID generation** (DB sequence `{TABLE}_SEQ` vs a `nextId()/generate_id()`=MAX+1 helper — state which, verified from model/repo/factory), key fillable, relations.
- **Endpoints:** `METHOD /uri` · route `file:line` · `Controller@method` · middleware/roles · service(s) called · notes.
- **Services / Repositories / Factories / Requests / Resources** with one-line purpose.
- **Events fired / jobs dispatched / commands** it touches (list for the cross-cutting docs).
- **Caveats** (⚠️) and `> ❓ OPEN` questions.

### Phase 2 — Cross-cutting
- **Events/jobs/listeners:** the authoritative wiring (check whether the framework auto-discovers or registers explicitly — find the registration site), the event→listener(+method) map, **fire sites** (`grep` for dispatch sites → `path:line`), jobs + queue backing.
- **Commands:** signatures, what each does, which are scheduled (cadence) vs manual.
- **Payments:** dedicated section — gateway client, **webhook/async flow** (mark public/unauth endpoints + signature verification), status-code lifecycle (happy + timeout/failure path), source-of-truth table.
- **Configs:** project-specific config files + keys by name (no values). Note ID-gen wiring, storage disks, integrations.

### Phase 3 — FE routes + flow map
- Extract the composable/service → endpoint map *once* in a sandbox (shared reference) so page agents don't re-derive it.
- Per page: route, layout/guard, components (incl. nested), composables/hooks, **BE API split into on-mount vs on-action(named)**, navigation targets.
- Determine role guards from the real source (global middleware + menu/nav config), not just per-page meta. Build the flow map per role; diagram key flows (mermaid). **Mermaid tip:** quote node labels `["/path/:id"]`; do NOT use `[/label/]` (parallelogram) when labels contain `/ : ( )`.

### Phase 4 — DB schema
Generate `30-db-schema.md` programmatically (sandbox): for each table emit anchor heading, columns (from DDL), model link (from model map), `_SEQ` presence, and a **classification**: model-backed / raw-active (no model but referenced in code) / infra / view / backup / legacy (zero code refs). Use `grep -r` reference counts to separate "no model but used" from "dead." List sequences with no convention-matched table (don't guess owners).

### Phase 4b — Blueprint / URS compliance  *(only if Phase 0 found a spec source)*
Fan out one sub-agent per spec module using `references/urs-audit-spec.md`. Each extracts atomic requirements (`M<n>-R<nnn>`), locates implementing code (`file:line`), classifies `✅/🟡/❌/❓`, and writes `urs-audit/mod-<n>-<slug>.md`. Then roll all modules into `40-urs-compliance.md` (master scorecard + cross-module material gaps + spec inconsistencies). Report-only — **never modify application code.** If no spec source exists, skip this phase (or, if the user asked, derive an inferred blueprint and mark it clearly as inferred, not signed).

### Phase 4c — Traceability spine (`41-traceability.md`)
Assemble the cross-pillar relationship map — one row per feature/requirement: **requirement (or feature) ↔ FE page ↔ endpoint ↔ controller/service ↔ table(s)**, each cell a link to its anchor. Feed it from the FE api-map (Phase 3), be-domains (Phase 1), and the URS audit columns (Phase 4b) — do not re-derive. This is the single view that answers "if I change X, what else is involved."

### Phase 4d — E2E / testing enablement  *(optional — only if the user opted in)*
Build `50-e2e-enablement.md` per `references/e2e-enablement-spec.md`: roles & test-account references (by env-key/`file:line`, **never secret values**), selector strategy per key page (grep for `data-testid`; record the fallback ladder if absent), per-role journeys **tagged READ-ONLY or MUTATING(DANGER)**, environment/base-url, and seed/state prerequisites. This closes the gap where each test session re-derives selectors and journeys from scratch.

### Phase 5 — Stitch & verify
- Write `00-overview.md` (doc map, glossary: roles, status codes, ID-gen, integrations; consolidated open questions; top-level `Audited:` date).
- **Self-verification sample.** Beyond links: pick N (≈5–8) random documented claims across pillars — an ID-gen mechanism, a fire site, a table classification, a compliance verdict — and re-grep each against the code to confirm. A doc-set that fails its own spot-check is unread, not "mostly right." Report sampled/passed counts.
- **Run a link-integrity check** over the folder and fix everything before declaring done:

```python
# anchor = heading lowercased, non-word stripped, spaces→hyphens; plus explicit {#id}
import os,re,glob
root='docs/bible'
def anch(t):
    a={m.group(1) for m in re.finditer(r'\{#([\w-]+)\}',t)}
    for l in t.split('\n'):
        h=re.match(r'#{1,6}\s+(.*)',l)
        if h:
            x=re.sub(r'\{#[\w-]+\}','',h.group(1)).strip().lower();x=re.sub(r'[^\w\s-]','',x);a.add(re.sub(r'\s+','-',x))
    return a
F={os.path.relpath(p,root):open(p).read() for p in glob.glob(root+'/**/*.md',recursive=True) if '/_build/' not in p}
A={f:anch(t) for f,t in F.items()};bad=[]
for f,t in F.items():
    b=os.path.dirname(f)
    for m in re.finditer(r'\]\(([^)]+)\)',t):
        g=m.group(1)
        if g.startswith('http'):continue
        p,_,fr=g.partition('#');tf=f if p=='' else os.path.normpath(os.path.join(b,p))
        if tf not in F:bad.append((f,g,'FILE'))
        elif fr and fr not in A[tf]:bad.append((f,g,'ANCHOR'))
print('broken:',len(bad)); [print(x) for x in bad]
```

### Anchor convention (give to every sub-agent)
- Table link: `[FOO](../30-db-schema.md#foo)` — anchor = table name **lowercased**, underscores kept.
- Use explicit `## Heading {#stable-slug}` so links don't rot.
- Use **standard relative markdown links**, not `[[wikilinks]]` — the doc set must render on GitHub and in plain editors, not only in Obsidian. (The output is already Obsidian-compatible markdown; keep it portable.)

### Obsidian / graph tools (supported on request — do not bring it up)
The bible is already an Obsidian vault: point Obsidian at the folder (`Open folder`) and relative links, backlinks, the graph view, and mermaid all work as-is. **Do not mention or offer Obsidian proactively.** Only when the user explicitly asks for Obsidian support:
- Add optional YAML frontmatter to each file (`type: route|domain|schema|requirement`, `tags: [...]`, `pillar: fe|be|db|urs`) — GitHub and plain editors ignore it; Obsidian's graph grouping and Dataview queries (`LIST WHERE pillar="fe"`) use it. Zero portability cost.
- Keep the standard relative links — **never** fork a second wikilink copy; a parallel vault is a duplicate that drifts, the exact failure this skill guards against.

The genuine Obsidian win is *human* visual exploration (graph/backlinks), not AI context — agents read the markdown directly and gain nothing from wikilinks.

---

## MODE: UPDATE

1. Locate the existing bible: **check project memory / the `.claude/` marker for the recorded canonical path first** (set on create). Default `docs/bible/`; respect a renamed/relocated copy. If multiple copies exist, ask which is canonical and record it.
2. Read only the section(s) affected. Prefer `Edit` (targeted) over `Write` (full rewrite) to avoid clobbering user edits. Before any full rewrite, diff current vs intended and surface discrepancies.
3. When adding research/findings, resolve any matching `> ❓ OPEN` items and record the resolution + date. **Bump the `Audited:` stamp** on every file you touch.
4. Keep cross-links intact; **re-run the link-integrity check** after edits.

## MODE: READ

Answer questions *from the bible* — do not re-read the whole codebase.
1. Find the canonical bible path (memory/marker), then `grep -ri` the bible folder for the topic; collect hits per doc.
2. Synthesize an answer from the documented pieces, citing which doc/section.
3. If the topic is scattered with no consolidated section, say so and **offer to add a consolidated section** (don't auto-create). If the bible lacks the info, say that and offer to research the code. Note the file's `Audited:` date if the answer might be stale.

---

## Output discipline
- Write artifacts to files; reply with file paths + a short summary, not inline dumps.
- End a create/update with: files written, each file's `Audited:` date, the self-verification sample result, the link-check result (0 broken), and the consolidated **open questions** for the user to confirm.
