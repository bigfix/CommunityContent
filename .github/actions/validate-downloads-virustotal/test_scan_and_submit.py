#!/usr/bin/env python3
"""Local test wrapper for scan_and_submit.py (this action's main script).

scan_and_submit.py is wired for its GitHub Actions caller: it reads changed
files via `git show <HEAD_SHA>:<path>` (never the working tree), and writes
its rendered PR-comment Markdown + malicious/scanned/unresolved counts to
files ($COMMENT_BODY_PATH / $GITHUB_OUTPUT) that action.yml then uses to
post/update an actual pull request comment. Neither fits an ad hoc local
check against files on disk, so this wrapper imports scan_and_submit.py as a
module and reuses its actual URL-discovery, partitioning, submission, and
report-rendering logic (collect_urls_from_content / partition_urls /
scan_urls / render_report / summarize) directly against files you name on
the command line, instead of reimplementing any of that here.

This wrapper itself only: takes the BES file(s) to scan and an optional
skip-urls.txt override as command-line options (in place of the action's
FILES_LIST/--skip-urls), and prints the results to stdout.

VirusTotal submission is real, costs quota (free tier: 4 requests/minute,
500/day), and needs a live API key, so it is NOT the default. Pass --submit
to actually call VirusTotal (reads VIRUSTOTAL_API_KEY from the environment -
never pass a key on the command line, where it would land in shell history).
Without --submit this only discovers URLs and previews what a real run would
do - no network calls.

Every run's console output (stdout and stderr) is also duplicated to a
timestamped .log file written to the current working directory, whose path
is printed at the end, so a run can be reviewed or shared afterward without
having captured the terminal yourself.

Usage:
    # Dry run: just show what URLs would be submitted, no VirusTotal calls.
    python test_scan_and_submit.py "Sites/TestSite/Fixlets/*.bes"

    # Actually submit to VirusTotal (needs VIRUSTOTAL_API_KEY set):
    $env:VIRUSTOTAL_API_KEY = "<your key>"   # PowerShell
    python test_scan_and_submit.py "Sites/TestSite/Fixlets/*.bes" --submit
"""

import argparse
import datetime
import glob
import os
import pathlib
import sys
from typing import TextIO

ACTION_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ACTION_DIR.parent.parent.parent

sys.path.insert(0, str(ACTION_DIR))
import scan_and_submit as sas  # noqa: E402 - see sys.path.insert above

sys.path.insert(0, str(ACTION_DIR.parent / "_lib"))
import bes_downloads as bd  # noqa: E402 - see sys.path.insert above

# Matches production's max-urls-per-run input default (see action.yml) - a
# safety cap so a careless local run against a big glob doesn't submit
# dozens of URLs and burn through VirusTotal's daily quota. sas.main() (the
# production entry point) itself defaults to no limit when this isn't given.
DEFAULT_MAX_URLS_PER_RUN = 15


class _Tee:
    """A writable stream that duplicates everything written to it across several
    underlying streams (e.g. the real console plus a log file), so existing
    print()/bd.warn() calls don't need to change to also reach the log file."""

    def __init__(self, *streams: TextIO):
        self._streams = streams

    def write(self, data: str):
        for stream in self._streams:
            stream.write(data)

    def flush(self):
        for stream in self._streams:
            stream.flush()


def gather_urls_from_disk(patterns, max_bytes):
    """Glob-expand `patterns` against REPO_ROOT and collect download URLs from
    each matched .bes file's on-disk content, via sas.collect_urls_from_content
    (the exact same per-file logic production uses against `git show` output).

    Returns (url_to_files, checked, read_failures).
    """
    files = []
    for pattern in patterns:
        pattern_path = pathlib.Path(pattern)
        resolved_pattern = pattern if pattern_path.is_absolute() else str(REPO_ROOT / pattern)
        matches = sorted(glob.glob(resolved_pattern, recursive=True))
        if not matches:
            bd.warn(f'glob pattern "{pattern}" matched no files')
        files.extend(matches)

    url_to_files = {}
    checked = 0
    read_failures = 0

    for path in files:
        if not path.endswith(".bes"):
            bd.warn("not a .bes file; skipping", file=path)
            continue
        checked += 1

        display_path = str(pathlib.Path(path).resolve().relative_to(REPO_ROOT).as_posix())

        try:
            content = pathlib.Path(path).read_bytes()
        except OSError as err:
            read_failures += 1
            bd.warn(f"could not read file ({err}); skipping", file=display_path)
            continue

        sas.collect_urls_from_content(display_path, content, max_bytes, url_to_files)

    return url_to_files, checked, read_failures


