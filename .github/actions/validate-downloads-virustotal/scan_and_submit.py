#!/usr/bin/env python3
"""Submit every download URL in a pull request's changed .bes files to VirusTotal.

Invoked by action.yml as a single step, with these environment variables:
    HEAD_SHA             - the pull request's head commit SHA
    FILES_LIST           - path to a NUL-separated list of changed file paths
    MAX_BYTES            - per-file size cap before a file is skipped
    VIRUSTOTAL_API_KEY   - VirusTotal public API key (repo secret)
    COMMENT_BODY_PATH    - where to write the rendered Markdown PR-comment body
    GITHUB_OUTPUT        - GitHub Actions' own output file

and these command-line options:
    --max-urls-per-run   - cap on distinct URLs submitted in one run (see
                            "Rate limiting" below); default is no limit
    --skip-urls          - path to a file of regular expressions (one per
                            line); any scan URL matching one is skipped
                            instead of submitted (see "Skipping URLs" below);
                            default is 'skip-urls.txt' next to this script

URL discovery reuses .github/actions/_lib/bes_downloads.py - the exact same
extraction used by validate-download-allowlist, so "what counts as a download
command" never drifts between the two checks. Every distinct URL found (deduplicated,
case-sensitive) across every changed *.bes file is submitted to VirusTotal's
public API (POST /urls), then polled (GET /analyses/{id}) until VirusTotal
reports a verdict or this script gives up waiting.

Rate limiting: the public API allows 4 requests/minute and 500/day. This
script throttles submissions to stay under that, retries a 429 with backoff,
and, if --max-urls-per-run is given, caps how many distinct URLs one run will
submit so a pull request naming an unusually large number of download URLs
can't exhaust the day's quota or make one run unreasonably slow - any URL
beyond the cap is named in the PR comment as "not scanned" rather than
silently dropped. With no cap given (the default), every distinct URL found
is submitted.

Skipping URLs: --skip-urls names a file of regular expressions, one per
line (blank lines and lines starting with '#' are ignored). Before a URL
would be submitted, it's checked with re.search() against every pattern in
that file (in order); a match marks the URL "skipped" in the results table
with the matching pattern named, and no request is sent to VirusTotal for
it. Skipping a URL adds no delay before the next submission, since no API
call was made for it. The default --skip-urls file is 'skip-urls.txt' next
to this script; if that default file doesn't exist, no URLs are skipped. A
file path given explicitly via --skip-urls that doesn't exist is a setup
error (see "Exits 0" below), unlike the silently-optional default. A
skipped URL costs no VirusTotal quota, so it never counts against
--max-urls-per-run - the cap only limits how many URLs are actually
submitted; matching a skip pattern always exempts a URL from it.

COMMENT_BODY_PATH is (re)written after every URL processed, not only at the
end - each write is the full Markdown so far, so the file always has real
content even if this script is killed mid-run, and action.yml can post/update
the PR comment from it whenever it's convenient to. It (and, at the very end,
GITHUB_STEP_SUMMARY) includes a hidden HTML marker action.yml uses to find
and update a prior run's comment instead of piling up a new one every push.

action.yml runs this script under `timeout <scan-timeout-seconds>s`, which
sends SIGTERM when that elapses. This script catches it (see _request_stop):
rather than dying wherever that lands, it stops starting new VirusTotal
submissions/polls, marks whatever's left in the queue "timed out", and falls
through to its normal end-of-run reporting - so a timeout still produces a
real comment/summary/outputs, not nothing.

At the end (whether finishing normally or stopped early by a timeout), sets
these GITHUB_OUTPUT values for action.yml to act on:
    malicious   - count of scanned URLs with at least one VirusTotal engine
                  reporting them malicious (drives the label + REQUEST_CHANGES)
    scanned     - count of URLs actually submitted this run
    unresolved  - count of URLs that timed out or errored (no verdict reached)
    timed_out   - "true" if a stop was requested before every URL finished

Exits 0 unless VIRUSTOTAL_API_KEY is missing/empty, no *.bes file in
FILES_LIST could be read at all, or an explicitly-given --skip-urls file is
missing or contains an invalid regular expression - those are genuine setup
problems, not a "some URLs were flagged" (or "timed out") outcome, and should
show as a failed job so they get noticed.

Everything below main() is also imported and reused by
test_scan_and_submit.py, this action's local test wrapper (same directory),
so "how a URL is found/scanned/reported" can't drift between a real PR run
and a local test run.
"""

