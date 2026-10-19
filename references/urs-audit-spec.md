# URS / Blueprint Compliance Audit — sub-agent spec (report-only)

Give this to each sub-agent that audits **one** requirements document (URS / PRD / SRS /
spec) against the current codebase. **Do NOT modify application code.** Output is
documentation only. This is the third pillar: the *product blueprint* (what the system
was promised to do) checked against the *factory* (code) and *raw material* (DB).

Only run this pillar when a real spec source exists (see SKILL.md Phase 0 detection). If
none exists, do not fabricate requirements — offer an inferred blueprint or skip.

## Inputs (adapt roots to the stack)
- **Your spec text:** the one requirements doc assigned to you. Read it fully. If it was
  extracted from PDF/DOCX, expect page markers; cite the page/section.
- **Backend root:** controllers, services, commands, models, events/listeners, routes.
- **Frontend root:** pages, components, API client layer.
- **Existing bible code-map** (shortcuts — may be stale, verify against real code):
  the `be-domains/*`, `fe-pages/*`, and any `_fe_api_map` produced by earlier phases.

## Method
1. Extract **atomic** requirements (every "shall / must / should" + each described
   behavior). Give each a stable REQ-ID `M<module>-R<nnn>`.
2. For each requirement, locate implementing code (grep/glob/read). Cite it as a symbol anchor
   (`references/citations.md`); add `~"text"` only when the verdict hinges on one statement.
   Absence is the weakest claim — a bad search and a genuine gap look identical, so
   confirm a "Missing" with a second search angle before recording it.
3. Classify status:
  - ✅ **Met** — implemented, matches the spec.
  - 🟡 **Partial** — partially implemented or deviates.
  - ❌ **Missing** — no implementation found (confirmed by ≥2 search angles).
  - ❓ **Unverified** — cannot confirm from code (infra / manual / external / migration).
4. Note spec-internal contradictions or ambiguities you hit (raise with the product
   owner — these are not code bugs).
5. Pay special attention to concrete rules where drift hides: SLA day counts (working vs
   calendar, holiday-skip), status codes, fee/amount formulas, notification recipients,
   auth/roles, webhook/async flows.

## Output file: `<bible>/urs-audit/mod-<N>-<slug>.md`

The file is a **scorecard plus open divergences**, written so the next update re-checks ✅ rows by script
instead of rewriting them:

- ✅ rows: one short requirement phrase, one citation, nothing else. The checker keeps them current; an
  agent only re-reads one when its cited file changed.
- 🟡 / ❌ / ❓ rows: the only place for explanation — what the spec says, what the code does, the citation.
- No history: no "fixed in round N", no "RESOLVED", no dated notes. A divergence that closes becomes a ✅
  row and leaves the divergence list. What changed belongs in findings docs.

```
# Module <N> — <Title> — Blueprint Compliance Audit
Source: <spec path> · Audited: <YYYY-MM-DD> @ <commit> · report-only

## Scorecard
Total: T · ✅ Met: a · 🟡 Partial: b · ❌ Missing: c · ❓ Unverified: d

## Open divergences (most material first)
| REQ-ID | Spec says | Code does | Status | Evidence |
|---|---|---|---|---|

## Code has, spec lacks
- <behaviour> — <citation>

## Requirements
| REQ-ID | Spec § / pg | Requirement (concise) | Status | Evidence | FE page | Endpoint | Table(s) |
|---|---|---|---|---|---|---|---|

## Spec ambiguities / contradictions noted
- ...
```

The FE-page / Endpoint / Table(s) columns are the feed for `41-traceability.md` — fill
them where known so the master traceability spine can be assembled without re-deriving.

## Master scorecard: `<bible>/40-urs-compliance.md`
Roll every module up into one scorecard table (module · total · met · partial · missing ·
unverified · % met), a **cross-module open divergences** list (most severe first), and a
**spec-inconsistencies** list. Link each module to its per-module file. Stamp `Audited: <date> @ <commit>`.
The same shape applies when the "spec" is a contract doc compliance file inside the bible
(e.g. `40-contract-compliance.md`): scorecard, open divergences, code-has-spec-lacks, ✅ rows terse.

## Return to caller (concise, <200 words)
- Output file path
- Scorecard line
- Top 3 gaps
Keep raw code and raw spec text OUT of your returned message.
