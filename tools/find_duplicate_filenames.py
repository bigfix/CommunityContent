#!/usr/bin/env python3
"""
Find duplicate filenames under CommunityContent/Sites (or any path), where a
duplicate is a file whose name matches another file's name once a leading
"###-" numeric contentid prefix is stripped off. Duplicates may live in any
subdirectory, not just alongside each other.

Example:
    123-my-fixlet.bes
    456-my-fixlet.bes

Both share the short name "my-fixlet.bes". The one with the lowest contentid
(123 here) is reported as the "original"; the rest are "duplicates".
"""

import argparse
import fnmatch
import os
import re
import sys
from collections import defaultdict

PREFIX_RE = re.compile(r"^(\d+)-(.+)$")


def find_duplicates(root, exclude_pattern=None):
    """Return {short_name: [(contentid, relative_path), ...]} for names with >1 match."""
    groups = defaultdict(list)

    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if exclude_pattern and fnmatch.fnmatch(filename, exclude_pattern):
                continue

            match = PREFIX_RE.match(filename)
            if not match:
                continue

            contentid, short_name = int(match.group(1)), match.group(2)
            full_path = os.path.join(dirpath, filename)
            relative_path = os.path.relpath(full_path, root)
            groups[short_name].append((contentid, relative_path))

    return {name: entries for name, entries in groups.items() if len(entries) > 1}


def main():
    parser = argparse.ArgumentParser(
        description="Find files under a path whose names collide once their "
        "leading '###-' contentid prefix is removed."
    )
    parser.add_argument("path", help="Top-level path to search")
    parser.add_argument(
        "--exclude",
        default=None,
        help="Glob pattern of filenames to exclude from the search (matched against the bare filename)",
    )
    parser.add_argument(
        "--show",
        choices=["original", "duplicates", "both"],
        default="both",
        help="Which of the matched files to print (default: both)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        print(f"error: not a directory: {args.path}", file=sys.stderr)
        return 1

    groups = find_duplicates(args.path, args.exclude)

    for entries in groups.values():
        entries.sort(key=lambda entry: entry[0])
        original_path = entries[0][1]
        duplicate_paths = [path for _contentid, path in entries[1:]]

        if args.show in ("original", "both"):
            print(original_path)
        if args.show in ("duplicates", "both"):
            for path in duplicate_paths:
                print(path)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, OSError):
        # Output was piped into something like `head` that closed early
        # (Windows raises a plain OSError here rather than BrokenPipeError).
        sys.exit(0)
