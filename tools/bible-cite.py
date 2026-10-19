#!/usr/bin/env python3
"""bible-cite — deterministic citation checker for a project bible.

Citation grammar (inside backticks, one token each):

    `path::Symbol`                 symbol anchor (function, method as Class.method, const, class, md heading)
    `path::Symbol~"exact text"`    statement anchor: exact substring inside the symbol's span
    `path~"exact text"`            text anchor: exact substring, unique in the file (CSS, templates, literals)
    `path~'exact "quoted" text'`   same, single-quoted when the text itself contains double quotes
    [`path::Symbol`](../../path#L134)   resolved form, written by `check --write`: the same token as link
                                        text, line in the fragment (clickable in markdown preview / GitHub).
                                        Writers never type it; the script owns the link and the line.

Legacy forms (`path:N`, `path:N-M`, `path:a,b`, bare `:N`) are converted by `convert`.

Subcommands:
    scan      inventory + lint (bare tokens, legacy forms, malformed anchors)
    convert   legacy -> canonical, using graph.json (must be built at the bible's audited commit)
    check     resolve every canonical citation against the repo at HEAD; --write updates line suffixes
    range     list commits/files/renames since the audited commit, cited files touched, findings docs added

Resolution order: graph.json -> grep with per-language definition patterns. A graph line is used only
when the file is unchanged since the graph's built_at_commit (working tree included) and the line still
names the symbol; otherwise grep decides. Text anchors are always matched against the file itself.

check statuses: ok (line unchanged) | drifted (line moved, --write fixes) | new (no line yet, --write adds)
| moved / ambiguous-move | ambiguous-path / ambiguous-symbol / ambiguous-text | misanchored | unresolved
| missing-file | bare / legacy / malformed (lint). Anything but ok/drifted/new needs a person or agent.

Run with `python3 -I`. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict

# Any file: a path with a letter-led extension, or an extension-less path with a directory part
# (`docker/Dockerfile`). No language list here, so no file type is ever skipped silently.
PATH_RE = r"(?:[\w.@/-]*?[\w@-]\.[A-Za-z]\w*|(?:[\w.@-]+/)+[\w@-][\w.@-]*)"

# canonical: `path::sym`, `path::sym~"text"`, `path~"text"`, each optionally `:NNN`
CANON_RE = re.compile(
    rf"`(?P<path>{PATH_RE})"
    rf"(?:::(?P<sym>[^`~:\"]+?))?"
    rf"(?:~(?:\"(?P<text>[^\"`]+)\"|'(?P<text2>[^'`]+)'))?"
    rf"(?::(?P<line>\d+))?`"
)
TEXT_FORMS = ("text", "text2")
# resolved link form: [`canon`](../../path#L134)
LINK_RE = re.compile(
    rf"\[(?P<tok>`(?P<path>{PATH_RE})(?:::(?P<sym>[^`~:\"]+?))?(?:~(?:\"(?P<text>[^\"`]+)\"|'(?P<text2>[^'`]+)'))?`)\]"
    rf"\((?P<rel>(?:\.\./)*)(?P<lpath>{PATH_RE})#L(?P<line>\d+)\)"
)
# anything in backticks containing `::` or `~"`/`~'` that the canonical regex did not consume
MALFORMED_RE = re.compile(rf"`(?:{PATH_RE})(?:::|~)[^`]*`")
# legacy: `path:N`, `path:N-M`, `path:a,b,c` (and N–M with en dash)
LEGACY_RE = re.compile(rf"`(?P<path>{PATH_RE}):(?P<nums>\d+(?:[-–]\d*)?(?:,\s?\d+(?:[-–]\d*)?)*)`")
# bare: `:N`, `:N-M`, `:a,b`
BARE_RE = re.compile(r"`:(?P<nums>\d+(?:[-–]\d*)?(?:,\s?\d+(?:[-–]\d*)?)*)`")  # `:12-` (open range) allowed
SUFFIX_MARK = " ⚠️UNRESOLVED"
EVIDENCE_STOP = {"the", "and", "for", "null", "true", "false", "string", "number", "boolean", "void", "const",
                 "let", "var", "function", "return", "await", "async", "this", "import", "export", "from",
                 "class", "div", "span", "style", "template", "script"}
HEADING_NUM_RE = re.compile(r"^§?\s*(\d+(?:\.\d+)*[a-z]*)\b")
SYM_LABEL_RE = re.compile(r"^\.?[\w$]+(?:\(\))?$")
TEST_FILE_RE = re.compile(r"\.(?:test|spec)\.[jt]sx?$|/__tests__/|/tests?/")

# Per language: tiers of definition patterns, strongest first. grep_def returns the first tier that hits,
# so a keyword-led definition beats a shorthand method / object key / call that happens to look alike.
DEF_PATTERNS = {
    "ts": [
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*{n}\b",
        r"^\s*(?:export\s+)?(?:declare\s+)?(?:const|let|var)\s+{n}\b",
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+{n}\b",
        r"^\s*(?:export\s+)?(?:interface|type|enum)\s+{n}\b",
        None,
        r"^\s*(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*{n}\s*(?:<[^>]*>)?\s*\((?!.*;\s*$)",
        r"^\s*(?:(?:public|private|protected|static|readonly)\s+)*{n}\s*[?!]?\s*[:=](?!=)",
    ],
    "php": [
        r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+{n}\b",
        r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+{n}\b",
        r"^\s*(?:public\s+|private\s+|protected\s+)?const\s+{n}\b",
        r"^\s*(?:(?:public|private|protected|static|readonly)\s+)*(?:\??[\w\\|]+\s+)?\${n}\s*[=;]",
        None,
        r"^\s*['\"]{n}['\"]\s*=>",
    ],
    "py": [r"^\s*(?:async\s+)?def\s+{n}\b", r"^\s*class\s+{n}\b", r"^{n}\s*[:=]"],
    "json": [r"^\s*\"{n}\"\s*:"],
    # Markup has no symbols: cite it with text anchors.
    "markup": [],
    # Any other language (C#, Java, Kotlin, Go, Rust, Swift, C/C++, Ruby, shell, SQL, ...).
    "generic": [
        r"^\s*(?:[\w@#\[\]]+\s+)*?(?:class|struct|record|interface|enum|trait|protocol|object|module|namespace"
        r"|typealias|type|fn|func|fun|def|function|sub|proc|impl)\s+{n}\b",
        r"^\s*func\s+\([^)]*\)\s*{n}\b",
        r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|abstract|sealed|async|partial|extern"
        r"|unsafe|new|final|synchronized|open|suspend|inline|readonly|required|pub(?:\([^)]*\))?|export|const)\s+)+"
        r"(?:[\w<>\[\],.?()*&:]+\s+)?{n}\s*(?:<[^>]*>)?\s*[({{=:;]",
        r"^\s*(?:const|let|var|val|static)\s+(?:mut\s+)?(?:[\w<>\[\],.?]+\s+)?{n}\s*[=:;]",
        r"(?i:^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|FUNCTION|PROCEDURE|INDEX|TRIGGER|TYPE)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?)[`\"\[]?{n}\b",
        r"^\s*{n}\s*\(\)\s*\{{",
        None,
        r"^\s*(?!(?:return|await|new|throw|if|while|for|foreach|switch|using|else|case|yield|var|let|const|val|goto)\b)"
        r"(?:[\w<>\[\],.?*&]+\s+)+{n}\s*(?:<[^>]*>)?\s*\((?!.*;\s*$)",
    ],
    "yaml": [r"^\s*{n}\s*:"],
    "md": [r"^#{{1,6}}\s+(?:§\s*)?{n}(?!\w|\.\w)"],
    "css": [r"^\s*{n}\s*[,{{]"],
}
LANG_BY_EXT = {
    "ts": "ts", "tsx": "ts", "js": "ts", "mjs": "ts", "cjs": "ts", "vue": "ts",
    "php": "php", "blade.php": "php", "py": "py", "md": "md", "css": "css", "scss": "css",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "html": "markup", "htm": "markup", "xml": "markup", "cshtml": "markup", "razor": "markup", "svg": "markup",
    "txt": "markup", "csv": "markup",
}


@dataclass
class Cite:
    md: str
    mdline: int
    raw: str
    path: str
    sym: str | None = None
    text: str | None = None
    line: int | None = None
    kind: str = "canon"  # canon | legacy | bare
    start: int = 0
    end: int = 0
    # resolution
    status: str = ""
    resolved_path: str | None = None
    resolved_line: int | None = None
    note: str = ""
    candidates: list = field(default_factory=list)
    new_raw: str | None = None
    link_target: str | None = None  # rel prefix + path of a resolved link, compared on check


# ---------------------------------------------------------------- repo helpers

def sh(cmd, cwd, must=False):
    if cmd[0] == "git":
        cmd = ["git", "-c", "core.quotepath=off"] + cmd[1:]
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if must and r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout


def git_commit(ref, cwd):
    """Full sha for ref, or exit: a mistyped baseline must not read as an empty range."""
    return sh(["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"], cwd, must=True).strip()


def git_root(path):
    out = sh(["git", "rev-parse", "--show-toplevel"], path).strip()
    return out or os.path.abspath(path)


class Repo:
    def __init__(self, root):
        self.root = root
        files = sh(["git", "ls-files"], root).split("\n")
        self.files = [f for f in files if f]
        self.fileset = set(self.files)
        self.by_base = defaultdict(list)
        for f in self.files:
            self.by_base[os.path.basename(f)].append(f)
        self._lines = {}

    def head(self):
        return sh(["git", "rev-parse", "--short", "HEAD"], self.root).strip()

    def resolve_path(self, p, prefer=None):
        """Short or full path -> unique repo path, or list of candidates.
        prefer: Counter of directories cited elsewhere in the same bible doc; breaks ties when one
        candidate's directory is cited there and the others are not."""
        if p in self.fileset:
            return p, []
        cands = [f for f in self.by_base.get(os.path.basename(p), []) if f.endswith("/" + p) or f == p]
        if len(cands) == 1:
            return cands[0], []
        if prefer and len(cands) > 1:
            scored = sorted(((prefer.get(os.path.dirname(f), 0), f) for f in cands), reverse=True)
            if scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                return scored[0][1], ["preferred:" + scored[0][1]]
        return None, cands

    def lines(self, p):
        if p not in self._lines:
            try:
                with open(os.path.join(self.root, p), encoding="utf-8", errors="replace") as fh:
                    self._lines[p] = fh.read().split("\n")
            except OSError:
                self._lines[p] = None
        return self._lines[p]


