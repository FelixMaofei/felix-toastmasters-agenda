#!/usr/bin/env python3
"""Small, deterministic entry point for portable agenda workflows."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_SCRIPT = SCRIPT_DIR / "build_agenda.py"
EXPORT_SCRIPT = SCRIPT_DIR / "export_a4.py"
RENDERER_SCRIPT = SCRIPT_DIR / "agenda_renderer.py"
V3_PREVIEW_META_RE = re.compile(
    r"<meta\s+(?=[^>]*\bname\s*=\s*['\"]agenda-workflow['\"])(?=[^>]*\bcontent\s*=\s*['\"]v3-preview['\"])[^>]*>",
    re.IGNORECASE,
)


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


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label} could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def load_v3_renderer() -> Any:
    """Load the colocated renderer without requiring scripts to be a package."""

    if not RENDERER_SCRIPT.is_file():
        raise ValueError(f"V3 renderer is not installed: {RENDERER_SCRIPT}")
    spec = importlib.util.spec_from_file_location(
        "felix_toastmasters_agenda_renderer", RENDERER_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"V3 renderer could not be loaded: {RENDERER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    render_agenda = getattr(module, "render_agenda", None)
    if not callable(render_agenda):
        raise ValueError("V3 renderer does not expose render_agenda(computed, view)")
    return render_agenda


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_v3_preview_marker(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            source = handle.read(256 * 1024)
    except (OSError, UnicodeError):
        return False
    return V3_PREVIEW_META_RE.search(source) is not None


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
    deprecated: bool = False,
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
            **({"deprecated": True} if deprecated else {}),
        },
        error=True,
    )
    return 2


def append_profile_options(command: list[str], args: argparse.Namespace) -> None:
    if args.club_profile:
        command.extend(["--club-profile", args.club_profile])
    if args.update_club_profile:
        command.append("--update-club-profile")
    if args.profile_root:
        command.extend(
            ["--profile-root", str(args.profile_root.expanduser().resolve())]
        )


def draft(args: argparse.Namespace) -> int:
    """V3 stage 1: compute meeting facts and readable Markdown only."""

    input_path = args.input_json.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    command = [
        sys.executable,
        str(BUILD_SCRIPT),
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--facts-only",
    ]
    append_profile_options(command, args)
    return_code, payload = run_json_command(command)
    if return_code != 0 or payload.get("ok") is not True:
        emit(
            {
                **payload,
                "ok": False,
                "stage": "draft_failed",
                "build_exit_code": return_code,
                "next_action": (
                    "Only ask for the missing or conflicting meeting facts listed in "
                    "errors, update meeting.json, then run draft again."
                ),
            },
            error=True,
        )
        return 2

    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        emit(
            {
                "ok": False,
                "stage": "draft_failed",
                "errors": ["agenda build returned no output manifest"],
            },
            error=True,
        )
        return 2
    computed_path = Path(
        str(outputs.get("computed_json", output_dir / "agenda.computed.json"))
    )
    markdown_path = Path(str(outputs.get("markdown", output_dir / "agenda.md")))
    diagnostics_path = Path(
        str(outputs.get("diagnostics", output_dir / "agenda.diagnostics.json"))
    )
    required = (computed_path, markdown_path, diagnostics_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        emit(
            {
                "ok": False,
                "stage": "draft_failed",
                "errors": ["agenda draft is incomplete: " + ", ".join(missing)],
            },
            error=True,
        )
        return 2

    manifest_path = output_dir / "agenda.manifest.json"
    manifest = {
        "workflow_version": 3,
        "stage": "draft",
        "source": str(input_path),
        "facts_sha256": file_sha256(computed_path),
        "outputs": {
            "computed_json": str(computed_path),
            "markdown": str(markdown_path),
            "diagnostics": str(diagnostics_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    clean_outputs = {
        "computed_json": str(computed_path),
        "markdown": str(markdown_path),
        "diagnostics": str(diagnostics_path),
        "manifest": str(manifest_path),
        **(
            {"club_profile": outputs["club_profile"]}
            if outputs.get("club_profile")
            else {}
        ),
    }
    emit(
        {
            **payload,
            "stage": "drafted",
            "outputs": clean_outputs,
            "next_action": (
                "Show agenda.md for content confirmation. Do not render a visual preview "
                "until the meeting facts are confirmed."
            ),
        }
    )
    return 0


def preview(args: argparse.Namespace) -> int:
    """V3 stage 2: render confirmed facts and a constrained view to a real PNG."""

    computed_path = args.input_computed.expanduser().resolve()
    view_path = args.view.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        computed = load_json_object(computed_path, "computed agenda")
        view = load_json_object(view_path, "agenda view")
        render_agenda = load_v3_renderer()
        rendered_html = render_agenda(
            computed,
            view,
            skill_dir=SCRIPT_DIR.parent,
        )
        if not isinstance(rendered_html, str) or "<html" not in rendered_html.lower():
            raise ValueError("V3 renderer did not return a complete HTML document")
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        emit(
            {
                "ok": False,
                "stage": "preview_failed",
                "errors": [str(exc)],
                "next_action": "Fix the visual intent only; do not change meeting facts.",
            },
            error=True,
        )
        return 2

    environment = os.environ.copy()
    if ".workbuddy" in str(SCRIPT_DIR).lower():
        environment["AGENDA_CHROME_NO_SANDBOX"] = "1"
    with tempfile.TemporaryDirectory(
        prefix="agenda-preview-staging-",
        dir=output_dir.parent,
    ) as staging_text:
        staging_dir = Path(staging_text)
        staged_html = staging_dir / "agenda.preview.html"
        staged_html.write_text(rendered_html, encoding="utf-8")
        try:
            export_code, export_payload = run_json_command(
                [
                    sys.executable,
                    str(EXPORT_SCRIPT),
                    str(staged_html),
                    "--output-dir",
                    str(staging_dir),
                ],
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            export_code = 2
            export_payload = {"ok": False, "errors": [str(exc)]}
        staged_png = staging_dir / "agenda.png"
        if (
            export_code != 0
            or export_payload.get("ok") is not True
            or not is_valid_agenda_file(staged_png, b"\x89PNG\r\n\x1a\n")
        ):
            errors = export_payload.get("errors")
            if not isinstance(errors, list) or not errors:
                errors = ["visual preview export did not produce a valid PNG"]
            emit(
                {
                    **export_payload,
                    "ok": False,
                    "stage": "preview_failed",
                    "errors": errors,
                    "export_exit_code": export_code,
                    "next_action": (
                        "Keep the previous preview. Fix the visual layer only; do not "
                        "change meeting facts."
                    ),
                },
                error=True,
            )
            return 2
        preview_html = output_dir / "agenda.preview.html"
        preview_png = output_dir / "agenda.preview.png"
        try:
            copy_pairs_atomically(
                [(staged_html, preview_html), (staged_png, preview_png)]
            )
        except OSError as exc:
            emit(
                {
                    "ok": False,
                    "stage": "preview_failed",
                    "errors": [f"preview files could not be committed: {exc}"],
                },
                error=True,
            )
            return 2

    emit(
        {
            "ok": True,
            "stage": "previewed",
            "outputs": {
                "html": str(preview_html),
                "png": str(preview_png),
            },
            "facts_sha256": file_sha256(computed_path),
            "view_sha256": file_sha256(view_path),
            "next_action": (
                "Show agenda.preview.png for visual confirmation. Export final files only "
                "after the user confirms the style."
            ),
        }
    )
    return 0


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
    append_profile_options(command, args)

    return_code, payload = run_json_command(command)
    if return_code != 0 or payload.get("ok") is not True:
        emit(
            {
                **payload,
                "ok": False,
                "deprecated": True,
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
            "deprecated": True,
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
    v3_final = bool(getattr(args, "v3_final", False))
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
    if v3_final and not has_v3_preview_marker(html_path):
        return emit_finalize_failure(
            {
                "errors": [
                    "final requires HTML created by the V3 preview stage; "
                    "agenda-workflow=v3-preview marker is missing"
                ]
            },
            export_exit_code=2,
            last_good_paths=last_good_paths,
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
                deprecated=not v3_final,
            )
        if return_code != 0 or payload.get("ok") is not True:
            return emit_finalize_failure(
                payload,
                export_exit_code=return_code,
                last_good_paths=last_good_paths,
                deprecated=not v3_final,
            )

        staged_pdf = staging_dir / "agenda.pdf"
        staged_png = staging_dir / "agenda.png"
        if not has_complete_agenda_pair(staging_dir):
            return emit_finalize_failure(
                {"errors": ["agenda export reported success without a complete PDF and PNG pair"]},
                export_exit_code=2,
                last_good_paths=last_good_paths,
                deprecated=not v3_final,
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
                deprecated=not v3_final,
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
            **({"deprecated": True} if not v3_final else {}),
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

    draft_parser = subparsers.add_parser(
        "draft", help="V3: compute facts and Markdown without generating HTML"
    )
    draft_parser.add_argument("input_json", type=Path)
    draft_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    draft_parser.add_argument("--club-profile", type=str, default=None)
    draft_parser.add_argument("--update-club-profile", action="store_true")
    draft_parser.add_argument(
        "--profile-root", type=Path, default=None, help=argparse.SUPPRESS
    )
    draft_parser.set_defaults(handler=draft)

    preview_parser = subparsers.add_parser(
        "preview", help="V3: render confirmed facts and a visual intent to HTML plus PNG"
    )
    preview_parser.add_argument("input_computed", type=Path)
    preview_parser.add_argument("--view", type=Path, required=True)
    preview_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    preview_parser.set_defaults(handler=preview)

    final_parser = subparsers.add_parser(
        "final", help="V3: export an approved preview HTML to PDF plus PNG"
    )
    final_parser.add_argument("input_html", type=Path)
    final_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    final_parser.set_defaults(handler=finalize, v3_final=True)

    prepare_parser = subparsers.add_parser(
        "prepare", help="deprecated V2: build validated JSON, Markdown and HTML"
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
        "finalize", help="deprecated V2: export one A4 PDF plus PNG"
    )
    finalize_parser.add_argument("input_html", type=Path)
    finalize_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    finalize_parser.set_defaults(handler=finalize, v3_final=False)

    args = parser.parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
