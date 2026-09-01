#!/usr/bin/env python3
"""Small, deterministic entry point for portable agenda workflows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_SCRIPT = SCRIPT_DIR / "build_agenda.py"
EXPORT_SCRIPT = SCRIPT_DIR / "export_a4.py"


def emit(payload: dict[str, Any], *, error: bool = False) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=sys.stderr if error else sys.stdout,
    )


def run_json_command(
    command: list[str], *, env: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    raw = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "errors": [
                "agenda command returned non-JSON output",
                raw[-2000:],
            ],
        }
    if not isinstance(payload, dict):
        payload = {
            "ok": False,
            "errors": ["agenda command returned JSON that is not an object"],
        }
    return result.returncode, payload


def is_valid_agenda_file(path: Path, signature: bytes) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 1000:
            return False
        with path.open("rb") as handle:
            return handle.read(len(signature)) == signature
    except OSError:
        return False


def has_complete_agenda_pair(directory: Path) -> bool:
    return (
        is_valid_agenda_file(directory / "agenda.pdf", b"%PDF-")
        and is_valid_agenda_file(
            directory / "agenda.png", b"\x89PNG\r\n\x1a\n"
        )
    )


def copy_pairs_atomically(pairs: list[tuple[Path, Path]]) -> None:
    """Copy a small related file set with rollback if any final replace fails."""
    temporary: list[tuple[Path, Path]] = []
    backups: dict[Path, Path] = {}
    replaced: set[Path] = set()
    try:
        for source, destination in pairs:
            if not source.is_file():
                raise OSError(f"agenda transaction source is missing: {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_text = tempfile.mkstemp(
                prefix=f".{destination.name}.new-",
                dir=destination.parent,
            )
            os.close(descriptor)
            temp_path = Path(temp_text)
            shutil.copy2(source, temp_path)
            temporary.append((temp_path, destination))

        for _, destination in temporary:
            if not destination.exists():
                continue
            descriptor, backup_text = tempfile.mkstemp(
                prefix=f".{destination.name}.rollback-",
                dir=destination.parent,
            )
            os.close(descriptor)
            backup_path = Path(backup_text)
            shutil.copy2(destination, backup_path)
            backups[destination] = backup_path

        for temp_path, destination in temporary:
            os.replace(temp_path, destination)
            replaced.add(destination)
    except OSError:
        for _, destination in temporary:
            backup = backups.get(destination)
            if backup and backup.is_file():
                os.replace(backup, destination)
            elif destination in replaced and destination.is_file():
                destination.unlink()
        raise
    finally:
        for temp_path, _ in temporary:
            if temp_path.exists():
                temp_path.unlink()
        for backup_path in backups.values():
            if backup_path.exists():
                backup_path.unlink()


def emit_finalize_failure(
    payload: dict[str, Any],
    *,
    export_exit_code: int,
    last_good_paths: list[str],
) -> int:
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        errors = [f"agenda export failed with code {export_exit_code}"]
    if last_good_paths:
        next_action = (
            "Keep the previous usable PDF and PNG. Explain the conflict in plain language "
            "and offer one or two concrete choices; do not ask the user about CSS, JSON, "
            "Python, or template permissions."
        )
    else:
        next_action = (
            "No complete previous PDF and PNG pair exists. Keep the prepared agenda content, "
            "explain the conflict in plain language, and offer one or two concrete choices; "
            "do not ask the user about CSS, JSON, Python, or template permissions."
        )
    emit(
        {
            **payload,
            "ok": False,
            "errors": errors,
            "stage": "finalize_failed",
            "export_exit_code": export_exit_code,
            "last_good_preserved": bool(last_good_paths),
            "last_good_paths": last_good_paths,
            "next_action": next_action,
        },
        error=True,
    )
    return 2


def prepare(args: argparse.Namespace) -> int:
    input_path = args.input_json.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    command = [
        sys.executable,
        str(BUILD_SCRIPT),
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--html-renderer",
        args.html_renderer,
    ]
    if args.club_profile:
        command.extend(["--club-profile", args.club_profile])
    if args.update_club_profile:
        command.append("--update-club-profile")
    if args.profile_root:
        command.extend(["--profile-root", str(args.profile_root.expanduser().resolve())])

    return_code, payload = run_json_command(command)
    if return_code != 0 or payload.get("ok") is not True:
        emit(
            {
                **payload,
                "ok": False,
                "stage": "prepare_failed",
                "build_exit_code": return_code,
                "next_action": (
                    "Only ask the user for the exact missing or conflicting facts listed "
                    "in errors, update meeting.json, then run prepare again."
                ),
            },
            error=True,
        )
        return 2

    outputs = payload.get("outputs", {})
    emit(
        {
            **payload,
            "stage": "prepared",
            "next_action": (
                f"Check {outputs.get('markdown', output_dir / 'agenda.md')} for names, order, "
                "durations and location. If no material fact is unresolved and the user did not "
                "ask for a draft only, run finalize now; do not require approval of a technical preview."
            ),
            "finalize_command": (
                f'{sys.executable} "{Path(__file__).resolve()}" finalize '
                f'"{outputs.get("html", output_dir / "agenda.html")}" '
                f'--output-dir "{output_dir}"'
            ),
        }
    )
    return 0


def finalize(args: argparse.Namespace) -> int:
    html_path = args.input_html.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    if ".workbuddy" in str(SCRIPT_DIR).lower():
        environment["AGENDA_CHROME_NO_SANDBOX"] = "1"
    current_pdf = output_dir / "agenda.pdf"
    current_png = output_dir / "agenda.png"
    has_last_good = has_complete_agenda_pair(output_dir)
    last_good_paths = (
        [str(current_pdf), str(current_png)] if has_last_good else []
    )
    previous_pdf = output_dir / "agenda.previous.pdf"
    previous_png = output_dir / "agenda.previous.png"
    previous_version_paths: list[str] = []

    with tempfile.TemporaryDirectory(
        prefix="agenda-export-staging-",
        dir=output_dir.parent,
    ) as staging_text:
        staging_dir = Path(staging_text)
        try:
            return_code, payload = run_json_command(
                [
                    sys.executable,
                    str(EXPORT_SCRIPT),
                    str(html_path),
                    "--output-dir",
                    str(staging_dir),
                ],
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return emit_finalize_failure(
                {"errors": [f"agenda export could not run: {exc}"]},
                export_exit_code=2,
                last_good_paths=last_good_paths,
            )
        if return_code != 0 or payload.get("ok") is not True:
            return emit_finalize_failure(
                payload,
                export_exit_code=return_code,
                last_good_paths=last_good_paths,
            )

        staged_pdf = staging_dir / "agenda.pdf"
        staged_png = staging_dir / "agenda.png"
        if not has_complete_agenda_pair(staging_dir):
            return emit_finalize_failure(
                {"errors": ["agenda export reported success without a complete PDF and PNG pair"]},
                export_exit_code=2,
                last_good_paths=last_good_paths,
            )
        try:
            commit_pairs: list[tuple[Path, Path]] = []
            if has_last_good:
                commit_pairs.extend(
                    [
                        (current_pdf, previous_pdf),
                        (current_png, previous_png),
                    ]
                )
            commit_pairs.extend(
                [
                    (staged_pdf, current_pdf),
                    (staged_png, current_png),
                ]
            )
            copy_pairs_atomically(commit_pairs)
            if has_last_good:
                previous_version_paths = [str(previous_pdf), str(previous_png)]
        except OSError as exc:
            return emit_finalize_failure(
                {"errors": [f"agenda files could not be committed: {exc}"]},
                export_exit_code=2,
                last_good_paths=last_good_paths,
            )

    for stale_page in output_dir.glob("agenda-page-*.png"):
        if stale_page.is_file():
            try:
                stale_page.unlink()
            except OSError:
                pass
    payload = {
        **payload,
        "pdf": str(current_pdf),
        "png": str(current_png),
        "pngs": [str(current_png)],
    }
    emit(
        {
            **payload,
            "stage": "finalized",
            "previous_version_paths": previous_version_paths,
            "next_action": "Deliver the verified PDF and PNG. Do not redesign after approval.",
        }
    )
    return 0


def doctor(_: argparse.Namespace) -> int:
    try:
        import export_a4
    except ModuleNotFoundError:
        from scripts import export_a4
    chrome = export_a4.find_chrome()
    payload = {
        "ok": bool(chrome),
        "python": sys.executable,
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "chrome": chrome,
        "build_script": str(BUILD_SCRIPT),
        "export_script": str(EXPORT_SCRIPT),
    }
    if not chrome:
        payload["errors"] = ["Chrome/Chromium is required for PDF and PNG export"]
        emit(payload, error=True)
        return 2
    emit(payload)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="check local runtime")
    doctor_parser.set_defaults(handler=doctor)

    prepare_parser = subparsers.add_parser(
        "prepare", help="build validated JSON, Markdown and HTML"
    )
    prepare_parser.add_argument("input_json", type=Path)
    prepare_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    prepare_parser.add_argument("--club-profile", type=str, default=None)
    prepare_parser.add_argument("--update-club-profile", action="store_true")
    prepare_parser.add_argument(
        "--html-renderer",
        choices=("auto", "classic", "editorial"),
        default="auto",
    )
    prepare_parser.add_argument("--profile-root", type=Path, default=None, help=argparse.SUPPRESS)
    prepare_parser.set_defaults(handler=prepare)

    finalize_parser = subparsers.add_parser(
        "finalize", help="run visual audit and export one A4 PDF plus PNG"
    )
    finalize_parser.add_argument("input_html", type=Path)
    finalize_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    finalize_parser.set_defaults(handler=finalize)

    args = parser.parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
