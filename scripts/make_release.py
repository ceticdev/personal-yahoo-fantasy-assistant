"""Build and verify a clean release archive from tracked sources only.

The previous ad-hoc zip picked up ~90 generated entries (`.venv`,
`__pycache__`, `.pytest_cache`, egg-info, local reports). The fix is to stop
zipping the working directory at all: `git archive` emits exactly what Git
tracks at a given ref, so build products and ignored files cannot be included
by construction.

The archive is then *verified* rather than trusted -- a `.gitignore` mistake
or a badly-added file would otherwise sail straight through. Verification
rejects any entry matching a forbidden pattern, requires exactly one
top-level directory, and requires `.env.example` to be present.

Usage:
    python scripts/make_release.py                 # build + verify from HEAD
    python scripts/make_release.py --ref v0.2.0    # a specific ref
    python scripts/make_release.py --check-only PATH.zip
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_NAME = "yahoo-fantasy-mcp-v2"
DEFAULT_OUTPUT_DIR = Path("dist")

#: Anything matching these must never appear in a release archive.
FORBIDDEN_PATTERNS: dict[str, str] = {
    "git metadata": r"(^|/)\.git(/|$)",
    "virtualenv": r"(^|/)\.venv(/|$)|(^|/)venv(/|$)",
    "pytest cache": r"(^|/)\.pytest_cache(/|$)",
    "bytecode cache": r"(^|/)__pycache__(/|$)",
    "compiled bytecode": r"\.py[co]$",
    "egg-info": r"\.egg-info(/|$)",
    "dotenv secrets": r"(^|/)\.env$|(^|/)\.env\.(?!example$)",
    "token file": r"token[^/]*\.json$|\.yahoo_token\.json$",
    "credential file": r"credential[^/]*\.json$|client_secret[^/]*\.json$",
    "key material": r"\.(pem|key|p12|pfx)$",
    "local reports": r"(^|/)reports?(/|$)|VERIFICATION-RUN-NOTES\.md$",
    "parent NFL folder documents": r"MCP-PLAN-AND-CLAUDE-HANDOFF\.md$|(^|/)deliverable(/|$)",
    "local tooling": r"(^|/)\.serena(/|$)|(^|/)\.claude(/|$)",
    "nested archive": r"\.zip$",
}

REQUIRED_ENTRIES = (".env.example", "README.md", "pyproject.toml")


def build(ref: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "archive",
            "--format=zip",
            f"--prefix={PROJECT_NAME}/",
            ref,
            "-o",
            str(output),
        ],
        check=True,
    )
    return output


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(archive: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    compiled = {label: re.compile(pattern) for label, pattern in FORBIDDEN_PATTERNS.items()}

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()

    if not names:
        return False, ["archive is empty"]

    for name in names:
        for label, pattern in compiled.items():
            if pattern.search(name):
                problems.append(f"forbidden entry ({label}): {name}")

    top_level = {name.split("/", 1)[0] for name in names}
    if len(top_level) != 1:
        problems.append(f"expected exactly one top-level directory, found: {sorted(top_level)}")
    elif top_level != {PROJECT_NAME}:
        problems.append(f"top-level directory should be {PROJECT_NAME!r}, found {top_level}")

    stripped = {name.split("/", 1)[1] for name in names if "/" in name}
    for required in REQUIRED_ENTRIES:
        if required not in stripped:
            problems.append(f"missing required entry: {required}")

    return not problems, problems


def report(archive: Path) -> int:
    ok, problems = verify(archive)
    with zipfile.ZipFile(archive) as zf:
        entry_count = len(zf.namelist())

    print(f"release-check: archive     {archive}")
    print(f"release-check: entries     {entry_count}")
    print(f"release-check: sha256      {sha256(archive)}")

    if ok:
        print("release-check: RESULT clean -- no forbidden entries")
        return 0

    print("release-check: RESULT FAILED")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="git ref to archive (default: HEAD)")
    parser.add_argument("--output", type=Path, default=None, help="output .zip path")
    parser.add_argument(
        "--check-only",
        type=Path,
        default=None,
        help="verify an existing archive instead of building one",
    )
    args = parser.parse_args()

    if args.check_only is not None:
        if not args.check_only.is_file():
            print(f"release-check: no such archive: {args.check_only}", file=sys.stderr)
            return 1
        return report(args.check_only)

    output = args.output or (DEFAULT_OUTPUT_DIR / f"{PROJECT_NAME}.zip")
    try:
        archive = build(args.ref, output)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"release-check: git archive failed ({type(exc).__name__})", file=sys.stderr)
        return 1

    return report(archive)


if __name__ == "__main__":
    raise SystemExit(main())
