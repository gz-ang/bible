# UPDATE mode — runbook

UPDATE never runs on its own. The operator (the main session) runs it only after the user asked for it,
and confirms the scope (step 1) before spawning anyone.

## 0. Baseline

The baseline lives in the project marker `<project>/.claude/bible.json`, on the bible's entry:

```json
{ "path": "docs/bible", "scope": "root", "created": "2026-09-17",
  "audited_commit": "1f902df", "audited_at": "2026-10-19",
  "graph": "graphify-out/graph.json", "citation_format": "v3-symbol-anchors",
  "findings_glob": "^docs/findings/" }
```

`audited_commit` = the commit every citation in the bible was last verified against. Each file's stamp
repeats it: `Audited: 2026-10-19 @ 1f902df`. No `audited_commit` → this is the first update under these
rules: ask the user for the commit the bible was last audited at (the stamps' date is a hint), or run
the migration in `citations.md` first if the bible still has `path:line` citations.

## 1. Scope (operator, no agents)

```bash
T=<skill dir>/tools/bible-cite.py
python3 -I $T --bible docs/bible --repo . range                       # commits, files, renames, cited files changed, findings docs
graphify update .   # only if the project uses graphify (marker "graph"); otherwise skip
python3 -I $T --bible docs/bible --repo . check --range <audited_commit>..HEAD
```

From those, write `_build/update-<date>.md`: range, commit count, changed files, renames, findings docs in
range, check counts, and the work split below. Show the user the counts and the split; wait for go.

Work items, by source:
- **Mechanical** — `ok` with no change in range, `drifted`, `new`: the script handles them. No agent reads them.
- **Re-read** — `ok`/`drifted` citations into files changed in range (`note: file changed in range`):
  the construct still exists, but the sentence may no longer be true.
- **Fix** — every other status (`citations.md` → statuses table).
- **Content** — behaviour added or changed in range that the bible does not cover yet: from the commit
  log, the findings docs in range, and changed files no citation points at.

Small range (a handful of changed cited files, no new domain) → the operator does it alone; skip step 2.

## 2. Fan-out (writers)

- **One writer per bible file.** Never two agents editing one file, ever; a writer may own several
  files. The split is by bible file, not by code area.
- Writers are Sonnet workers. The operator plans, reviews, and runs every `--write`.
- Each writer gets its own scratch dir `_build/run-<date>/<agent>/` and a worklist JSON there
  (`mdline`, token, status, note, reason) built by the operator from `check.json`.
- Each writer reads: the brief (`update-brief.md`, filled in), its worklist, **the findings docs in
  range that touch its domain** (they record what changed and why — read them before the diff), and
  `git diff <audited_commit>..HEAD -- <files its doc cites>`.
- Writers edit their own bible files in place (Edit, never Write), write the citation grammar only,
  never run `--write`, and return a five-line summary plus `report.md` in their scratch.

## 3. Final operator pass

All of these, in order, before anything is called done:

1. `check --write`, then `check` again: **0** statuses other than `ok`.
2. `scan`: 0 bare, 0 legacy, 0 malformed.
3. `links`: 0 broken.
4. History grep over the shipped files: no `shifted`, `moved from`, `was :N`, `Round N`, `pass N`,
   `RESOLVED`, dated changelog headings. Anything found moves to findings (see SKILL.md *History*).
5. Sample read: at least 8 claims, spread over the files writers touched — read the sentence, open
   the link, confirm the code says it. Report sampled/passed.
6. Stamp every file `Audited: <date> @ <short HEAD>`; set `audited_commit` and `audited_at` in the
   marker. Stamps move only when steps 1–5 passed for the whole bible.

## 4. Record the run

Append one row to `_build/runs.md`:

| date | range | commits / files | wall | tokens | cites checked by script | sent to agents | corrections | agents |

Wall = first agent start to last agent end, plus the operator's own time if measured. Tokens from the
agents' usage reports. "Corrections" = tokens or sentences changed by agents. This is how one update is
compared with the last.
