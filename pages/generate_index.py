#!/usr/bin/env python3
"""
Generate pages/index.json: a listing of every Sites/**/*.bes file (Fixlets,
Tasks, Analyses, Baselines, ...) plus every Signatures/*.xml file, with
metadata parsed from its XML.

GitHub Pages publishes the whole repo root (see index.html there), so
Sites/ and Signatures/ are already served as-is - this script does not copy
or duplicate any .bes/.xml file. It only enumerates them and writes
pages/index.json for the viewer's (index.html + pages/app.js) file list and
search.

Run from the repo root:
    python scripts/generate_index.py
"""
import json
from datetime import datetime
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "Sites"
SIGNATURE_ROOT = REPO_ROOT / "Signatures"
OUTPUT_PATH = REPO_ROOT / "pages" / "index.json"

# How many entries the viewer's welcome page lists under "Recent contributions".
RECENT_COUNT = 10

# GitHub's privacy-preserving commit emails: "<id>+<login>@users.noreply.github.com"
# (current) or "<login>@users.noreply.github.com" (legacy). The only place a git
# commit reveals a GitHub login without calling the API.
NOREPLY_EMAIL_RE = re.compile(r"^(?:\d+\+)?([^@+]+)@users\.noreply\.github\.com$")

KNOWN_ROOT_TAGS = {"Task", "Fixlet", "Analysis", "Baseline", "TaskCondition", "ComputerGroup"}

# Both .bes exports and Signatures/*.xml files carry their metadata as
# an XML comment "frontmatter" block before the real root element, e.g.:
#   <!--
#     ID       : 2994532
#     Author   : jgstew
#   -->
# or:
#   <!--
#   Author: "edmontan"
#   Publisher: "3M Company"
#   -->
FRONTMATTER_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
FRONTMATTER_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


def find_source_bes_files():
    for path in sorted(SOURCE_ROOT.rglob("*.bes")):
        yield path.relative_to(REPO_ROOT)


def find_source_signature_files():
    for path in sorted(SIGNATURE_ROOT.rglob("*.xml")):
        yield path.relative_to(REPO_ROOT)


def child_text(el, tag):
    child = el.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def parse_frontmatter(abs_path: Path) -> dict[str, str]:
    """Parse the leading XML-comment frontmatter block into a dict of fields.

    Values may optionally be wrapped in double quotes (used by the
    Signatures/*.xml exports); surrounding quotes are stripped.
    """
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"warning: could not read {abs_path}: {e}", file=sys.stderr)
        return {}

    match = FRONTMATTER_RE.search(text)
    if not match:
        return {}

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        field_match = FRONTMATTER_FIELD_RE.match(line.strip())
        if not field_match:
            continue
        key, value = field_match.group(1), field_match.group(2).strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        fields.setdefault(key, value)
    return fields


def base_entry(source_rel_path: Path):
    # source_rel_path is already relative to the repo root (Sites/... or
    # Signatures/... - see find_source_bes_files/find_source_signature_files
    # above) - this doubles as pages/app.js's local fetch/download URL
    # (relative to the published index.html, which lives at the repo root
    # too) and, combined with BLOB_BASE there, the "View on GitHub" link.
    rel_path = source_rel_path
    return {
        "path": rel_path.as_posix(),
        "name": rel_path.name,
        "dir": rel_path.parent.as_posix() if rel_path.parent != Path(".") else "(root)",
        "type": "Other",
        "title": rel_path.stem,
        "source": "",
        "sourceReleaseDate": "",
        "severity": "",
        "domain": "",
        "downloadSize": "",
        "relevanceCount": 0,
        "author": "",
        "id": "",
        "publisher": "",
        "productName": "",
        "release": "",
        "keywords": "",
    }


def describe(source_rel_path: Path):
    abs_path = REPO_ROOT / source_rel_path
    entry = base_entry(source_rel_path)
    posix_path = entry["path"]

    frontmatter = parse_frontmatter(abs_path)
    entry["author"] = frontmatter.get("Author", "")
    entry["id"] = frontmatter.get("ID", "")

    try:
        tree = ET.parse(abs_path)
    except ET.ParseError as e:
        print(f"warning: skipping unparsable file {posix_path}: {e}", file=sys.stderr)
        return entry

    bes = tree.getroot()
    root = None
    for tag in KNOWN_ROOT_TAGS:
        root = bes.find(tag)
        if root is not None:
            break
    if root is None:
        return entry

    entry["type"] = root.tag
    entry["title"] = child_text(root, "Title") or entry["title"]
    entry["source"] = child_text(root, "Source")
    entry["sourceReleaseDate"] = child_text(root, "SourceReleaseDate")
    entry["severity"] = child_text(root, "SourceSeverity")
    entry["domain"] = child_text(root, "Domain")
    entry["downloadSize"] = child_text(root, "DownloadSize")
    entry["relevanceCount"] = len(root.findall("Relevance"))
    return entry


