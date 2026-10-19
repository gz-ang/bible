# Citations — grammar, checker, statuses

Every pointer from the bible into the code is a **symbol anchor**, not a line number. Writers name the
construct; `tools/bible-cite.py` finds its line, verifies it, and writes the clickable link. Line
numbers drift on every commit; symbol names rarely do, so an update re-checks citations mechanically
instead of re-reading them.

## Grammar (what writers type, inside backticks)

| Form | Use for |
|---|---|
| `` `path::Symbol` `` | function, const, class, interface, type, PHP/Python def, JSON/YAML key |
| `` `path::Class.method` `` | a method; qualify whenever the bare name is not unique in the file |
| `` `path::Symbol~"exact text"` `` | one statement that matters (a guard, a status write, a formula); text must sit inside the symbol |
| `` `path~"exact text"` `` | no enclosing symbol: CSS rule, template/Blade markup, route line, migration line, config literal |
| `` `path~'text with "quotes"'` `` | same, when the text contains double quotes |
| `` `docs/spec.md::§13.3a` `` | a markdown heading, by its number prefix (or full heading text) |

Rules:
- Path is full from the repo root. Quoted text is copied verbatim from **one** line and occurs once in
  its scope (symbol span, or file for text anchors). Lengthen it until unique.
- Cite the symbol when the claim is about the construct; add `~"text"` only when the sentence is about a
  specific statement. Do not anchor template/style lines of a `.vue`/`.blade.php` file on a script
  symbol: use a text anchor.
- **Forbidden:** typed line numbers (`path:123`, bare `` `:123` ``, ranges `:12-30`, lists `:3,7`),
  "shifted/moved from line N" notes, any line history.

## Resolved form (what the checker writes)

`check --write` turns every token into a markdown link, token as link text, line in the fragment:

```
[`server/src/queue.ts::Scheduler.tick`](../../server/src/queue.ts#L134)
```

This is the reader's click target (VS Code markdown preview, GitHub, Obsidian). The source editor does
not follow it; agents resolve it by grep or `Read` with offset. Writers may leave the plain backtick
form — the next `check --write` wraps it. Never hand-edit the `#L` fragment; edit the token.

## Checker

`tools/bible-cite.py` in this skill. Python 3.9+, stdlib only, read-only on the repo. Run it with
`python3 -I` from the project root:

```bash
T=<skill dir>/tools/bible-cite.py
python3 -I $T --bible docs/bible --repo . scan            # inventory + lint (bare, legacy, malformed)
python3 -I $T --bible docs/bible --repo . check            # resolve every citation, report only
python3 -I $T --bible docs/bible --repo . check --write    # + rewrite links/lines for ok/drifted/new
python3 -I $T --bible docs/bible --repo . check --range <audited>..HEAD   # flag cites into changed files
python3 -I $T --bible docs/bible --repo . range            # commits/files/renames since audited_commit
python3 -I $T --bible docs/bible --repo . links            # bible anchors + repo-file links
python3 -I $T --bible docs/bible --repo . convert [--write]  # legacy path:N -> anchors (migration only)
```

Reports go to `<bible>/_build/run-<date>/` (`check.json` + `check.md`), or `--out DIR`. Exit code is
non-zero when anything needs attention.

**Only the operator runs `--write`.** Agents run `check` into their own scratch (`--out`) to see whether
their tokens resolve.

### Resolution

1. Path: exact repo path. A bare filename (`queue.ts`) may resolve by unique basename; a path with a
   directory must match exactly (a suffix match is reported, not verified).
2. Symbol: graphify `graph.json` when present, **used only for files unchanged since the graph's
   `built_at_commit` (working tree included) and only when the line still contains the name**;
   otherwise grep with per-language definition patterns (ts/js/vue, php/blade, py, md, css, json, yaml),
   strongest pattern tier first, `Class.method` searched inside the class body. A wrong or ambiguous
   class qualifier never falls back to the bare method name.
3. Span: the shorter of (next graph node) and a lexer-aware end — bracket balance skipping strings,
   comments and template literals (brace languages), indentation (py/yaml), next same-level heading (md);
   a one-line definition ends on its line. Spans err short: a too-short span fails a statement anchor
   (reviewed), never passes one.
4. Text: exact substring, matched against the file itself, inside the span (or whole file); two
   occurrences on one line count as two. In `.vue`/`.html`/`.blade.php`, a symbol-anchored statement
   must sit inside a `<script>` block (`misanchored` otherwise).
5. Link: on the resolved form, the link target must equal the resolved path (else `drifted`, and
   `--write` repairs it).

Tokens inside fenced code blocks are examples and are not checked. A token wrapped in a hand-written
link the checker does not own is reported `malformed` (rewriting it would nest links). Line endings
are preserved on `--write`.

Rebuild the graph at HEAD before an update's `check` when graphify is available; with a stale or absent
graph the checker still works, but moved-symbol detection only covers files the graph can vouch for.

### Statuses → who acts

| Status | Meaning | Action |
|---|---|---|
| `ok` | resolves, line unchanged | none |
| `drifted` | resolves, line changed | `--write` fixes the link |
| `new` | resolves, no link yet | `--write` adds the link |
| `moved` | file/symbol/text gone, found uniquely elsewhere | agent confirms the sentence still holds, retypes the path (`--apply-moved` only after review) |
| `ambiguous-symbol` / `ambiguous-text` / `ambiguous-path` / `ambiguous-move` | several matches | agent qualifies the symbol or lengthens the text |
| `misanchored` | statement text lies outside the `<script>` of a SFC | agent drops the symbol, keeps a text anchor |
| `unresolved` / `missing-file` | gone | agent finds the construct the sentence describes, or corrects the sentence, or marks `❓ location unverified` + `> ❓ OPEN:` |
| `bare` / `legacy` / `malformed` | lint | agent rewrites into the grammar (`convert` handles legacy mechanically) |

A citation that is not `ok` after the run is either fixed or visibly marked. `check --mark` appends
` ⚠️UNRESOLVED` after anything still failing; nothing ships looking verified that is not.

### What the checker proves, and what it does not

It proves the cited **construct exists** where the link says. It does not prove the **sentence** is
true of that construct. That is why, after a code change, citations into changed files
(`check --range`) and every non-ok status go to an agent who reads the sentence against the code.
A citation whose file did not change and which resolves `ok` needs no re-reading.

## Migrating a bible with `path:line` citations

1. Snapshot the bible to `_build/archive/<date>-pre-anchors/`.
2. Build the graph **at the commit the citations were written against** (or check it out), then
   `convert --write`: full `path:N` tokens become anchors; bare `` `:N` `` tokens get their file inferred
   from the same line, earlier lines of the block, or the section heading.
3. `check`, then fan out review agents (one per bible file) over everything the script could not
   confirm, **including inferred-file conversions** — file inference is weak in web/view docs.
4. Operator: `check --write`, `links`, a sampled read (8+ claims), stamp, record the baseline.