# ---------------------------------------------------------------- graph

def norm_sym(s):
    s = s.strip()
    s = re.sub(r"\(\)$", "", s)
    s = s.lstrip(".")
    return s.lower()


class Graph:
    def __init__(self, path):
        with open(path) as fh:
            g = json.load(fh)
        self.commit = g.get("built_at_commit", "")
        self.dirty = None  # files changed since built_at_commit; None = unknown -> trust no graph line
        self.live = set()  # files tracked at HEAD
        self.by_file = defaultdict(list)  # file -> [(line, norm, label, id)]
        self.by_norm = defaultdict(list)  # norm -> [(file, line, id)]
        self.methods_of = defaultdict(set)  # class id -> {method id}
        self.node = {}
        for n in g["nodes"]:
            loc = n.get("source_location") or ""
            m = re.match(r"L(\d+)", loc)
            if not m:
                continue
            line = int(m.group(1))
            f = n["source_file"]
            label = n["label"]
            if line == 1 and f.endswith(label):
                continue  # file node (label may carry a parent dir when basenames collide)
            if not f.endswith(".md") and not SYM_LABEL_RE.match(label):
                continue  # package deps, destructuring blobs, prose labels: not citable symbols
            nm = norm_sym(label)
            self.node[n["id"]] = (f, line, label)
            self.by_file[f].append((line, nm, label, n["id"]))
            self.by_norm[nm].append((f, line, n["id"]))
        for f in self.by_file:
            self.by_file[f].sort()
        for l in g.get("links", []):
            if l.get("relation") == "method":
                self.methods_of[l["source"]].add(l["target"])

    def trusted(self, f):
        return self.dirty is not None and f not in self.dirty and f in self.live

    def find(self, f, sym):
        """-> list of (line, id) for sym in file f. Qualified 'Class.method' honoured.
        Callers must check trusted(f) first; graph lines for changed files are stale.
        In .md files the symbol is a heading: '§13.3a' / '13.3a' matches by number prefix, else whole text."""
        if f.endswith(".md"):
            m = HEADING_NUM_RE.match(sym.strip())
            if m:
                num = m.group(1).lower()
                return [(ln, nid) for (ln, nm, _, nid) in self.by_file.get(f, [])
                        if (HEADING_NUM_RE.match(nm) or [None, ""])[0] and HEADING_NUM_RE.match(nm).group(1).lower() == num]
            return [(ln, nid) for (ln, nm, _, nid) in self.by_file.get(f, []) if nm == norm_sym(sym)]
        parts = [norm_sym(p) for p in sym.split(".") if p.strip()]
        if not parts:
            return []
        last = parts[-1]
        hits = [(ln, nid) for (ln, nm, _, nid) in self.by_file.get(f, []) if nm == last]
        if len(parts) >= 2 and hits:  # a wrong qualifier must not fall back to the bare name
            cls = parts[-2]
            cls_ids = {nid for (ln, nm, _, nid) in self.by_file.get(f, []) if nm == cls}
            allowed = set()
            for c in cls_ids:
                allowed |= self.methods_of.get(c, set())
            hits = [(ln, nid) for (ln, nid) in hits if nid in allowed or nid.endswith(f"_{cls}_{last}")]
        return hits

    def find_anywhere(self, sym):
        parts = [norm_sym(p) for p in sym.split(".") if p.strip()]
        if not parts:
            return []
        hits = [(f, ln, nid) for (f, ln, nid) in self.by_norm.get(parts[-1], []) if self.trusted(f)]
        non_test = [h for h in hits if not TEST_FILE_RE.search(h[0])]
        return non_test or hits

    def enclosing(self, f, line):
        """Nearest node at or before line in file f -> (line, label, id) or None."""
        best = None
        for (ln, nm, label, nid) in self.by_file.get(f, []):
            if ln <= line:
                best = (ln, label, nid)
            else:
                break
        return best

    def span_end(self, f, start_line, nid=None):
        """Next graph node minus one, skipping the node's own methods (a class spans its members).
        Not a true end (code between nodes is included); callers take the minimum with grep_span_end."""
        if not self.trusted(f):
            return None
        members = self.methods_of.get(nid, set()) if nid else set()
        for (ln, _, _, oid) in self.by_file.get(f, []):
            if ln > start_line and oid not in members:
                return ln - 1
        return None

    def qualified_label(self, nid):
        """'.tick()' under Scheduler -> 'Scheduler.tick'; 'foo()' -> 'foo'; md heading '13.3a Foo' -> '§13.3a'."""
        f, ln, label = self.node[nid]
        if f.endswith(".md"):
            m = HEADING_NUM_RE.match(label)
            return "§" + m.group(1) if m else label.strip()
        base = re.sub(r"\(\)$", "", label)
        if base.startswith("."):
            base = base[1:]
            for cid, ms in self.methods_of.items():
                if nid in ms and cid in self.node:
                    cls = re.sub(r"\(\)$", "", self.node[cid][2])
                    return f"{cls}.{base}"
        return base