def describe_signature(source_rel_path: Path):
    abs_path = REPO_ROOT / source_rel_path
    entry = base_entry(source_rel_path)
    entry["type"] = "Signature"

    frontmatter = parse_frontmatter(abs_path)
    entry["author"] = frontmatter.get("Author", "")
    entry["publisher"] = frontmatter.get("Publisher", "")
    entry["productName"] = frontmatter.get("ProductName", "")
    entry["release"] = frontmatter.get("Release", "")
    entry["keywords"] = frontmatter.get("Keywords", "")
    entry["title"] = entry["productName"] or entry["title"]
    return entry


def git(*args):
    """Run git in the repo and return stdout as text; raises on failure."""
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def parse_author(header):
    """Split a '<name>\\x1f<email>\\x1f<iso date>' record into a contribution dict."""
    name, email, date = (header.split("\x1f") + ["", "", ""])[:3]
    m = NOREPLY_EMAIL_RE.match(email)
    return {
        "author": name,
        # Only trust a noreply email for a profile link, and never for bots.
        "login": m.group(1) if m and not name.endswith("[bot]") else "",
        "date": date,
    }


def newest_paths_on_main():
    """Current content paths, most recently landed on main first.

    Replays the first-parent (main line) history oldest -> newest with rename
    detection, so a file's "landing" position survives the update-index
    workflow's ID-prefix renames: A(dd) stamps the path with the commit's
    position, R(ename) carries the stamp to the new path, D(elete) drops it.
    First-parent (with -m, so merge commits diff against their first parent)
    keeps the replay linear and correct even when content arrived via a
    pull-request merge after being deleted and re-added on other branches.
    This only ORDERS files by recency; who actually authored them is resolved
    separately (see original_author), because a merge/bot commit's own author
    is not the contributor.
    """
    out = git(
        "log", "-z", "--first-parent", "-m", "--reverse", "-M", "-l0",
        "--name-status", "--format=%x01", "--", "Sites", "Signatures",
    )
    # With -z, --name-status emits NUL-separated tokens: a "\x01" header per
    # commit, then per file "<status>", "<path>" (renames: "<old>", "<new>").
    tokens = [t.lstrip("\n") for t in out.split("\0")]
    landed: dict[str, int] = {}
    seq = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if not tok:
            continue
        if tok.startswith("\x01"):
            seq += 1
            continue
        status = tok[0]  # A, M, D, R, C, T, ...
        if status in "RC" and i + 1 < len(tokens):
            old, new = tokens[i], tokens[i + 1]
            i += 2
            landed[new] = landed.pop(old, seq) if status == "R" else seq
        elif i < len(tokens):
            path = tokens[i]
            i += 1
            if status == "A":
                landed[path] = seq
            elif status == "D":
                landed.pop(path, None)
    return [p for p, _seq in sorted(landed.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)]


def original_author(path):
    """Who first added `path`, following it back across renames (or None).

    `--follow` walks the file's history through the bot's ID-prefix rename to
    its original name; --diff-filter=A keeps only the add commits, and the
    oldest of those is the original contribution.
    """
    out = git(
        "log", "--follow", "--diff-filter=A", "-M", "--format=%an%x1f%ae%x1f%aI", "--", path
    )
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return parse_author(lines[-1]) if lines else None


def recent_contributions(existing_paths):
    """The RECENT_COUNT most recent contributions, newest first, as
    [{path, added, author, login}], credited to the original author.

    Needs full git history (CI must check out with fetch-depth: 0); returns []
    with a warning when history is unavailable so the index still builds and
    the viewer simply omits the list.
    """
    try:
        if git("rev-parse", "--is-shallow-repository").strip() == "true":
            print("warning: shallow clone - contribution data would be wrong; "
                  "check out with fetch-depth: 0. Skipping 'recent'.", file=sys.stderr)
            return []
        candidates = [p for p in newest_paths_on_main() if p in existing_paths]
        # A pull request can land many files at once, so look past RECENT_COUNT,
        # then order by each file's original authored date.
        rows = []
        for path in candidates[: RECENT_COUNT * 5]:
            info = original_author(path)
            if info and info["date"]:
                rows.append({"path": path, "added": info["date"],
                             "author": info["author"], "login": info["login"]})
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"warning: git history unavailable, skipping 'recent': {e}", file=sys.stderr)
        return []
    rows.sort(key=lambda r: (datetime.fromisoformat(r["added"]), r["path"]), reverse=True)
    return rows[:RECENT_COUNT]


def main():
    rel_paths = list(find_source_bes_files())
    entries = [describe(rel) for rel in rel_paths]
    signature_rel_paths = list(find_source_signature_files())
    entries += [describe_signature(rel) for rel in signature_rel_paths]
    payload = {
        # Drives the viewer's welcome page; credited to whoever first added each
        # file, not to the bots/maintainers that later renamed or touched it.
        "recent": recent_contributions({e["path"] for e in entries}),
        "files": entries,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(entries)} entries to {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
