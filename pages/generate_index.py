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
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "Sites"
SIGNATURE_ROOT = REPO_ROOT / "Signatures"
OUTPUT_PATH = REPO_ROOT / "pages" / "index.json"

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


def main():
    rel_paths = list(find_source_bes_files())
    entries = [describe(rel) for rel in rel_paths]
    signature_rel_paths = list(find_source_signature_files())
    entries += [describe_signature(rel) for rel in signature_rel_paths]
    payload = {
        "files": entries,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(entries)} entries to {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