# ---------------------------------------------------------------- grep fallback

def lang_of(path):
    if path.endswith(".blade.php"):
        return "php"
    base = os.path.basename(path)
    if "." not in base:
        return "generic"
    return LANG_BY_EXT.get(base.rsplit(".", 1)[-1].lower(), "generic")


def grep_def(lines, path, sym):
    lang = lang_of(path)
    if not lang or lines is None:
        return []
    if lang == "md":
        m = HEADING_NUM_RE.match(sym.strip())
        name = re.escape(m.group(1) if m else sym.strip())
    else:
        name = re.escape(sym.split(".")[-1].strip().rstrip("()"))
    lo, hi = 1, len(lines)
    parts = [x.strip() for x in sym.split(".") if x.strip()]
    if lang not in ("md", "json", "yaml") and len(parts) >= 2:
        cls = grep_def(lines, path, parts[-2])
        if len(cls) != 1:
            return []  # class missing or ambiguous: never fall back to the bare method name
        lo, hi = cls[0] + 1, grep_span_end(lines, path, cls[0])
    tiers, cur = [], []
    for p in DEF_PATTERNS[lang] + [None]:
        if p is None:
            tiers.append(cur)
            cur = []
        else:
            cur.append(re.compile(p.format(n=name)))
    for pats in tiers:
        hits = [i for i in range(lo, hi + 1) if any(p.search(lines[i - 1]) for p in pats)]
        if hits:
            return hits
    return []


def grep_span_end(lines, path, start):
    """End of the construct defined at `start`, without a graph: balanced brackets for brace languages,
    indentation for Python/YAML, next heading of the same or higher level for markdown. Errs short: a span
    that ends too early makes a statement anchor fail (reviewed), never pass wrongly."""
    lang = lang_of(path)
    n = len(lines)
    if lang == "md":
        lvl = len(lines[start - 1]) - len(lines[start - 1].lstrip("#"))
        for i in range(start + 1, n + 1):
            h = re.match(r"(#{1,6})\s", lines[i - 1])
            if h and len(h.group(1)) <= lvl:
                return i - 1
        return n
    if lang in ("py", "yaml"):
        ind = len(lines[start - 1]) - len(lines[start - 1].lstrip())
        for i in range(start + 1, n + 1):
            l = lines[i - 1]
            if l.strip() and len(l) - len(l.lstrip()) <= ind:
                return i - 1
        return n
    depth, opened, state = 0, False, None  # state: None | "'" | '"' | "`" | "/*"
    hash_comments = lang in ("php", "generic")  # also C# #region, shell, Ruby; Rust #[attr] is kept below
    for i in range(start, n + 1):
        l, j, code = lines[i - 1], 0, []
        while j < len(l):
            ch, two = l[j], l[j:j + 2]
            if state == "/*":
                if two == "*/":
                    state, j = None, j + 2
                    continue
            elif state in ("'", '"', "`"):
                if ch == "\\":
                    j += 2
                    continue
                if ch == state:
                    state = None
            elif two == "/*":
                state, j = "/*", j + 2
                continue
            elif two == "//" or (hash_comments and ch == "#" and not l.startswith("#[", j)):
                break
            elif ch in "'\"`":
                state = ch
            else:
                code.append(ch)
                if ch in "{([":
                    depth += 1
                    opened = True
                elif ch in "})]":
                    depth -= 1
            j += 1
        if state in ("'", '"'):
            state = None  # unterminated quote on a line: not a multi-line string in these languages
        text = "".join(code).rstrip()
        nxt = next((x.strip() for x in lines[i:i + 3] if x.strip()), "")
        allman = nxt.startswith("{")  # C#/Java style: the body's brace sits on the next line
        if opened and depth <= 0 and not allman:
            return i
        if not opened and state is None:
            if text.endswith(";") or (i == start and not allman
                                      and not re.search(r"(=>?|\||&|\+|\(|\?|:|\{|\[|\bextends|\bimplements)$", text)):
                return i
    return n


