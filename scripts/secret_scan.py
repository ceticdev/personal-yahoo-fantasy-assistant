"""Secret scan over tracked files.

Reports **filenames and pattern categories only**. It never prints a matched
value, so the scan output itself can be pasted into a PR, a CI log, or a
review thread without becoming the leak it is looking for.

Exit code 0 = clean, 1 = at least one match (or the scan could not run).

Usage:
    python scripts/secret_scan.py [--all]   # --all also scans untracked files
"""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, str] = {
    "aws_access_key_id": r"AKIA[0-9A-Z]{16}",
    "private_key_block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt_like": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
    "yahoo_consumer_key": r"dj0y[A-Za-z0-9\-_]{20,}",
    "bearer_token": r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}",
    "oauth_token_value": r"(refresh_token|access_token)\s*[:=]\s*[\"'][A-Za-z0-9\-._~+/]{16,}[\"']",
    "client_secret_value": r"(client_secret|consumer_secret)\s*[:=]\s*[\"'][A-Za-z0-9\-._~+/]{12,}[\"']",
    "generic_api_key_value": r"(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[\"'][A-Za-z0-9\-._~+/]{16,}[\"']",
    "authorization_code": r"\boauth_verifier\s*[:=]\s*[\"']?[A-Za-z0-9]{6,}",
    "long_hex_blob": r"\b[0-9a-fA-F]{40,}\b",
    "long_base64_blob": r"\b[A-Za-z0-9+/]{60,}={0,2}\b",
}

#: Paths whose contents are allowed to look secret-shaped. Nothing is here by
#: default; entries must be justified in review.
ALLOWLIST: set[str] = set()


def tracked_files(include_untracked: bool) -> list[str]:
    args = ["git", "ls-files", "-c"]
    if include_untracked:
        args += ["-o", "--exclude-standard"]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line.strip()]


def scan(paths: list[str]) -> tuple[int, dict[str, set[str]]]:
    compiled = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}
    hits: dict[str, set[str]] = collections.defaultdict(set)
    scanned = 0

    for name in paths:
        if name in ALLOWLIST:
            continue
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for category, pattern in compiled.items():
            if pattern.search(text):
                hits[name].add(category)

    return scanned, hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="also scan untracked (but not ignored) files",
    )
    args = parser.parse_args()

    try:
        paths = tracked_files(args.all)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"secret-scan: could not list files ({type(exc).__name__})", file=sys.stderr)
        return 1

    scanned, hits = scan(paths)

    print(f"secret-scan: scanned {scanned} files against {len(PATTERNS)} pattern categories")
    if not hits:
        print("secret-scan: RESULT clean -- no matches in any category")
        return 0

    print("secret-scan: RESULT matches found (filename + category only; values never printed)")
    for name in sorted(hits):
        print(f"  {name}: {', '.join(sorted(hits[name]))}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
