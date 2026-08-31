#!/usr/bin/env python3
"""Small, deterministic entry point for local and weaker-model agenda workflows."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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
    return result.returncode, payload


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
                "stage": "prepare_failed",
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
                f"Read and show {outputs.get('markdown', output_dir / 'agenda.md')} to the "
                "user. Do not run finalize until the user confirms the text."
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
    environment = os.environ.copy()
    if ".workbuddy" in str(SCRIPT_DIR).lower():
        environment["AGENDA_CHROME_NO_SANDBOX"] = "1"
    return_code, payload = run_json_command(
        [
            sys.executable,
            str(EXPORT_SCRIPT),
            str(html_path),
            "--output-dir",
            str(output_dir),
        ],
        env=environment,
    )
    if return_code != 0 or payload.get("ok") is not True:
        emit(
            {
                **payload,
                "stage": "finalize_failed",
                "next_action": (
                    "Do not bypass the exporter. Reduce or rebalance the content named in "
                    "errors, run prepare again, reconfirm the text, then finalize."
                ),
            },
            error=True,
        )
        return 2
    emit(
        {
            **payload,
            "stage": "finalized",
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