import argparse
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "_lib"))
import bes_downloads as bd  # noqa: E402 - see sys.path.insert above

ACTION_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_SKIP_URLS_PATH = ACTION_DIR / "skip-urls.txt"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB - matches validate-download-allowlist's cap

COMMENT_MARKER = "<!-- validate-downloads-virustotal:status -->"

VT_BASE = "https://www.virustotal.com/api/v3"
# Free-tier VirusTotal API limits: 4 requests/minute, 500/day, no batch
# endpoint. SUBMIT_INTERVAL keeps submissions at 60/4 = 15s apart with a
# small safety margin; POLL_INTERVAL/POLL_ATTEMPTS bound how long this script
# waits for one URL's analysis to finish before treating it as unresolved.
SUBMIT_INTERVAL_SECONDS = 16
POLL_INTERVAL_SECONDS = 15
POLL_ATTEMPTS = 8  # ~2 minutes per URL
MAX_HTTP_RETRIES = 3


# --- Graceful shutdown ---------------------------------------------------
#
# action.yml runs this script under `timeout`, which sends SIGTERM when
# --scan-timeout-seconds elapses. Rather than dying wherever that catches us
# (mid-submission, mid-poll, before a single result has been written
# anywhere), we catch it, stop starting new VirusTotal work, and let main()
# fall through to its normal end-of-run reporting - so a timeout still
# produces a real comment/summary/outputs describing whatever did complete,
# instead of leaving downstream steps with nothing.

_STOP_REQUESTED = False


def _request_stop(signum, frame):  # noqa: ARG001 - required signal handler signature
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def fail(message):
    print(f"::error::{message}", file=sys.stderr)
    sys.exit(1)


def load_skip_patterns(path, explicit):
    """Load one compiled regex per non-blank, non-comment line of `path`.

    Missing default file -> no patterns. Missing explicitly-given file, or
    any invalid regex in the file, is treated as a setup error (fail()).
    """
    path = pathlib.Path(path)
    if not path.exists():
        if explicit:
            fail(f"--skip-urls file not found: {path}")
        return []
    patterns = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                patterns.append(re.compile(line))
            except re.error as err:
                fail(f"{path}:{lineno}: invalid regular expression ({err}): {line}")
    return patterns


def skip_reason(url, patterns):
    """Return the pattern text `url` matched, or None if it matches nothing."""
    for pattern in patterns:
        if pattern.search(url):
            return pattern.pattern
    return None


# --- VirusTotal API -----------------------------------------------------


