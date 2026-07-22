# bible — Project Bible Builder (Claude Code skill)

Generate, update, or read a project **"bible"**: living, cross-linked onboarding +
reference documentation that approximates a codebase's source of truth from three pillars.

- **Code = the factory** — what the system actually does (FE routes, BE domains).
- **URS/PRD/spec = the product blueprint** — what it was promised to do (compliance audit
  traced to `file:line`, when a spec exists).
- **Database schema = the raw material** — tables ↔ models, columns, PK/ID strategy, dead tables.

Plus the **cross-pillar relationships** (requirement ↔ FE page ↔ endpoint ↔ table) and an
optional **e2e / testing-enablement** layer (roles, selectors, tagged journeys, seed state).

The bible is *derived, not authoritative* — a best-effort snapshot that drifts as code
changes. Every file carries an `Audited:` stamp; the skill can install a soft CLAUDE.md
rule that **asks** you to refresh after major changes (never auto-runs).

## Modes
- **create** — build a new bible (multi-file by default, untracked `docs/bible/`).
- **update** — refresh the section(s) affected; bumps `Audited:` stamps.
- **read** — answer from the bible without re-reading the whole codebase.

## Install
Clone into your Claude Code skills directory:

```bash
git clone git@github.com:gz-ang/bible.git ~/.claude/skills/bible
```

Then invoke with `/bible` (create / update / read).

## Layout
```
SKILL.md                          # the doctrine + phase flow
references/urs-audit-spec.md      # URS/blueprint compliance audit sub-agent spec
references/e2e-enablement-spec.md # optional e2e/testing-enablement layer spec
```

Output is portable markdown (renders on GitHub and in plain editors). It is also an
Obsidian-compatible vault as-is; Obsidian graph/Dataview enrichment is available on
request.
