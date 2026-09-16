#!/usr/bin/env python3
"""Scan changed .bes files' ActionScript for download URLs unknown to known_urls.txt.

Invoked by action.yml as a single step, with these environment variables:
    HEAD_SHA         - the pull request's head commit SHA
    FILES_LIST       - path to a NUL-separated list of changed file paths
    KNOWN_URLS_PATH  - path to the known-URL-pattern file, read from whatever
                        is already checked out (the PR BASE, under this
                        action's intended pull_request_target caller - see
                        action.yml's header for why that matters). Defaults to
                        known_urls.txt alongside this script.
    MAX_BYTES        - per-file size cap before a file is skipped
    GITHUB_OUTPUT    - GitHub Actions' own output file

Every *.bes file named in FILES_LIST is read via `git show <HEAD_SHA>:<path>`
(never from the working tree, which under this action's intended caller holds
the PR base, not head) and treated purely as data: parsed as XML with
xml.etree.ElementTree, then each <ActionScript> body is scanned line-by-line
for a download command - see .github/actions/_lib/bes_downloads.py (shared
with validate-downloads-virustotal) for exactly what counts as one. See
action.yml for the full security rationale.

The known-URL-pattern loading and per-file scan below are also imported and
reused by test_validate_download_allowlist.py, this action's local test
wrapper (same directory), so the two never drift apart.

Exits 0 always - this script's effect is the `flagged` output and the warning
annotations it prints; action.yml decides what to do with them.
"""

import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "_lib"))
import bes_downloads as bd  # noqa: E402 - see sys.path.insert above

ACTION_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_KNOWN_URLS_PATH = ACTION_DIR / "known_urls.txt"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB - generous for a .bes export, small enough to bound parse cost


def load_known_url_patterns(known_urls_path):
    """Parse one compiled regex per non-blank, non-comment line of `known_urls_path`.

    Returns (patterns, found) - `found` is False when the file doesn't exist,
    which callers report however fits their context (the PR-base checkout vs.
    an arbitrary local path).
    """
    known_urls_path = pathlib.Path(known_urls_path)
    patterns = []
    if not known_urls_path.is_file():
        return patterns, False
    with open(known_urls_path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                patterns.append(re.compile(line))
            except re.error as err:
                bd.warn(
                    f"ignoring invalid regex on line {lineno} of {known_urls_path} "
                    f"({err}): {line}",
                    file=str(known_urls_path),
                    line=lineno,
                )
    return patterns, True


def is_known(patterns, url):
    return any(p.fullmatch(url) for p in patterns)


def scan_bes_content(display_path, content, patterns, known_urls_name, max_bytes):
    """Scan one .bes file's raw bytes for download URLs not covered by `patterns`.

    Emits a ::warning:: (via bd.warn) for a too-large file, an unparseable
    file, and each unrecognized (file, URL) pair. Returns the number of
    unrecognized URLs flagged in this file.
    """
    if len(content) > max_bytes:
        bd.warn(
            f"{len(content)} bytes exceeds the {max_bytes} byte download-scan limit; skipping",
            file=display_path,
        )
        return 0

    try:
        urls = list(bd.iter_bes_download_urls(content))
    except bd.ET.ParseError as err:
        # Not this check's job to fail on invalid XML - validate-bes-xsd
        # already owns that; just skip so this check stays focused.
        bd.warn(f"not parseable BES XML ({err}); skipping", file=display_path)
        return 0

    flagged = 0
    seen_in_file = set()
    for url in urls:
        if url in seen_in_file or is_known(patterns, url):
            continue
        seen_in_file.add(url)
        flagged += 1
        bd.warn(
            f'references a download URL that does not match any pattern in '
            f'{known_urls_name}: "{url}". Please confirm this URL is legitimate, '
            f'then ask a maintainer to add a matching pattern to {known_urls_name} '
            "before merging.",
            file=display_path,
            line=1,
        )
    return flagged


def main():
    HEAD_SHA = os.environ["HEAD_SHA"]
    FILES_LIST = os.environ["FILES_LIST"]
    KNOWN_URLS_PATH = os.environ.get("KNOWN_URLS_PATH", str(DEFAULT_KNOWN_URLS_PATH))
    MAX_BYTES = int(os.environ.get("MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    GITHUB_OUTPUT = os.environ["GITHUB_OUTPUT"]

    patterns, found = load_known_url_patterns(KNOWN_URLS_PATH)
    if not found:
        bd.warn(
            f"{KNOWN_URLS_PATH} not found on the PR base; every download URL "
            "will be treated as unrecognized"
        )
    known_urls_name = pathlib.Path(KNOWN_URLS_PATH).name

    with open(FILES_LIST, "rb") as fh:
        files = [p.decode("utf-8", errors="replace") for p in fh.read().split(b"\0") if p]

    flagged = 0
    checked = 0

    for path in files:
        if not path.endswith(".bes"):
            continue
        checked += 1

        try:
            content = bd.read_git_show(HEAD_SHA, path)
        except subprocess.CalledProcessError as err:
            stderr = err.stderr.decode("utf-8", errors="replace")[:500]
            bd.warn(f"could not read PR-head content ({stderr}); skipping", file=path)
            continue

        flagged += scan_bes_content(path, content, patterns, known_urls_name, MAX_BYTES)

    with open(GITHUB_OUTPUT, "a", encoding="utf-8") as fh:
        fh.write(f"flagged={flagged}\n")

    print(f"Checked {checked} .bes file(s) under Sites/*/Fixlets; {flagged} unrecognized download URL(s) flagged.")
    sys.exit(0)


if __name__ == "__main__":
    main()