def names_symbol(lines, ln, sym):
    """Guard against a stale graph: the cited line must still contain the symbol's name."""
    if not (1 <= ln <= len(lines)):
        return False
    m = HEADING_NUM_RE.match(sym.strip())
    name = m.group(1) if m else sym.split(".")[-1].strip().rstrip("()")
    return re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", lines[ln - 1]) is not None


def find_text(lines, text, lo=1, hi=None):
    hi = hi or len(lines)
    hits = []
    for i in range(lo, min(hi, len(lines)) + 1):
        hits += [i] * lines[i - 1].count(text)
    return hits


# ---------------------------------------------------------------- bible scanning

def bible_files(bible):
    out = []
    for dp, dn, fn in os.walk(bible):
        if "/_build" in dp or dp.endswith("/_build"):
            continue
        for f in fn:
            if f.endswith(".md"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def scan_file(bible, p):
    rel = os.path.relpath(p, bible)
    cites = []
    fence = None
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        for i, line in enumerate(fh.read().split("\n"), 1):
            f = re.match(r"\s*(```+|~~~+)", line)
            if f and (fence is None or f.group(1)[0] == fence[0]):
                fence = None if fence else f.group(1)
                continue
            if fence:
                continue  # code examples are not citations
            spans = []
            for m in LINK_RE.finditer(line):
                spans.append((m.start(), m.end()))
                cites.append(Cite(rel, i, m.group(0), m.group("path"), m.group("sym"), m.group("text") or m.group("text2"),
                                  int(m.group("line")), "canon", start=m.start(), end=m.end(),
                                  link_target=m.group("rel") + m.group("lpath")))
            for m in CANON_RE.finditer(line):
                if not (m.group("sym") or m.group("text") or m.group("text2")):
                    continue  # bare path mention or legacy, handled below
                if any(a <= m.start() < b for a, b in spans):
                    continue  # link text of a resolved form, already recorded
                spans.append((m.start(), m.end()))
                if line[m.start() - 1:m.start()] == "[" and line[m.end():m.end() + 2] == "](":
                    # hand-written link around a token: --write would nest links
                    cites.append(Cite(rel, i, m.group(0), "", None, None, None, "malformed",
                                      start=m.start(), end=m.end(), note="token inside a link the checker does not own"))
                    continue
                cites.append(Cite(rel, i, m.group(0), m.group("path"), m.group("sym"), m.group("text") or m.group("text2"),
                                  int(m.group("line")) if m.group("line") else None, "canon",
                                  start=m.start(), end=m.end()))
            # malformed: a backtick span that looks like a citation but did not parse (e.g. quotes inside quotes)
            for m in MALFORMED_RE.finditer(line):
                if any(a <= m.start() < b for a, b in spans):
                    continue
                cites.append(Cite(rel, i, m.group(0), "", None, None, None, "malformed", start=m.start(), end=m.end()))
            for m in LEGACY_RE.finditer(line):
                cites.append(Cite(rel, i, m.group(0), m.group("path"), None, None, None, "legacy",
                                  note=m.group("nums")))
            for m in BARE_RE.finditer(line):
                cites.append(Cite(rel, i, m.group(0), "", None, None, None, "bare", note=m.group("nums")))
    return cites


# ---------------------------------------------------------------- resolve

def looks_like_code(c: Cite, repo: Repo):
    """A slash-less token that names no file in the repo (`button.pill::before`, `config.port:3`) is code
    in prose, not a citation. Citations use full paths, so only root files lack a '/'."""
    if not c.path or "/" in c.path:
        return False
    rp, cands = repo.resolve_path(c.path)
    return rp is None and not cands


def resolve(c: Cite, repo: Repo, graph: Graph | None):
    rp, cands = repo.resolve_path(c.path)
    if rp is None:
        if cands:
            c.status, c.candidates, c.note = "ambiguous-path", cands, "short path matches several files"
        else:
            # moved file? look the symbol up graph-wide
            if graph and c.sym:
                anywhere = graph.find_anywhere(c.sym)
                if len(anywhere) == 1:
                    f, ln, nid = anywhere[0]
                    c.status, c.resolved_path, c.resolved_line = "moved", f, ln
                    c.note = f"file gone; symbol found uniquely in {f}"
                    return c
                if anywhere:
                    c.status, c.candidates = "ambiguous-move", [f"{f}:{ln}" for f, ln, _ in anywhere]
                    return c
            c.status, c.note = "missing-file", "file not in repo"
        return c
    if "/" in c.path and rp != c.path:
        c.status, c.candidates = "ambiguous-path", [rp]
        c.note = f"typed path is not in the repo; only a suffix match ({rp})"
        return c
    c.resolved_path = rp
    lines = repo.lines(rp)
    if lines is None:
        c.status = "missing-file"
        return c
    sym_line, span_hi = None, None
    if c.sym:
        hits = graph.find(rp, c.sym) if graph and graph.trusted(rp) else []
        hits = [(ln, nid) for ln, nid in hits if names_symbol(lines, ln, c.sym)]
        src = "graph"
        if not hits:
            hits = [(ln, None) for ln in grep_def(lines, rp, c.sym)]
            src = "grep"
        if len(hits) == 0:
            if graph:
                anywhere = graph.find_anywhere(c.sym)
                if len(anywhere) == 1 and anywhere[0][0] != rp:
                    f, ln, _ = anywhere[0]
                    c.status, c.resolved_path, c.resolved_line = "moved", f, ln
                    c.note = f"symbol not in {rp}; found uniquely in {f}"
                    return c
                if len(anywhere) > 1:
                    c.status, c.candidates = "ambiguous-move", [f"{f}:{ln}" for f, ln, _ in anywhere]
                    c.note = f"symbol not in {rp}; several elsewhere"
                    return c
            c.status, c.note = "unresolved", (f"symbol not found ({src})" if lang_of(rp) != "markup"
                                               else "markup has no symbols; use a text anchor")
            return c
        if len(hits) > 1:
            c.status, c.candidates = "ambiguous-symbol", [ln for ln, _ in hits]
            c.note = "qualify the symbol (Class.method) or use a text anchor"
            return c
        sym_line = hits[0][0]
        g_hi = graph.span_end(rp, sym_line, hits[0][1]) if graph and src == "graph" else None
        span_hi = min(x for x in (g_hi, grep_span_end(lines, rp, sym_line)) if x)
    if c.text:
        lo = sym_line or 1
        hi = span_hi if c.sym else len(lines)
        th = find_text(lines, c.text, lo, hi)
        if len(th) == 0 and not c.sym:
            sib = []
            d = os.path.dirname(rp)
            for f in repo.files:
                if os.path.dirname(f) == d and f != rp and not TEST_FILE_RE.search(f):
                    fl = repo.lines(f)
                    if fl:
                        sib += [(f, n) for n in find_text(fl, c.text)]
            if len(sib) == 1:
                c.status, c.resolved_path, c.resolved_line = "moved", sib[0][0], sib[0][1]
                c.note = f"text gone from {rp}; found uniquely in {sib[0][0]}"
                return c
            if sib:
                c.status, c.candidates, c.note = "ambiguous-move", [f"{f}:{n}" for f, n in sib], "text gone; several siblings"
                return c
        if len(th) == 0:
            c.status, c.note = "unresolved", "text not found" + (" in symbol span" if c.sym else " in file")
            return c
        if len(th) > 1:
            c.status, c.candidates, c.note = "ambiguous-text", th, "text occurs more than once; lengthen it"
            return c
        c.resolved_line = th[0]
        if c.sym and not in_script(lines, rp, th[0]):
            c.status, c.note = "misanchored", "text is past </script>; drop the symbol, keep the text anchor"
            return c
    else:
        c.resolved_line = sym_line
    if c.line is None:
        c.status = "new"
    elif c.line == c.resolved_line:
        c.status = "ok"
    else:
        c.status = "drifted"
    return c


def quote(text):
    return f'"{text}"' if '"' not in text else f"'{text}'"


def render(c: Cite, path=None, line=None, rel_prefix=""):
    """Backtick token; with a line, the link form [`token`](<rel>path#Lnnn)."""
    path = path or c.path
    s = f"`{path}"
    if c.sym:
        s += f"::{c.sym}"
    if c.text:
        s += "~" + quote(c.text)
    s += "`"
    if line:
        return f"[{s}]({rel_prefix}{path}#L{line})"
    return s


# ---------------------------------------------------------------- convert (legacy -> canonical)

def parse_nums(nums):
    out = []
    for part in re.split(r",\s?", nums):
        a = [x for x in re.split(r"[-–]", part) if x]
        out.append((int(a[0]), int(a[-1])))
    return out


def anchor_ok(t):
    return len(t) >= 8 and "`" not in t and not ('"' in t and "'" in t)


def unique_line_in(lines, a, b, lo, hi):
    """First line in a..b whose stripped text is unique within lo..hi -> (line_no, text) or None."""
    for n in range(a, min(b, len(lines)) + 1):
        t = lines[n - 1].strip()
        if anchor_ok(t) and len(find_text(lines, t, lo, hi)) == 1:
            return n, t
    return None


DEF_ON_LINE_RE = re.compile(r"^\s*(?:export\s+)?(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)\b")
CSS_SEL_RE = re.compile(r"^[^\s/@].*\{\s*$")


def script_end(lines, path):
    """Last line of the <script> section in .vue/.html/.blade.php; EOF for other files."""
    if not re.search(r"\.(?:vue|html|blade\.php|svelte)$", path):
        return len(lines)
    ends = [i for i, l in enumerate(lines, 1) if re.search(r"</script", l, re.I)]
    return ends[-1] if ends else len(lines)


def in_script(lines, path, ln):
    """True when line ln lies inside a <script> block. Non-markup files, and markup files without any
    <script>, count as all script."""
    if not re.search(r"\.(?:vue|html|blade\.php|svelte)$", path):
        return True
    if not any(re.search(r"<script\b", l, re.I) for l in lines):
        return True
    inside = False
    for i, l in enumerate(lines, 1):
        if re.search(r"<script\b", l, re.I):
            inside = True
        if i == ln:
            return inside
        if re.search(r"</script", l, re.I):
            inside = False
    return False


def css_enclosing(lines, a):
    for n in range(a, 0, -1):
        if CSS_SEL_RE.match(lines[n - 1]):
            return n, lines[n - 1].rstrip().rstrip("{").strip()
    return None


def evidence(context, *needles):
    """True when any backticked identifier in the sentence appears in the anchor text/symbol."""
    words = set()
    for span in re.findall(r"`([^`]+)`", context):
        words |= {w for w in re.findall(r"[A-Za-z_$][\w$-]{2,}", span) if w.lower() not in EVIDENCE_STOP}
    hay = " ".join(n for n in needles if n)
    return any(w in hay for w in words)


def convert_one(c: Cite, paths, repo: Repo, graph: Graph, context: str, prefer=None):
    """Build canonical token(s) for a legacy cite at the graph's commit, trying each candidate
    file in order (explicit path, then inferred ones). A candidate wins when its lines are in range
    and the sentence names something on the anchored line/symbol; failing that, the first in-range
    candidate. Returns (new_raw, status, note, evidence_found)."""
    files = []
    for path in paths:
        rp, cands = repo.resolve_path(path, prefer)
        if rp:
            files.append((rp, "preferred" if cands else ""))
        else:
            files.extend((f, "candidate") for f in cands)
    if not files:
        return None, "missing-file", ", ".join(paths), False
    results = []
    for rp, how in files:
        r = convert_in_file(c, rp, repo, graph, context)
        if r[0] and r[3]:
            return r[0], r[1], (how + " " + rp + "; " if how else "") + r[2], True
        results.append((r, rp, how))
    for r, rp, how in results:
        if r[0]:
            return r[0], r[1], (how + " " + rp + "; " if how else "") + r[2], False
    r, rp, how = results[0]
    if len(files) > 1 and r[1] in ("out-of-range", "no-anchor"):
        return None, "ambiguous-path", "no candidate fits: " + "; ".join(f"{rp}: {r[1]}" for r, rp, _ in results), False
    return r


def convert_in_file(c: Cite, rp, repo: Repo, graph: Graph, context: str):
    lines = repo.lines(rp)
    if lines is None:
        return None, "missing-file", rp, False
    notes = []
    toks, worst, ev = [], "converted", False
    for (a, b) in parse_nums(c.note):
        if a > len(lines):
            return None, "out-of-range", f"{rp} has {len(lines)} lines", False
        enc = graph.enclosing(rp, a)
        if enc and a > script_end(lines, rp):
            enc = None  # template / style section of a single-file component: no script symbol encloses it
        ltxt = lines[a - 1].strip()
        own = DEF_ON_LINE_RE.match(lines[a - 1]) if a <= script_end(lines, rp) else None
        if own and (not enc or enc[0] != a) and len(grep_def(lines, rp, own.group(1))) == 1:
            toks.append(f"`{rp}::{own.group(1)}`")  # the line defines a symbol the graph lacks (const, type, ...)
            ev = ev or evidence(context, own.group(1), ltxt)
            if b != a:
                notes.append(f"range {a}-{b} anchored at {a}")
            continue
        if enc and enc[0] == a:
            sym = graph.qualified_label(enc[2])
            toks.append(f"`{rp}::{sym}`")
            ev = ev or evidence(context, sym, ltxt)
        elif enc:
            sym = graph.qualified_label(enc[2])
            hi = graph.span_end(rp, enc[0]) or len(lines)
            u = unique_line_in(lines, a, b, enc[0], hi)
            if u:
                toks.append(f"`{rp}::{sym}~{quote(u[1])}`")
                ev = ev or evidence(context, sym, u[1])
            else:
                toks.append(f"`{rp}::{sym}`")
                notes.append(f"L{a} widened to symbol {sym}")
                worst = "widened"
                ev = ev or evidence(context, sym, ltxt)
        else:
            u = unique_line_in(lines, a, b, 1, len(lines))
            if u:
                toks.append(f"`{rp}~{quote(u[1])}`")
                ev = ev or evidence(context, u[1])
            elif lang_of(rp) == "css" and css_enclosing(lines, a):
                n, sel = css_enclosing(lines, a)
                if len(find_text(lines, sel)) == 1:
                    toks.append(f"`{rp}~{quote(sel)}`")
                    notes.append(f"L{a} widened to selector")
                    worst = "widened"
                    ev = ev or evidence(context, sel, ltxt)
                else:
                    return None, "no-anchor", f"L{a}: selector {sel!r} not unique", False
            else:
                return None, "no-anchor", f"L{a}: no enclosing symbol and no unique line in {a}-{b}", False
        if b != a:
            notes.append(f"range {a}-{b} anchored at {a}")
    return ", ".join(toks), worst, "; ".join(notes), ev


PATH_MENTION_RE = re.compile(rf"`({PATH_RE})(?:::|~|:|`)")


def infer_bare_files(line_text, pos, src, i):
    """Candidate files for a bare `:N`, nearest first: path mentions before it on the same line,
    then in the previous lines of the same block, then the nearest heading above that names a file.
    Test files are dropped unless the sentence talks about tests."""
    cands = []
    cands += [m.group(1) for m in reversed(list(PATH_MENTION_RE.finditer(line_text[:pos])))]
    for j in range(i - 2, -1, -1):
        pl = src[j]
        if not pl.strip() or pl.startswith("#"):
            break
        cands += [m.group(1) for m in reversed(list(PATH_MENTION_RE.finditer(pl)))]
    for j in range(i - 2, -1, -1):
        if src[j].startswith("#"):
            cands += [m.group(1) for m in PATH_MENTION_RE.finditer(src[j])]
            break
    talks_tests = re.search(r"\btests?\b|covered by", line_text[max(0, pos - 120):pos + 40], re.I)
    out = []
    for f in cands:
        if f in out:
            continue
        if TEST_FILE_RE.search(f) and not talks_tests:
            continue
        out.append(f)
    return out


def cmd_convert(args, repo, graph, bible):
    if graph is None:
        sys.exit("convert needs graph.json")
    head = sh(["git", "rev-parse", "HEAD"], repo.root).strip()
    if graph.commit and graph.commit != head:
        print(f"WARN graph built at {graph.commit[:7]}, HEAD is {head[:7]}; run `graphify update .` first", file=sys.stderr)
    report = []
    for p in bible_files(bible):
        rel = os.path.relpath(p, bible)
        with open(p, encoding="utf-8") as fh:
            src = fh.read().split("\n")
        # directories this doc cites by full path: tie-breaker for short paths
        prefer = defaultdict(int)
        for m in PATH_MENTION_RE.finditer("\n".join(src)):
            rp, _ = repo.resolve_path(m.group(1))
            if rp and "/" in m.group(1):
                prefer[os.path.dirname(rp)] += 1
        out = []
        for i, line in enumerate(src, 1):
            new = line

            def repl_legacy(m):
                c = Cite(rel, i, m.group(0), m.group("path"), kind="legacy", note=m.group("nums"))
                ctx = line[max(0, m.start() - 160): m.end() + 160]
                tok, st, note, ev = convert_one(c, [m.group("path")], repo, graph, ctx, prefer)
                # same commit, file named explicitly: location identity is preserved by construction;
                # review only failures and directory-preferred short paths without context evidence
                review = tok is None or ("preferred" in note and not ev)
                report.append({"md": rel, "mdline": i, "old": m.group(0), "new": tok, "status": st,
                               "note": note, "evidence": ev, "needs_review": review})
                return tok if tok else m.group(0)

            new = LEGACY_RE.sub(repl_legacy, new)

            def repl_bare(m):
                fs = infer_bare_files(new, m.start(), src, i)
                f, how = (fs[0], "inferred") if fs else (None, "none")
                c = Cite(rel, i, m.group(0), f or "", kind="bare", note=m.group("nums"))
                if not f:
                    report.append({"md": rel, "mdline": i, "old": m.group(0), "new": None, "status": "bare-nofile",
                                   "note": "no preceding path mention", "evidence": False, "needs_review": True})
                    return m.group(0)
                ctx = new[max(0, m.start() - 160): m.end() + 160]
                tok, st, note, ev = convert_one(c, fs, repo, graph, ctx, prefer)
                # inferred file: trust only when the sentence names something on the anchored line/symbol
                review = tok is None or not ev
                report.append({"md": rel, "mdline": i, "old": m.group(0), "new": tok, "status": st,
                               "note": f"file inferred from {fs[:3]}; {note}", "evidence": ev, "needs_review": review})
                return tok if tok else m.group(0)

            new = BARE_RE.sub(repl_bare, new)
            out.append(new)
        if args.write and out != src:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out))
    write_report(args, "convert", report, bible)


