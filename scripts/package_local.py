#!/usr/bin/env python3
"""Build a clean, portable local-model installation package."""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FOLDER = "felix-toastmasters-agenda"

FILES = [
    "README.md",
    "SKILL.md",
    "agents/openai.yaml",
    "examples/club-profile.example.json",
    "examples/meeting.example.json",
    "references/agenda-rules.md",
    "references/input-schema.md",
    "references/local-model-workflow.md",
    "references/visual-system.md",
    "scripts/build_agenda.py",
    "scripts/editorial_renderer.py",
    "scripts/export_a4.py",
    "scripts/run_agenda.py",
]

DIRECTORIES = [
    "assets/fonts/noto-sans-sc",
    "assets/icons/tabler",
    "assets/layouts",
    "assets/themes",
]

PRIVATE_MARKERS = (
    "/Users/maofei",
    "明源云",
    "金地威新",
    "MBTI认识自己",
)


def copy_whitelist(target: Path) -> None:
    for relative in FILES:
        source = SKILL_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"package source is missing: {source}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    logo = SKILL_ROOT / "assets" / "toastmasters-logo.png"
    logo_destination = target / "assets" / "toastmasters-logo.png"
    logo_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(logo, logo_destination)
    for relative in DIRECTORIES:
        source = SKILL_ROOT / relative
        destination = target / relative
        shutil.copytree(source, destination)


def scan_text_files(target: Path) -> None:
    problems: list[str] = []
    for path in target.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".html",
            ".svg",
            ".txt",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in PRIVATE_MARKERS:
            if marker in text:
                problems.append(f"{path.relative_to(target)} contains {marker!r}")
    if problems:
        raise ValueError("local package privacy scan failed: " + "; ".join(problems))


def make_zip(package_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=SKILL_ROOT / "dist" / "local")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output_root = args.output_dir.expanduser().resolve()
    package_dir = output_root / PACKAGE_FOLDER
    zip_path = output_root / f"{PACKAGE_FOLDER}-local.zip"
    if package_dir.exists() or zip_path.exists():
        if not args.force:
            parser.error("output already exists; pass --force to rebuild the same target")
        if package_dir.exists():
            shutil.rmtree(package_dir)
        if zip_path.exists():
            zip_path.unlink()
    output_root.mkdir(parents=True, exist_ok=True)
    copy_whitelist(package_dir)
    scan_text_files(package_dir)
    make_zip(package_dir, zip_path)
    print(f"package_dir={package_dir}")
    print(f"zip={zip_path}")
    print(f"files={sum(1 for path in package_dir.rglob('*') if path.is_file())}")
    print(f"bytes={zip_path.stat().st_size}")


if __name__ == "__main__":
    main()