def vt_request(api_key, method, path, data=None):
    """Call one VirusTotal v3 endpoint; retries a 429 with exponential backoff."""
    url = f"{VT_BASE}{path}"
    body = None
    headers = {"x-apikey": api_key}
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    for attempt in range(1, MAX_HTTP_RETRIES + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < MAX_HTTP_RETRIES:
                wait = 5 * (2**attempt)
                print(f"VirusTotal rate-limited (429); backing off {wait}s (attempt {attempt}/{MAX_HTTP_RETRIES})")
                time.sleep(wait)
                continue
            detail = err.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(str(err.reason)) from err
    raise RuntimeError("exhausted retries")  # pragma: no cover - loop always returns or raises


def submit_url(api_key, url):
    """Submit `url` for analysis; return its analysis id."""
    resp = vt_request(api_key, "POST", "/urls", data={"url": url})
    return resp["data"]["id"]


def poll_analysis(api_key, analysis_id, poll_interval=POLL_INTERVAL_SECONDS, poll_attempts=POLL_ATTEMPTS):
    """Poll an analysis until VirusTotal completes it; return its stats dict,
    or None on timeout or because a stop was requested (see _request_stop)."""
    for _ in range(poll_attempts):
        if _STOP_REQUESTED:
            return None
        resp = vt_request(api_key, "GET", f"/analyses/{analysis_id}")
        attrs = resp["data"]["attributes"]
        if attrs.get("status") == "completed":
            return attrs.get("stats", {})
        time.sleep(poll_interval)
    return None


# --- Gathering download URLs from .bes content ------------------------------


def collect_urls_from_content(display_path, content, max_bytes, url_to_files):
    """Parse one .bes file's raw bytes, recording each download URL found into
    url_to_files (url -> set of display paths it was found in).

    Returns True if the file was read/parsed without being skipped (even if
    it contained zero URLs), False if it was skipped (too large or
    unparseable) - emits a warning via bd.warn either way something's wrong.
    Shared by both the production gather loop below (content via `git show`)
    and test_scan_and_submit.py's (content via local disk), so "how a URL is
    found in a .bes file" can't drift between a real PR run and a local test.
    """
    if len(content) > max_bytes:
        bd.warn(f"{len(content)} bytes exceeds the {max_bytes} byte scan limit; skipping", file=display_path)
        return False
    try:
        urls = list(bd.iter_bes_download_urls(content))
    except bd.ET.ParseError as err:
        bd.warn(f"not parseable BES XML ({err}); skipping", file=display_path)
        return False
    for url in urls:
        url_to_files.setdefault(url, set()).add(display_path)
    return True


# --- Partitioning + submitting -----------------------------------------


def partition_urls(all_urls, skip_patterns, max_urls_per_run):
    """Split all_urls into (to_scan, capped, scan_slots_used).

    Partition, not slice: a URL matching a skip pattern costs no VirusTotal
    quota, so it doesn't consume one of the max_urls_per_run scan slots and
    is never counted against the cap - only URLs actually destined for
    submission are. See the module docstring's "Rate limiting"/"Skipping
    URLs" sections.
    """
    to_scan = []
    capped = []
    scan_slots_used = 0
    for url in all_urls:
        if skip_reason(url, skip_patterns) is not None:
            to_scan.append(url)
        elif max_urls_per_run is None or scan_slots_used < max_urls_per_run:
            to_scan.append(url)
            scan_slots_used += 1
        else:
            capped.append(url)
    return to_scan, capped, scan_slots_used


def scan_urls(
    api_key,
    to_scan,
    scan_slots_used,
    url_to_files,
    skip_patterns,
    submit=True,
    submit_interval=SUBMIT_INTERVAL_SECONDS,
    poll_interval=POLL_INTERVAL_SECONDS,
    poll_attempts=POLL_ATTEMPTS,
    on_progress=None,
):
    """Submit (unless submit=False, for a dry run) and poll every URL in
    to_scan; returns the `results` list (each: {url, files, status,
    malicious, suspicious, harmless, undetected, detail}).

    A dry run still applies skip patterns (so the printed/rendered output
    matches what a real run would do) but marks every would-be-submitted URL
    "dry-run" instead of actually calling VirusTotal - test_scan_and_submit.py
    uses this to preview what a run would do without spending API quota.

    If on_progress is given, it's called with the `results` list so far after
    every URL (submitted, skipped, or dry-run) - main() uses this to keep
    COMMENT_BODY_PATH updated as the run progresses, rather than only at the
    very end. If a stop has been requested (see _request_stop) before a URL
    that would need an actual VirusTotal submission, that URL (and every one
    after it) is recorded as "timed-out" instead of being submitted, so a run
    that's asked to stop still returns a complete, renderable `results` list
    matching every entry in `to_scan`.
    """
    results = []
    submitted_any = False  # tracks whether a real API submission has happened yet, for submit_interval pacing
    submitted_count = 0
    for url in to_scan:
        entry = {"url": url, "files": sorted(url_to_files[url])}

        reason = skip_reason(url, skip_patterns)
        if reason is not None:
            entry["status"] = "skipped"
            entry["detail"] = f"matched skip pattern: {reason}"
            results.append(entry)
            print(f"{url}: skipped (matched skip pattern: {reason})")
            if on_progress is not None:
                on_progress(results)
            continue

        if _STOP_REQUESTED:
            entry["status"] = "timed-out"
            entry["detail"] = "scan run timed out before this URL could be submitted"
            results.append(entry)
            print(f"{url}: not scanned (scan run timed out)")
            if on_progress is not None:
                on_progress(results)
            continue

        if not submit:
            entry["status"] = "dry-run"
            entry["detail"] = "not submitted (dry run)"
            results.append(entry)
            print(f"{url}: would be submitted (dry run)")
            if on_progress is not None:
                on_progress(results)
            continue

        if submitted_any:
            time.sleep(submit_interval)
        submitted_any = True

        submitted_count += 1
        print(f"Submitting ({submitted_count}/{scan_slots_used}): {url}")
        try:
            analysis_id = submit_url(api_key, url)
            stats = poll_analysis(api_key, analysis_id, poll_interval, poll_attempts)
            if stats is None:
                entry["status"] = "unresolved"
                entry["detail"] = (
                    "scan run timed out while waiting for VirusTotal's verdict"
                    if _STOP_REQUESTED
                    else "VirusTotal had not finished analyzing this URL within the wait budget"
                )
            else:
                entry["status"] = "completed"
                entry["malicious"] = stats.get("malicious", 0)
                entry["suspicious"] = stats.get("suspicious", 0)
                entry["harmless"] = stats.get("harmless", 0)
                entry["undetected"] = stats.get("undetected", 0)
        except Exception as err:  # noqa: BLE001 - any VT/network failure becomes "unresolved", never a crash mid-scan
            entry["status"] = "unresolved"
            entry["detail"] = str(err)
        results.append(entry)
        print(f"{url}: {entry['status']}" + (f" (malicious={entry.get('malicious', 0)})" if entry["status"] == "completed" else ""))
        if on_progress is not None:
            on_progress(results)
    return results


# --- Rendering the report/PR-comment body -----------------------------------


def md_cell(text):
    """Escape a value for safe placement inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").replace("`", "'")


def render_report(
    all_urls,
    results,
    capped,
    url_to_files,
    scanned_count,
    skipped_count,
    malicious_count,
    unresolved_count,
    context="in this pull request's changed Fixlets/Tasks",
    include_marker=True,
    banner_lines=None,
):
    """Render the scan results as Markdown - the same body production posts
    as a PR comment. `context` is a short phrase describing where the URLs
    came from (test_scan_and_submit.py passes "in the matched files"
    instead); `include_marker=False` drops the hidden HTML marker
    action.yml uses to find a prior comment, meaningless outside a PR.
    `banner_lines`, if given, is inserted right after the marker - main() uses
    it for an "in progress" note on incremental writes and a "timed out" note
    on the final one when the run didn't finish in time.

    Returns a list of lines (join with "\\n" to get the full body).
    """
    lines = [COMMENT_MARKER] if include_marker else []
    if banner_lines:
        lines.extend(banner_lines)
        lines.append("")

    if not all_urls:
        lines.append("# VirusTotal download scan")
        lines.append("")
        lines.append("> [!NOTE]")
        lines.append(f"> No download commands (prefetch/curl/wget/download) were found {context}.")
    elif malicious_count > 0:
        total_malicious_hits = sum(r.get("malicious", 0) for r in results)
        lines.append("# 🚨 VirusTotal scan: MALICIOUS DOWNLOAD DETECTED")
        lines.append("")
        lines.append("> [!CAUTION]")
        lines.append(
            f"> {total_malicious_hits} scanner(s) across {malicious_count} of {scanned_count} scanned "
            f"download URL(s) {context} were flagged as **malicious** by VirusTotal. "
            "Do not merge until a maintainer has reviewed this."
        )
    else:
        lines.append("# ✅ VirusTotal scan: no malicious downloads detected")
        lines.append("")
        if unresolved_count:
            lines.append("> [!WARNING]")
            lines.append(
                f"> No scanner reported a malicious verdict, but {unresolved_count} of {scanned_count} "
                "download URL(s) could not be scanned (see table) - manual review recommended for those."
            )
        else:
            lines.append("> [!NOTE]")
            lines.append(f"> All {scanned_count} download URL(s) found {context} were scanned by VirusTotal with no malicious verdicts.")

    if all_urls:
        lines.append("")
        lines.append("| URL | Referenced in | Malicious | Suspicious | Harmless | Undetected | Status |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in results:
            files_cell = "<br>".join(f"`{md_cell(f)}`" for f in r["files"])
            if r["status"] == "completed":
                mal = f"**{r['malicious']}**" if r["malicious"] > 0 else "0"
                row = (mal, r["suspicious"], r["harmless"], r["undetected"], "completed")
            elif r["status"] == "skipped":
                row = ("-", "-", "-", "-", f"skipped ({md_cell(r.get('detail', ''))})")
            elif r["status"] == "dry-run":
                row = ("-", "-", "-", "-", "dry-run (not submitted)")
            elif r["status"] == "timed-out":
                row = ("-", "-", "-", "-", "not scanned (run timed out)")
            else:
                row = ("-", "-", "-", "-", f"unresolved ({md_cell(r.get('detail', ''))})")
            lines.append(f"| `{md_cell(r['url'])}` | {files_cell} | {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |")
        for url in capped:
            files_cell = "<br>".join(f"`{md_cell(f)}`" for f in sorted(url_to_files[url]))
            lines.append(f"| `{md_cell(url)}` | {files_cell} | - | - | - | - | not scanned (per-run cap) |")

    lines.append("")
    lines.append(
        f"<sub>Scanned {scanned_count} of {len(all_urls)} distinct download URL(s) found via VirusTotal's public API"
        + (f" ({skipped_count} skipped per skip-urls patterns)" if skipped_count else "")
        + ". Malicious/suspicious counts are the number of VirusTotal's third-party scan engines reporting that verdict, "
        "not a guarantee - review before trusting either a clean or a flagged result.</sub>"
    )
    return lines


def summarize(checked, all_urls, scanned_count, skipped_count, malicious_count, unresolved_count):
    """The one-line final summary both main() and test_scan_and_submit.py print."""
    return (
        f"Checked {checked} .bes file(s); {len(all_urls)} distinct download URL(s) found, "
        f"{scanned_count} scanned, {skipped_count} skipped, {malicious_count} flagged malicious, "
        f"{unresolved_count} unresolved."
    )


# --- main (production entry point - see module docstring for env vars) -----


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--max-urls-per-run",
        type=int,
        default=None,
        metavar="N",
        help="cap on distinct URLs submitted in one run; any URL beyond it is listed in the PR "
        "comment as not scanned instead of being submitted (default: no limit)",
    )
    parser.add_argument(
        "--skip-urls",
        type=str,
        default=None,
        metavar="PATH",
        help="path to a file of regular expressions (one per line, '#' comments and blank lines "
        "ignored); a scan URL matching any of them is skipped instead of submitted, with no delay "
        f"before the next submission (default: {DEFAULT_SKIP_URLS_PATH.name} next to this script, "
        "silently ignored if that default file doesn't exist)",
    )
    args = parser.parse_args(argv)
    if args.max_urls_per_run is not None and args.max_urls_per_run < 0:
        parser.error("--max-urls-per-run must not be negative")
    return args


def main():
    # Registered here (not at import time) so importing this module for
    # tests (test_scan_and_submit.py) never installs it - only a real
    # production run, invoked under action.yml's `timeout`, needs to catch
    # SIGTERM and wind down gracefully (see _request_stop above).
    signal.signal(signal.SIGTERM, _request_stop)

    args = parse_args()

    head_sha = os.environ["HEAD_SHA"]
    files_list = os.environ["FILES_LIST"]
    max_bytes = int(os.environ.get("MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    api_key = os.environ.get("VIRUSTOTAL_API_KEY", "")
    comment_body_path = os.environ["COMMENT_BODY_PATH"]
    github_output = os.environ["GITHUB_OUTPUT"]
    max_urls_per_run = args.max_urls_per_run
    skip_urls_explicit = args.skip_urls is not None
    skip_urls_path = pathlib.Path(args.skip_urls) if skip_urls_explicit else DEFAULT_SKIP_URLS_PATH

    if not api_key:
        fail(
            "VIRUSTOTAL_API_KEY is empty - add it as a repository secret "
            "(Settings > Secrets and variables > Actions) before this check can run."
        )

    skip_patterns = load_skip_patterns(skip_urls_path, skip_urls_explicit)

    # --- Gather distinct download URLs across every changed .bes file ------

    with open(files_list, "rb") as fh:
        files = [p.decode("utf-8", errors="replace") for p in fh.read().split(b"\0") if p]

    url_to_files = {}  # url -> set of file paths it was found in
    checked = 0
    read_failures = 0

    for path in files:
        if not path.endswith(".bes"):
            continue
        checked += 1

        try:
            content = bd.read_git_show(head_sha, path)
        except subprocess.CalledProcessError as err:
            read_failures += 1
            stderr = err.stderr.decode("utf-8", errors="replace")[:500]
            bd.warn(f"could not read PR-head content ({stderr}); skipping", file=path)
            continue

        collect_urls_from_content(path, content, max_bytes, url_to_files)

    if checked > 0 and read_failures == checked:
        fail(f"could not read any of the {checked} changed .bes file(s) at {head_sha}; see warnings above")

    all_urls = sorted(url_to_files)
    to_scan, capped, scan_slots_used = partition_urls(all_urls, skip_patterns, max_urls_per_run)

    if capped:
        print(
            f"::warning::{len(capped)} download URL(s) were not scanned this run "
            f"(per-run cap of {max_urls_per_run}, to stay within VirusTotal's free-tier "
            "daily quota): " + ", ".join(capped)
        )

    to_skip_count = len(to_scan) - scan_slots_used
    print(
        f"skip-urls file: {skip_urls_path} ({len(skip_patterns)} pattern(s) loaded)\n"
        f"URLs found: {len(all_urls)}; to be skipped: {to_skip_count}; to be scanned: {scan_slots_used}"
    )

    # --- Show what will happen before submitting anything ------------------

    submit_urls = [u for u in to_scan if skip_reason(u, skip_patterns) is None]
    skip_list_urls = [u for u in to_scan if skip_reason(u, skip_patterns) is not None]

    print(f"\n=== URLs to submit to VirusTotal ({len(submit_urls)}) ===")
    for u in submit_urls:
        print(f"  {u}")

    print(f"\n=== URLs skipped - matched a skip-urls pattern ({len(skip_list_urls)}) ===")
    for u in skip_list_urls:
        print(f"  {u}  (matched: {skip_reason(u, skip_patterns)})")

    print(f"\n=== URLs skipped - past the max-urls-per-run cap of {max_urls_per_run} ({len(capped)}) ===")
    for u in capped:
        print(f"  {u}")
    print()

    # --- Submit + poll each URL, updating the PR comment as results come in,
    # then render + write the final report -----------------------------

    def write_comment(rendered_lines):
        with open(comment_body_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rendered_lines) + "\n")

    def report_progress(results_so_far):
        scanned_sf = sum(1 for r in results_so_far if r["status"] in ("completed", "unresolved"))
        skipped_sf = sum(1 for r in results_so_far if r["status"] == "skipped")
        malicious_sf = sum(1 for r in results_so_far if r["status"] == "completed" and r["malicious"] > 0)
        unresolved_sf = sum(1 for r in results_so_far if r["status"] == "unresolved")
        write_comment(
            render_report(
                all_urls,
                results_so_far,
                capped,
                url_to_files,
                scanned_sf,
                skipped_sf,
                malicious_sf,
                unresolved_sf,
                banner_lines=[
                    "> [!NOTE]",
                    f"> Scan in progress ({len(results_so_far)} of {len(to_scan)} URL(s) processed so far) - "
                    "this comment updates automatically as results come in; reload for the latest.",
                ],
            )
        )

    results = scan_urls(api_key, to_scan, scan_slots_used, url_to_files, skip_patterns, on_progress=report_progress)

    timed_out = _STOP_REQUESTED
    malicious_count = sum(1 for r in results if r["status"] == "completed" and r["malicious"] > 0)
    unresolved_count = sum(1 for r in results if r["status"] == "unresolved")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    timed_out_count = sum(1 for r in results if r["status"] == "timed-out")
    scanned_count = sum(1 for r in results if r["status"] in ("completed", "unresolved"))

    banner_lines = None
    if timed_out:
        print(f"::warning::scan run timed out; {timed_out_count} URL(s) were not scanned")
        banner_lines = [
            "> [!WARNING]",
            f"> This scan **timed out** before it could finish - {timed_out_count} URL(s) were not scanned "
            '(see "not scanned (run timed out)" rows below). Re-run this check (e.g. push a new commit, or '
            "re-run this job) to scan the remaining URL(s).",
        ]

    lines = render_report(
        all_urls, results, capped, url_to_files, scanned_count, skipped_count, malicious_count, unresolved_count, banner_lines=banner_lines
    )
    write_comment(lines)

    with open(github_output, "a", encoding="utf-8") as fh:
        fh.write(f"malicious={malicious_count}\n")
        fh.write(f"scanned={scanned_count}\n")
        fh.write(f"unresolved={unresolved_count}\n")
        fh.write(f"timed_out={'true' if timed_out else 'false'}\n")

    summary_line = summarize(checked, all_urls, scanned_count, skipped_count, malicious_count, unresolved_count)
    print(summary_line)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            if timed_out:
                fh.write(
                    "### ⚠️ VirusTotal scan timed out\n\n"
                    f"{timed_out_count} URL(s) were not scanned because the run timed out. "
                    "See the pinned VirusTotal comment on this pull request for full details.\n\n"
                )
            fh.write(summary_line + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
