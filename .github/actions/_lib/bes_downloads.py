#!/usr/bin/env python3
"""Shared BigFix ActionScript download-URL logic.

Used by both .github/actions/validate-download-allowlist (known_urls.txt
allowlist check) and .github/actions/validate-downloads-virustotal (VirusTotal
scan) so
"what counts as a download command" and "how a URL is pulled out of one" is
defined exactly once, in exactly one place, for both checks.

Not an action on its own - imported by each action's own script via:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "_lib"))
    import bes_downloads

This resolves by path from each script's own location, not the process's
current working directory, so it works regardless of which directory a
composite action's `run:` step happens to execute in.
"""

import re
import subprocess
import xml.etree.ElementTree as ET

# --- ::workflow-command:: annotation helpers ---------------------------------

# Per GitHub's documented `::workflow-command::` escaping rules
# (actions/toolkit's core/src/command.ts: escapeProperty/escapeData): order
# matters - '%' must be escaped first, or the '%' introduced by the other
# substitutions would itself get re-escaped.


def escape_property(s):
    s = s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    s = s.replace(":", "%3A").replace(",", "%2C")
    return s


def escape_data(s):
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def warn(message, file=None, line=None):
    props = []
    if file is not None:
        props.append(f"file={escape_property(file)}")
    if line is not None:
        props.append(f"line={line}")
    prefix = f"::warning {','.join(props)}::" if props else "::warning::"
    print(f"{prefix}{escape_data(message)}")


# --- Reading a file's content as of an exact PR-head commit ------------------


def read_git_show(head_sha, path):
    """Return the bytes of `path` as of commit `head_sha`, via `git show`.

    Raises subprocess.CalledProcessError if the object isn't available
    locally (e.g. the commit was never fetched) or the path doesn't exist at
    that commit. Callers are expected to have already run
    `git fetch --no-tags --depth=1 origin <head_sha>`.
    """
    return subprocess.run(
        ["git", "show", f"{head_sha}:{path}"],
        check=True,
        capture_output=True,
    ).stdout


# --- ActionScript download-command scanning ----------------------------------

# A generic absolute-URI token: scheme://rest-with-no-whitespace-or-quoting.
URL_RE = re.compile(r"""[A-Za-z][A-Za-z0-9+.\-]*://[^\s"'<>]+""")


def clean_url(u):
    """Strip trailing punctuation a URL token likely picked up from prose/syntax."""
    return u.rstrip(").,;:'\"")


# BigFix's own download syntax ("prefetch ...", "add prefetch item ...",
# "add nohash prefetch item ...") plus "download"/"download now" and the two
# third-party downloaders BigFix content commonly shells out to.
DOWNLOAD_KEYWORDS_RE = re.compile(r"\bdownload(\s+now)?\b|\bcurl\b|\bwget\b", re.IGNORECASE)


def is_download_line(lowered_stripped):
    if "prefetch item" in lowered_stripped:  # covers both add/add nohash forms
        return True
    if lowered_stripped.startswith("prefetch "):
        return True
    return bool(DOWNLOAD_KEYWORDS_RE.search(lowered_stripped))


# The raw content of a `createfile until <MARKER>` block is file text being
# written out, not ActionScript commands - a prefetch/curl/wget-looking line
# in there isn't a command at all, so lines between the two markers are
# skipped, same judgement bes_actionscript_validate_prefetch.py (in the
# vendored pre-commit-bigfix hooks) makes.
HEREDOC_START_RE = re.compile(r"^createfile\s+until\s+(\S+)\s*$", re.IGNORECASE)


def find_download_urls(actionscript_text):
    """Yield URLs from download-command lines in one ActionScript body."""
    heredoc_end = None
    for raw_line in actionscript_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if heredoc_end is not None:
            if stripped == heredoc_end:
                heredoc_end = None
            continue
        start = HEREDOC_START_RE.match(stripped)
        if start:
            heredoc_end = start.group(1)
            continue
        if not stripped or stripped.startswith("//"):
            continue
        if not is_download_line(stripped.lower()):
            continue
        for match in URL_RE.findall(stripped):
            yield clean_url(match)


def iter_bes_download_urls(content):
    """Parse `content` (one .bes file's raw bytes) and yield every download URL.

    Walks every <ActionScript> element in document order and yields each URL
    found in its download-command lines (duplicates included - callers dedupe
    as they see fit).

    Raises xml.etree.ElementTree.ParseError if `content` isn't parseable XML;
    callers decide how to report that (both current callers skip the file and
    emit a warning - BES.xsd schema validity is validate-bes-xsd's job, not
    this module's).
    """
    root = ET.fromstring(content)
    for element in root.iter("ActionScript"):
        yield from find_download_urls(element.text or "")
