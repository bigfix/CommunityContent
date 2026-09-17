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
    REVIEW_BODY_PATH - where to write the rendered Markdown REQUEST_CHANGES
                        review body (a listing of every flagged (file, URL)
                        pair); action.yml posts this file's content via
                        `gh api ... -f body=@<path>` when flagged != 0
    GITHUB_OUTPUT    - GitHub Actions' own output file
    GITHUB_STEP_SUMMARY - GitHub Actions' own job summary file (optional -
                        when set, this script appends a listing of every
                        matched AND every flagged (file, URL) pair)

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

Exits 0 always - this script's effect is the `flagged` output, the warning
annotations, the review body file, and the job summary it writes; action.yml
decides what to do with them.
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


def md_cell(text):
    """Escape a value for safe placement inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("`", "'")


def scan_bes_content(display_path, content, patterns, known_urls_name, max_bytes, matched, flagged):
    """Scan one .bes file's raw bytes for its download URLs, sorting each
    distinct one into `matched` or `flagged` (both lists of {"file", "url"}
    dicts, appended to in place - same shape main() accumulates across every
    file, for the review body and job summary).

    Emits a ::warning:: (via bd.warn) for a too-large file, an unparseable
    file, and each unrecognized (file, URL) pair.
    """
    if len(content) > max_bytes:
        bd.warn(
            f"{len(content)} bytes exceeds the {max_bytes} byte download-scan limit; skipping",
            file=display_path,
        )
        return

    try:
        urls = list(bd.iter_bes_download_urls(content))
    except bd.ET.ParseError as err:
        # Not this check's job to fail on invalid XML - validate-bes-xsd
        # already owns that; just skip so this check stays focused.
        bd.warn(f"not parseable BES XML ({err}); skipping", file=display_path)
        return

    seen_in_file = set()
    for url in urls:
        if url in seen_in_file:
            continue
        seen_in_file.add(url)
        if is_known(patterns, url):
            matched.append({"file": display_path, "url": url})
            continue
        flagged.append({"file": display_path, "url": url})
        bd.warn(
            f'references a download URL that does not match any pattern in '
            f'{known_urls_name}: "{url}". Please confirm this URL is legitimate, '
            f'then ask a maintainer to add a matching pattern to {known_urls_name} '
            "before merging.",
            file=display_path,
            line=1,
        )


def render_review_body(flagged_urls, known_urls_name):
    """Render the Markdown REQUEST_CHANGES review body listing every flagged
    (file, URL) pair - written to REVIEW_BODY_PATH regardless of whether any
    were found, so action.yml can post it unconditionally whenever
    steps.scan.outputs.flagged != '0'.
    """
    lines = [
        "One or more Fixlets/Tasks in this pull request reference a download URL "
        f"that does not match any pattern in {known_urls_name}. Please confirm each URL "
        "is legitimate and safe, then ask a maintainer to add a matching pattern to "
        f"{known_urls_name} - once that's merged to main, re-running this check will "
        "clear automatically.",
    ]
    if flagged_urls:
        lines.append("")
        lines.append("| File | URL |")
        lines.append("|---|---|")
        for entry in flagged_urls:
            lines.append(f"| `{md_cell(entry['file'])}` | `{md_cell(entry['url'])}` |")
    return "\n".join(lines) + "\n"


def _render_url_table(entries):
    if not entries:
        return "_None._"
    lines = ["| File | URL |", "|---|---|"]
    for entry in entries:
        lines.append(f"| `{md_cell(entry['file'])}` | `{md_cell(entry['url'])}` |")
    return "\n".join(lines)


def render_step_summary(matched_urls, flagged_urls, known_urls_name):
    """Render the job-summary Markdown listing every matched AND every
    flagged (file, URL) pair found across the whole run.
    """
    lines = ["### Download-URL allowlist check", ""]
    if not matched_urls and not flagged_urls:
        lines.append(
            "No download commands (prefetch/curl/wget/download) were found in this "
            "pull request's changed Fixlets/Tasks."
        )
    else:
        lines.append(f"#### Matched {known_urls_name} ({len(matched_urls)})")
        lines.append("")
        lines.append(_render_url_table(matched_urls))
        lines.append("")
        lines.append(f"#### Not in {known_urls_name} ({len(flagged_urls)})")
        lines.append("")
        lines.append(_render_url_table(flagged_urls))
    return "\n".join(lines) + "\n"


def main():
    HEAD_SHA = os.environ["HEAD_SHA"]
    FILES_LIST = os.environ["FILES_LIST"]
    KNOWN_URLS_PATH = os.environ.get("KNOWN_URLS_PATH", str(DEFAULT_KNOWN_URLS_PATH))
    MAX_BYTES = int(os.environ.get("MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    REVIEW_BODY_PATH = os.environ["REVIEW_BODY_PATH"]
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

    matched_urls = []  # [{"file", "url"}] - distinct per file, matched known_urls.txt
    flagged_urls = []  # [{"file", "url"}] - distinct per file, did NOT match known_urls.txt
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

        scan_bes_content(path, content, patterns, known_urls_name, MAX_BYTES, matched_urls, flagged_urls)

    flagged = len(flagged_urls)

    with open(REVIEW_BODY_PATH, "w", encoding="utf-8") as fh:
        fh.write(render_review_body(flagged_urls, known_urls_name))

    with open(GITHUB_OUTPUT, "a", encoding="utf-8") as fh:
        fh.write(f"flagged={flagged}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(render_step_summary(matched_urls, flagged_urls, known_urls_name))

    print(
        f"Checked {checked} .bes file(s) under Sites/*/Fixlets; {len(matched_urls)} known download URL(s), "
        f"{flagged} unrecognized download URL(s) flagged."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