def _run(args):
    api_key = os.environ.get("VIRUSTOTAL_API_KEY", "")
    if args.submit and not api_key:
        sas.fail(
            "--submit was given but $VIRUSTOTAL_API_KEY is empty - set it first, e.g. (PowerShell) "
            '$env:VIRUSTOTAL_API_KEY = "<your key>"'
        )

    skip_urls_path = pathlib.Path(args.skip_urls) if args.skip_urls is not None else sas.DEFAULT_SKIP_URLS_PATH
    skip_patterns = sas.load_skip_patterns(skip_urls_path, args.skip_urls is not None)

    url_to_files, checked, read_failures = gather_urls_from_disk(args.bes_files, sas.DEFAULT_MAX_BYTES)
    if checked > 0 and read_failures == checked:
        sas.fail(f"could not read any of the {checked} matched .bes file(s); see warnings above")

    all_urls = sorted(url_to_files)
    to_scan, capped, scan_slots_used = sas.partition_urls(all_urls, skip_patterns, args.max_urls_per_run)

    if capped:
        print(
            f"::warning::{len(capped)} download URL(s) were not scanned this run "
            f"(per-run cap of {args.max_urls_per_run}): " + ", ".join(capped)
        )

    to_skip_count = len(to_scan) - scan_slots_used
    print(
        f"skip-urls file: {skip_urls_path} ({len(skip_patterns)} pattern(s) loaded)\n"
        f"URLs found: {len(all_urls)}; to be skipped: {to_skip_count}; to be scanned: {scan_slots_used}\n"
        + ("Submitting to VirusTotal for real." if args.submit else "Dry run - nothing will be submitted to VirusTotal (pass --submit to actually scan).")
    )

    results = sas.scan_urls(api_key, to_scan, scan_slots_used, url_to_files, skip_patterns, submit=args.submit)

    malicious_count = sum(1 for r in results if r["status"] == "completed" and r["malicious"] > 0)
    unresolved_count = sum(1 for r in results if r["status"] == "unresolved")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    scanned_count = len(to_scan) - skipped_count

    lines = sas.render_report(
        all_urls,
        results,
        capped,
        url_to_files,
        scanned_count,
        skipped_count,
        malicious_count,
        unresolved_count,
        context="in the matched files",
        include_marker=False,
    )

    print("\n--- Rendered report (production posts this as a PR comment) ---\n")
    print("\n".join(lines))
    print(f"\n--- Output values (production writes these to $GITHUB_OUTPUT) ---\nmalicious={malicious_count}\nscanned={scanned_count}\nunresolved={unresolved_count}")
    print()
    print(sas.summarize(checked, all_urls, scanned_count, skipped_count, malicious_count, unresolved_count))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "bes_files",
        nargs="+",
        help='One or more .bes file paths or glob patterns, e.g. "Sites/TestSite/Fixlets/*.bes". '
        "Relative patterns are resolved against the repo root (%s)." % REPO_ROOT,
    )
    parser.add_argument(
        "--skip-urls",
        default=None,
        metavar="PATH",
        help=f"Path to a file of regular expressions (default: {sas.DEFAULT_SKIP_URLS_PATH}, the one this "
        "action ships; silently ignored if that default doesn't exist). A path given here that doesn't "
        "exist is a setup error, matching production.",
    )
    parser.add_argument(
        "--max-urls-per-run",
        type=int,
        default=DEFAULT_MAX_URLS_PER_RUN,
        metavar="N",
        help=f"Per-run cap on distinct URLs submitted (default: {DEFAULT_MAX_URLS_PER_RUN}, matching "
        "production's default input). Pass 0 to disable submission entirely while still previewing "
        "discovery, or a large number to remove the cap.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually submit discovered URLs to VirusTotal (costs quota; needs VIRUSTOTAL_API_KEY). "
        "Without this flag, URLs are only discovered and previewed - no network calls.",
    )
    args = parser.parse_args()

    # The rendered report can contain non-ASCII characters (emoji headings)
    # that a Windows console's legacy codepage can't encode; force UTF-8 on
    # the actual console streams (not just the log file below) so a local
    # run there doesn't crash mid-report.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass

    log_path = pathlib.Path.cwd() / f"test_scan_and_submit_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
    real_stdout, real_stderr = sys.stdout, sys.stderr
    with open(log_path, "w", encoding="utf-8") as log_file:
        sys.stdout = _Tee(real_stdout, log_file)
        sys.stderr = _Tee(real_stderr, log_file)
        try:
            _run(args)
        finally:
            sys.stdout, sys.stderr = real_stdout, real_stderr

    print(f"Full log written to {log_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