# ---------------------------------------------------------------- check

def cmd_check(args, repo, graph, bible):
    head = sh(["git", "rev-parse", "HEAD"], repo.root).strip()
    if graph and graph.dirty is None:
        print("WARN graph has no usable built_at_commit; every symbol is resolved by grep", file=sys.stderr)
    elif graph and graph.dirty:
        print(f"WARN graph built at {graph.commit[:7]}, HEAD is {head[:7]}; {len(graph.dirty)} changed file(s) "
              "resolved by grep, moved-symbol search skips them (rebuild the graph to cover them)", file=sys.stderr)
    changed = set()
    if args.range:
        a, _, b = args.range.partition("..")
        git_commit(a, repo.root)
        git_commit(b or "HEAD", repo.root)
        changed = set(sh(["git", "diff", "--name-only", "--no-renames", args.range], repo.root, must=True).split("\n")) - {""}
    all_cites = []
    for p in bible_files(bible):
        cites = [c for c in scan_file(bible, p) if not looks_like_code(c, repo)]
        rel = os.path.relpath(repo.root, os.path.dirname(p))
        prefix = "" if rel == "." else rel + "/"
        for c in cites:
            if c.kind != "canon":
                c.status = c.kind if c.kind == "malformed" else ("legacy" if c.kind == "legacy" else "bare")
                continue
            resolve(c, repo, graph)
            if c.status == "ok" and c.link_target and c.link_target != prefix + (c.resolved_path or ""):
                c.status, c.note = "drifted", f"link target {c.link_target} is not {prefix}{c.resolved_path}"
            if changed and c.resolved_path in changed:
                c.note = (c.note + "; " if c.note else "") + "file changed in range"
        all_cites.extend(cites)
        if args.write or args.mark:
            rewrite_file(p, cites, args, prefix)
    rows = [asdict(c) for c in all_cites]
    for r in rows:
        r.pop("new_raw", None)
    write_report(args, "check", rows, bible, extra={"head": head[:7], "graph_commit": (graph.commit[:7] if graph else None),
                                                     "range": args.range})
    bad = sum(1 for c in all_cites if c.status not in ("ok", "drifted", "new"))
    if bad:
        print(f"\n{bad} citation(s) need attention (not ok/drifted/new)", file=sys.stderr)
    return 1 if bad else 0


