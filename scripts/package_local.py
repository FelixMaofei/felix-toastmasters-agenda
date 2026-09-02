#!/usr/bin/env python3
"""Build the single portable runtime package used by every supported agent."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FOLDER = "felix-toastmasters-agenda"
MANIFEST_NAME = "SHA256SUMS"

RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "assets/agenda.css",
    "assets/toastmasters-logo.png",
    "scripts/simple_input.py",
    "scripts/build_agenda.py",
    "scripts/agenda_renderer.py",
    "scripts/export_a4.py",
    "scripts/run_agenda.py",
    "assets/fonts/noto-sans-sc/LICENSE",
    "assets/fonts/noto-sans-sc/NOTICE.md",
    "assets/fonts/noto-sans-sc/index.css",
)
FONT_GLOB = "assets/fonts/noto-sans-sc/files/*.woff2"
PROFILE_GLOB = "profiles/*.json"

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".svg",
    ".txt",
    ".yaml",
    ".yml",
}
PRIVATE_PATTERNS = (
    (
        re.compile(
            r"(?<![A-Za-z0-9_])(?:file://)?/(?:Users|home|Volumes)/[^\s'\"<>]+"
        ),
        "absolute local path",
    ),
    (
        re.compile(r"\b[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s'\"<>]+"),
        "Windows home path",
    ),
    (re.compile(r"\bPN-\d{6,}\b", re.IGNORECASE), "membership number"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "mobile number"),
    (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "email address",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_sources() -> list[tuple[Path, Path]]:
    """Return (source, package-relative path) pairs in deterministic order."""

    relative_paths = [Path(value) for value in RUNTIME_FILES]
    font_root = SKILL_ROOT / "assets" / "fonts" / "noto-sans-sc" / "files"
    relative_paths.extend(
        path.relative_to(SKILL_ROOT) for path in sorted(font_root.glob("*.woff2"))
    )
    relative_paths.extend(
        path.relative_to(SKILL_ROOT) for path in sorted(SKILL_ROOT.glob(PROFILE_GLOB))
    )
    return [(SKILL_ROOT / relative, relative) for relative in relative_paths]


def copy_runtime(target: Path) -> None:
    sources = runtime_sources()
    if not any(relative.match(FONT_GLOB) for _, relative in sources):
        raise FileNotFoundError("packaged Noto Sans SC font files are missing")
    for source, relative in sources:
        if not source.is_file():
            raise FileNotFoundError(f"package source is missing: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def scan_text_files(target: Path) -> None:
    """Reject private data and machine-specific absolute paths before packaging."""

    problems: list[str] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            problems.append(f"{path.relative_to(target)} is not valid UTF-8: {exc}")
            continue
        for pattern, label in PRIVATE_PATTERNS:
            if pattern.search(content):
                problems.append(f"{path.relative_to(target)} contains {label}")
    if problems:
        raise ValueError("runtime package privacy scan failed: " + "; ".join(problems))


def write_manifest(package_dir: Path) -> Path:
    manifest_path = package_dir / MANIFEST_NAME
    entries = [
        path
        for path in sorted(package_dir.rglob("*"))
        if path.is_file() and path != manifest_path
    ]
    manifest_path.write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(package_dir).as_posix()}\n"
            for path in entries
        ),
        encoding="utf-8",
    )
    return manifest_path


def make_zip(package_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir.parent))


def validate_output_root(output_root: Path) -> Path:
    resolved = output_root.expanduser().resolve()
    if resolved == SKILL_ROOT or SKILL_ROOT in resolved.parents:
        raise ValueError(
            "--output-dir must be outside the Skill directory; "
            "building inside it would create a nested Skill"
        )
    return resolved


def remove_exact_target(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def is_recognizable_previous_output(path: Path, *, zip_output: bool) -> bool:
    if zip_output:
        if not path.is_file():
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            return False
        prefix = f"{PACKAGE_FOLDER}/"
        return {
            f"{prefix}SKILL.md",
            f"{prefix}{MANIFEST_NAME}",
        }.issubset(names)
    return (
        path.is_dir()
        and not path.is_symlink()
        and (path / "SKILL.md").is_file()
        and (path / MANIFEST_NAME).is_file()
    )


def build_package(output_root: Path, *, force: bool = False) -> tuple[Path, Path]:
    output_root = validate_output_root(output_root)
    package_dir = output_root / PACKAGE_FOLDER
    zip_path = output_root / f"{PACKAGE_FOLDER}-local.zip"

    existing = [path for path in (package_dir, zip_path) if path.exists() or path.is_symlink()]
    if existing and not force:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(f"output already exists ({names}); pass --force to replace it")
    if force:
        for path in existing:
            if not is_recognizable_previous_output(path, zip_output=path == zip_path):
                raise ValueError(
                    f"refusing to replace unrecognized existing target: {path.name}"
                )

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".agenda-package-", dir=output_root) as temp_text:
        staging_root = Path(temp_text)
        staged_package = staging_root / PACKAGE_FOLDER
        staged_zip = staging_root / zip_path.name
        copy_runtime(staged_package)
        scan_text_files(staged_package)
        write_manifest(staged_package)
        make_zip(staged_package, staged_zip)

        for path in existing:
            remove_exact_target(path)
        os.replace(staged_package, package_dir)
        os.replace(staged_zip, zip_path)

    return package_dir, zip_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="external directory that will receive the folder and ZIP",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        package_dir, zip_path = build_package(args.output_dir, force=args.force)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))

    print(f"package_dir={package_dir}")
    print(f"zip={zip_path}")
    print(f"zip_sha256={sha256(zip_path)}")
    print(f"files={sum(1 for path in package_dir.rglob('*') if path.is_file())}")
    print(f"bytes={zip_path.stat().st_size}")


if __name__ == "__main__":
    main()
