#!/usr/bin/env python3
"""Local test wrapper for validate_download_allowlist.py (this action's main script).

validate_download_allowlist.py is wired for its GitHub Actions caller: it
reads changed files via `git show <HEAD_SHA>:<path>` (never the working tree)
and writes a `flagged` count to $GITHUB_OUTPUT. Neither fits an ad hoc local
check against files on disk, so this wrapper imports
validate_download_allowlist.py as a module and reuses its actual
pattern-loading and per-file scan logic (load_known_url_patterns /
scan_bes_content) directly against files you name on the command line,
instead of reimplementing that logic here.

This wrapper itself only: takes the BES file(s) to scan and an optional
known_urls.txt override as command-line options (in place of the action's
FILES_LIST/KNOWN_URLS_PATH environment variables), and prints the results to
stdout. Every run's console output is also duplicated to a timestamped .log
file written to the current working directory, whose path is printed at the
end, so a run can be reviewed or shared afterward without having captured the
terminal yourself.

Usage:
    python test_validate_download_allowlist.py "Sites/TestSite/Fixlets/*.bes"
    python test_validate_download_allowlist.py "Sites/**/*.bes" --known-urls path/to/known_urls.txt
"""

import argparse
import datetime
import glob
import pathlib
import sys
from typing import TextIO

ACTION_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ACTION_DIR.parent.parent.parent

sys.path.insert(0, str(ACTION_DIR))
import validate_download_allowlist as vda  # noqa: E402 - see sys.path.insert above

sys.path.insert(0, str(ACTION_DIR.parent / "_lib"))
import bes_downloads as bd  # noqa: E402 - see sys.path.insert above


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


def _run(args):
    known_urls_path = pathlib.Path(args.known_urls)
    patterns, found = vda.load_known_url_patterns(known_urls_path)
    if not found:
        bd.warn(f"{known_urls_path} not found; every download URL will be treated as unrecognized")
    known_urls_name = known_urls_path.name

    files = []
    for pattern in args.bes_files:
        pattern_path = pathlib.Path(pattern)
        resolved_pattern = pattern if pattern_path.is_absolute() else str(REPO_ROOT / pattern)
        matches = sorted(glob.glob(resolved_pattern, recursive=True))
        if not matches:
            bd.warn(f'glob pattern "{pattern}" matched no files')
        files.extend(matches)

    checked = 0
    flagged = 0

    for path in files:
        display_path = str(pathlib.Path(path).resolve().as_posix())

        if not path.endswith(".bes"):
            bd.warn("not a .bes file; skipping", file=display_path)
            continue
        checked += 1

        try:
            content = pathlib.Path(path).read_bytes()
        except OSError as err:
            bd.warn(f"could not read file ({err}); skipping", file=display_path)
            continue

        flagged += vda.scan_bes_content(display_path, content, patterns, known_urls_name, vda.DEFAULT_MAX_BYTES)

    print(f"Checked {checked} .bes file(s); {flagged} unrecognized download URL(s) flagged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "bes_files",
        nargs="+",
        help='One or more .bes file paths or glob patterns, e.g. "Sites/TestSite/Fixlets/*.bes". '
        "Relative patterns are resolved against the repo root (%s)." % REPO_ROOT,
    )
    parser.add_argument(
        "--known-urls",
        default=str(vda.DEFAULT_KNOWN_URLS_PATH),
        help=f"Path to the known-URL-pattern file (default: {vda.DEFAULT_KNOWN_URLS_PATH}, the one this action ships).",
    )
    args = parser.parse_args()

    log_path = pathlib.Path.cwd() / f"test_validate_download_allowlist_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
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