def rewrite_file(p, cites, args, rel_prefix=""):
    with open(p, encoding="utf-8", newline="") as fh:
        src = fh.read().split("\n")
    by_line = defaultdict(list)
    for c in cites:
        by_line[c.mdline].append(c)
    changed = False
    for ln, cs in by_line.items():
        line = src[ln - 1]
        # replace by recorded span, right to left, so earlier offsets stay valid
        for c in sorted((c for c in cs if c.kind == "canon"), key=lambda c: -c.start):
            if line[c.start:c.end] != c.raw:
                continue  # line changed under us; skip rather than guess
            new = None
            tail = line[c.end:]
            if args.write and c.status in ("ok", "drifted", "new"):
                new = render(c, c.resolved_path, c.resolved_line, rel_prefix)
            elif args.write and args.apply_moved and c.status == "moved":
                new = render(c, c.resolved_path, c.resolved_line, rel_prefix)
            elif args.mark and c.status not in ("ok", "drifted", "new"):
                if not tail.startswith(SUFFIX_MARK):
                    new = c.raw + SUFFIX_MARK
            good = c.status in ("ok", "drifted", "new") or (args.apply_moved and c.status == "moved")
            if args.write and good and tail.startswith(SUFFIX_MARK):
                tail = tail[len(SUFFIX_MARK):]
                new = new or c.raw
            elif new is None or new == c.raw:
                continue
            line = line[:c.start] + new + tail
            changed = True
        src[ln - 1] = line
    if changed:
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(src))


