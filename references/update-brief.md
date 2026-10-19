# Writer brief — template

Copy to `_build/run-<date>/brief.md`, fill the `<…>` slots, and hand each writer the path plus its own
assignment line. Keep project specifics in the project's `_build/spec.md`, not here.

---

# Bible update brief — <date>

Repo: `<repo root>` at `<HEAD short>`. Bible: `<bible path>`. Previous audit: `<audited_commit>`.
Read `<bible>/_build/spec.md` (project conventions) and `<skill dir>/references/citations.md` (citation
grammar) first.

## Your assignment

You own exactly: `<bible files>`. Never edit any other file. Scratch: `<bible>/_build/run-<date>/<agent>/`.
Worklist: `<scratch>/worklist.json`, one record per item: `mdline`, `token`, `status`, `note`, `reason`.

Read before the code:
- Findings docs in range for your domain: `<list>`.
- `git diff <audited_commit>..HEAD -- <files your doc cites>`.

## Per item

- `reason: re-read` — the cited file changed. Read the sentence, open the code at the token. Still true →
  no edit. Not true → correct the sentence to current behaviour and fix the token.
- `reason: fix` — the token does not resolve (status in `note`). Find the construct the sentence
  describes; rewrite the token. If the code no longer does it, correct the sentence.
- `reason: content` — behaviour added/changed in range that your file does not cover. Add it in the
  file's existing structure, cited in the grammar.
- Cannot locate after a real search → `(❓ location unverified)` in place and a `> ❓ OPEN:` line under
  `## Open questions` saying what you looked for and where.

## Rules

- Citation grammar only (`path::Symbol`, `path::Class.method`, `path::Symbol~"text"`, `path~"text"`,
  `doc.md::§N`). Never type a line number. When you change a resolved link, replace the whole
  `[...](...)` with the plain backtick token; the operator's run re-links it.
- Describe current behaviour. No dates, round numbers, "previously", "now fixed", "shifted from" — what
  changed and why belongs in findings, not here.
- Compliance files: update the scorecard counts and the open-divergence rows; a divergence that closed
  becomes a ✅ row (or is removed from the divergence list) — no "RESOLVED" note.
- Edit in place (Edit tool), never Write a whole file. Do not touch `Audited:` stamps or `{#anchors}`.
- You may run `python3 -I <skill dir>/tools/bible-cite.py --bible <bible> --repo . --out <scratch> check`
  to see whether your tokens resolve. Never pass `--write`.
- Never read `.env*`, credential files, or `<project secret paths>`. Config keys by name only.
  Do not run tests or servers.

## Report

`<scratch>/report.md`: counts (confirmed, token corrected, sentence corrected, content added, open) and
`L<mdline> old -> new` per change. Return a five-line summary, never file contents.
