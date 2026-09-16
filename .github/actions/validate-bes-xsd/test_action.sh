#!/usr/bin/env bash
# Local test runner for this action's own "Validate each changed file against
# BES.xsd" step (see action.yml) - runs the exact same per-file checks
# (symlink/extension/size/xmllint schema validation) against a glob of files
# you name on the command line, instead of a pull request's changed-files
# list, and prints everything straight to stdout - no GitHub Actions
# environment (gh api, git show, $RUNNER_TEMP, ...) required.
#
# Validates against this action's own bundled BES.xsd (alongside this
# script) by default - the same file action.yml uses, except action.yml's
# copy gets overwritten with the PR-base version during an actual CI run
# (see action.yml's header for why). Pass --schema to point at a different
# copy instead (e.g. scripts/BES.xsd, or a draft you're editing).
#
# Requires xmllint (libxml2-utils) on PATH, same as the action itself.
#
# Usage:
#   .github/actions/validate-bes-xsd/test_action.sh "Sites/**/*.bes"
#   .github/actions/validate-bes-xsd/test_action.sh --schema scripts/BES.xsd "Sites/TestSite/Fixlets/*.bes"
set -euo pipefail

ACTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
schema="$ACTION_DIR/BES.xsd"
MAX_BYTES="${MAX_BYTES:-10485760}" # 10 MiB - matches the action's own cap

if [ "${1:-}" = "--schema" ]; then
  schema="$2"
  shift 2
fi

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 [--schema PATH] <glob> [<glob> ...]"
  echo "e.g.:  $0 \"Sites/**/*.bes\""
  exit 2
fi

if [ ! -f "$schema" ]; then
  echo "schema file not found: $schema"
  exit 2
fi

# Expand each glob argument here (rather than relying on the caller's shell
# to have already done it) so a pattern like "Sites/**/*.bes" works whether
# or not the caller's shell has globstar enabled, and so a pattern matching
# nothing is reported instead of silently passed through as a literal string.
shopt -s globstar nullglob
files=()
for pattern in "$@"; do
  # shellcheck disable=SC2206 - intentional word-splitting glob expansion
  matches=( $pattern )
  if [ "${#matches[@]}" -eq 0 ]; then
    echo "pattern \"$pattern\" matched no files"
    continue
  fi
  files+=( "${matches[@]}" )
done

fail=0
checked=0

for file in "${files[@]}"; do
  # A leading "-" would otherwise be misread as an option by the tools below.
  case "$file" in
    -*) file="./$file" ;;
  esac

  checked=$((checked + 1))

  if [ -L "$file" ]; then
    printf 'FAIL  %s :: is a symlink, not a regular file\n' "$file"
    fail=1
    continue
  fi
  if [ ! -f "$file" ]; then
    printf 'FAIL  %s :: not found\n' "$file"
    fail=1
    continue
  fi

  case "$file" in
    *.bes) ;;
    *)
      printf 'FAIL  %s :: filename must end with .bes\n' "$file"
      fail=1
      continue
      ;;
  esac

  size=$(stat -c%s -- "$file")
  if [ "$size" -gt "$MAX_BYTES" ]; then
    printf 'FAIL  %s :: %s bytes exceeds the %s byte validation limit\n' "$file" "$size" "$MAX_BYTES"
    fail=1
    continue
  fi

  if ! output=$(timeout 30s xmllint --nonet --noout --schema "$schema" "$file" 2>&1); then
    printf 'FAIL  %s :: does not validate against %s\n' "$file" "$schema"
    # Cap xmllint's own error text so a file crafted to produce a huge error
    # stream can't flood the terminal.
    printf '%s\n' "$output" | head -c 4000
    echo
    fail=1
    continue
  fi

  printf 'PASS  %s\n' "$file"
done

echo
echo "Checked $checked file(s)."
exit "$fail"