# ---------------------------------------------------------------- scan / range

def cmd_scan(args, repo, graph, bible):
    rows = []
    for p in bible_files(bible):
        for c in (c for c in scan_file(bible, p) if not looks_like_code(c, repo)):
            rows.append({"md": c.md, "mdline": c.mdline, "kind": c.kind, "raw": c.raw, "path": c.path,
                         "sym": c.sym, "text": c.text, "line": c.line})
    write_report(args, "scan", rows, bible)


def cmd_range(args, repo, graph, bible):
    marker = read_marker(repo, bible)
    base = args.since or marker.get("audited_commit")
    fglob = args.findings_glob or marker.get("findings_glob") or r"^docs/findings/"
    if not base:
        sys.exit("no baseline: pass --since <commit> or record audited_commit in .claude/bible.json")
    git_commit(base, repo.root)
    rng = f"{base}..HEAD"
    log = sh(["git", "log", "--oneline", rng], repo.root, must=True).strip().split("\n")
    status = sh(["git", "diff", "--name-status", "-M", base, "HEAD"], repo.root, must=True).strip().split("\n")
    renames = [l for l in status if l.startswith("R")]
    files = [l.split("\t")[-1] for l in status if l]
    old_names = {l.split("\t")[1]: l.split("\t")[2] for l in renames}
    cited = set()
    for p in bible_files(bible):
        for c in scan_file(bible, p):
            if c.path:
                rp, _ = repo.resolve_path(c.path)
                cited.add(rp or c.path)
    touched = sorted((cited & set(files)) | {f"{o} -> {n}" for o, n in old_names.items() if o in cited})
    findings = [f for f in files if re.search(fglob, f)]
    out = {"range": rng, "commits": len([l for l in log if l]), "files": len(files), "renames": renames,
           "cited_files_changed": touched, "findings_docs": findings, "commit_log": log}
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_links(args, repo, graph, bible):
    """Link integrity: bible-internal links must hit an existing file + heading anchor; links into the repo
    (the resolved citation form) must hit an existing file."""
    files = {os.path.relpath(p, bible): open(p, encoding="utf-8").read() for p in bible_files(bible)}

    def anchors(t):
        a = {m.group(1) for m in re.finditer(r"\{#([\w-]+)\}", t)}
        for l in t.split("\n"):
            h = re.match(r"#{1,6}\s+(.*)", l)
            if h:
                x = re.sub(r"\{#[\w-]+\}", "", h.group(1)).strip().lower()
                x = re.sub(r"[^\w\s-]", "", x)
                a.add(re.sub(r"\s+", "-", x))
        return a

    A = {f: anchors(t) for f, t in files.items()}
    bad = []
    for f, t in files.items():
        base = os.path.dirname(os.path.join(bible, f))
        for m in re.finditer(r"\]\(\)", t):
            bad.append((f, t[max(0, m.start() - 60):m.end()].split("\n")[-1], "EMPTY"))
        for m in re.finditer(r"\]\(([^)\s]+)\)", t):
            g = m.group(1)
            if g.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, frag = g.partition("#")
            if path == "":
                if frag and frag not in A[f]:
                    bad.append((f, g, "ANCHOR"))
                continue
            target = os.path.normpath(os.path.join(base, path))
            rel_b = os.path.relpath(target, bible)
            if rel_b in files:
                if frag and frag not in A[rel_b]:
                    bad.append((f, g, "ANCHOR"))
            elif os.path.isfile(target):
                if frag and not re.fullmatch(r"L\d+(?:-L\d+)?", frag):
                    bad.append((f, g, "FRAGMENT"))
            else:
                bad.append((f, g, "FILE"))
    print(f"links checked in {len(files)} files; broken: {len(bad)}")
    for b in bad[:200]:
        print(" ", *b)
    return 1 if bad else 0


def read_marker(repo, bible=None):
    """The .claude/bible.json entry for this bible (matched on path), else the first entry."""
    p = os.path.join(repo.root, ".claude", "bible.json")
    try:
        with open(p) as fh:
            d = json.load(fh)
        entries = [e for e in (d.get("bibles") if isinstance(d, dict) else d) or [] if isinstance(e, dict)]
    except (OSError, ValueError, AttributeError, TypeError):
        return {}
    if not bible:
        return entries[0] if len(entries) == 1 else {}
    want = os.path.realpath(bible)
    for e in entries:
        if e.get("path") and os.path.realpath(os.path.join(repo.root, e["path"])) == want:
            return e
    print(f"WARN no entry for {os.path.relpath(bible, repo.root)} in .claude/bible.json", file=sys.stderr)
    return {}


# ---------------------------------------------------------------- reporting

def write_report(args, name, rows, bible, extra=None):
    run_dir = args.out or os.path.join(bible, "_build", "run-" + dt.date.today().isoformat())
    os.makedirs(run_dir, exist_ok=True)
    jp = os.path.join(run_dir, f"{name}.json")
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump({"meta": extra or {}, "rows": rows}, fh, indent=1, ensure_ascii=False)
    counts = defaultdict(int)
    key = "status" if rows and "status" in rows[0] else "kind"
    for r in rows:
        counts[r.get(key, "?")] += 1
    per_file = defaultdict(lambda: defaultdict(int))
    for r in rows:
        per_file[r["md"]][r.get(key, "?")] += 1
    md = [f"# {name} report", "", f"Total: {len(rows)}", ""]
    md += [f"- {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    if name == "convert":
        md += ["", f"- needs_review: {sum(1 for r in rows if r.get('needs_review'))}"]
    md += ["", "| file | " + " | ".join(sorted(counts)) + " |", "|---|" + "---|" * len(counts)]
    for f, cs in sorted(per_file.items()):
        md.append(f"| {f} | " + " | ".join(str(cs.get(k, 0)) for k in sorted(counts)) + " |")
    with open(os.path.join(run_dir, f"{name}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md[2:]))
    print(f"\nreport: {jp}")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bible", default="docs/bible", help="bible folder (default docs/bible)")
    ap.add_argument("--repo", default=None, help="repo root (default: git root of --bible)")
    ap.add_argument("--graph", default=None, help="graph.json (default <repo>/graphify-out/graph.json if present)")
    ap.add_argument("--no-graph", action="store_true")
    ap.add_argument("--out", default=None, help="report dir (default <bible>/_build/run-<date>)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    pc = sub.add_parser("convert"); pc.add_argument("--write", action="store_true")
    pk = sub.add_parser("check")
    pk.add_argument("--write", action="store_true", help="rewrite line suffixes for ok/drifted/new")
    pk.add_argument("--apply-moved", action="store_true", help="with --write: also re-point uniquely moved symbols")
    pk.add_argument("--mark", action="store_true", help="append ⚠️UNRESOLVED after citations that did not resolve")
    pk.add_argument("--range", default=None, help="A..B: flag citations into files changed in range")
    sub.add_parser("links")
    pr = sub.add_parser("range")
    pr.add_argument("--since", default=None)
    pr.add_argument("--findings-glob", default=None,
                    help="regex for findings docs (default: marker findings_glob, else ^docs/findings/)")
    args = ap.parse_args()

    bible = os.path.abspath(args.bible)
    root = os.path.abspath(args.repo) if args.repo else git_root(bible)
    repo = Repo(root)
    gpath = args.graph or os.path.join(root, "graphify-out", "graph.json")
    graph = None
    if not args.no_graph and os.path.exists(gpath):
        graph = Graph(gpath)
        graph.live = repo.fileset
        if graph.commit and sh(["git", "cat-file", "-t", graph.commit], root).strip() == "commit":
            changed = sh(["git", "diff", "--name-only", "--no-renames", graph.commit], root, must=True).split("\n")
            graph.dirty = {f for f in changed if f}
    rc = {"scan": cmd_scan, "convert": cmd_convert, "check": cmd_check, "range": cmd_range,
          "links": cmd_links}[args.cmd](args, repo, graph, bible)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
