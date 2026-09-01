#!/usr/bin/env python3
"""Small, deterministic entry point for portable agenda workflows."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
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
SHA256_RE = re.compile(r"[0-9a-f]{64}")
V3_PREVIEW_MANIFEST_NAME = "agenda.preview.manifest.json"


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


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def validate_v3_preview_bundle(
    html_path: Path,
) -> tuple[list[str], Path, Path, Path]:
    """Validate the exact preview artifacts approved by the user."""

    preview_dir = html_path.parent
    manifest_path = preview_dir / V3_PREVIEW_MANIFEST_NAME
    pdf_path = preview_dir / "agenda.preview.pdf"
    png_path = preview_dir / "agenda.preview.png"
    errors: list[str] = []

    if not has_v3_preview_marker(html_path):
        errors.append(
            "final requires HTML created by the V3 preview stage; "
            "agenda-workflow=v3-preview marker is missing"
        )

    try:
        manifest = load_json_object(manifest_path, "V3 preview manifest")
    except ValueError as exc:
        errors.append(str(exc))
        return errors, manifest_path, pdf_path, png_path

    if manifest.get("workflow_version") != 3 or manifest.get("stage") != "preview":
        errors.append("V3 preview manifest has the wrong workflow version or stage")
    if manifest.get("page_count") != 1:
        errors.append("V3 preview manifest must record exactly one A4 page")

    expected_outputs = {
        "html": html_path.name,
        "pdf": pdf_path.name,
        "png": png_path.name,
    }
    if manifest.get("outputs") != expected_outputs:
        errors.append("V3 preview manifest does not describe this preview file set")

    for key in ("facts_sha256", "view_sha256"):
        if not is_sha256(manifest.get(key)):
            errors.append(f"V3 preview manifest is missing a valid {key}")

    artifacts = (
        ("HTML", html_path, None, "html_sha256"),
        ("PDF", pdf_path, b"%PDF-", "pdf_sha256"),
        ("PNG", png_path, b"\x89PNG\r\n\x1a\n", "png_sha256"),
    )
    for label, path, signature, hash_key in artifacts:
        expected_hash = manifest.get(hash_key)
        if not is_sha256(expected_hash):
            errors.append(f"V3 preview manifest is missing a valid {hash_key}")
            continue
        if signature is None:
            if not path.is_file():
                errors.append(f"V3 preview {label} is missing: {path}")
                continue
        elif not is_valid_agenda_file(path, signature):
            errors.append(f"V3 preview {label} is missing or invalid: {path}")
            continue
        try:
            actual_hash = file_sha256(path)
        except OSError as exc:
            errors.append(f"V3 preview {label} could not be read: {exc}")
            continue
        if actual_hash != expected_hash:
            errors.append(
                f"V3 preview {label} no longer matches the approved preview manifest"
            )

    return errors, manifest_path, pdf_path, png_path


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


def capture_stage(
    handler: Any,
    args: argparse.Namespace,
) -> tuple[int, dict[str, Any]]:
    """Run one CLI stage internally while keeping the outer command single-response."""

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        return_code = handler(args)
    raw = stdout.getvalue().strip() or stderr.getvalue().strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "errors": ["agenda stage returned non-JSON output", raw[-2000:]],
        }
    if not isinstance(payload, dict):
        payload = {
            "ok": False,
            "errors": ["agenda stage returned JSON that is not an object"],
        }
    return return_code, payload


def build_default_view(computed: dict[str, Any]) -> dict[str, Any]:
    """Derive the restrained V3 view used for a first visual result.

    This makes no meeting-type choice. It only exposes real data, covers every
    materialized component once, and highlights one unambiguous special item.
    """

    raw_timeline = computed.get("timeline")
    timeline = raw_timeline if isinstance(raw_timeline, list) else []
    display_columns = ["time", "activity", "owner", "duration"]
    if any(
        isinstance(item, dict)
        and isinstance(item.get("pathways"), str)
        and bool(item["pathways"].strip())
        for item in timeline
    ):
        display_columns.insert(-1, "pathways")

    special_ids = [
        str(item.get("id")).strip()
        for item in timeline
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and str(item.get("id")).strip().startswith("special:")
    ]
    emphasis = (
        {"item_id": special_ids[0], "strength": "clear"}
        if len(special_ids) == 1
        else None
    )

    operations: list[str] = []
    background: list[str] = []
    seen: set[str] = set()
    if isinstance(computed.get("backstage"), list) and computed["backstage"]:
        operations.append("backstage")
        seen.add("backstage")

    raw_blocks = computed.get("support_blocks")
    if isinstance(raw_blocks, list):
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            component_id = block.get("id")
            if not isinstance(component_id, str) or not component_id.strip():
                continue
            component_id = component_id.strip()
            if component_id in seen:
                continue
            target = operations if block.get("group") == "operations" else background
            target.append(component_id)
            seen.add(component_id)

    return {
        "view_version": 1,
        "content_emphasis": emphasis,
        "display_columns": display_columns,
        "component_flow": {
            "operations": operations,
            "background": background,
        },
        "density": "balanced",
        "design": {"text_scale": "standard", "contrast": "clear"},
    }


def is_only_single_page_overflow(payload: dict[str, Any]) -> bool:
    errors = payload.get("errors")
    return (
        isinstance(errors, list)
        and len(errors) == 1
        and isinstance(errors[0], str)
        and "does not fit on one A4 page" in errors[0]
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
    """V3 stage 2: render confirmed facts to the complete approvable file set."""

    computed_path = args.input_computed.expanduser().resolve()
    view_path = args.view.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        computed = load_json_object(computed_path, "computed agenda")
        view = load_json_object(view_path, "agenda view")
        facts_sha256 = file_sha256(computed_path)
        view_sha256 = file_sha256(view_path)
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
        staged_pdf = staging_dir / "agenda.pdf"
        staged_png = staging_dir / "agenda.png"
        if (
            export_code != 0
            or export_payload.get("ok") is not True
            or export_payload.get("pages") != 1
            or not is_valid_agenda_file(staged_pdf, b"%PDF-")
            or not is_valid_agenda_file(staged_png, b"\x89PNG\r\n\x1a\n")
        ):
            errors = export_payload.get("errors")
            if not isinstance(errors, list) or not errors:
                errors = [
                    "visual preview export did not produce one valid A4 PDF and PNG pair"
                ]
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
        preview_pdf = output_dir / "agenda.preview.pdf"
        preview_png = output_dir / "agenda.preview.png"
        preview_manifest = output_dir / V3_PREVIEW_MANIFEST_NAME
        staged_manifest = staging_dir / V3_PREVIEW_MANIFEST_NAME
        manifest = {
            "workflow_version": 3,
            "stage": "preview",
            "page_count": 1,
            "facts_sha256": facts_sha256,
            "view_sha256": view_sha256,
            "html_sha256": file_sha256(staged_html),
            "pdf_sha256": file_sha256(staged_pdf),
            "png_sha256": file_sha256(staged_png),
            "outputs": {
                "html": preview_html.name,
                "pdf": preview_pdf.name,
                "png": preview_png.name,
            },
        }
        staged_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            copy_pairs_atomically(
                [
                    (staged_html, preview_html),
                    (staged_pdf, preview_pdf),
                    (staged_png, preview_png),
                    (staged_manifest, preview_manifest),
                ]
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
                "pdf": str(preview_pdf),
                "png": str(preview_png),
                "manifest": str(preview_manifest),
            },
            "facts_sha256": facts_sha256,
            "view_sha256": view_sha256,
            "next_action": (
                "Show agenda.preview.png for visual confirmation. After approval, promote "
                "the already-rendered PDF and PNG immediately; do not render them again."
            ),
        }
    )
    return 0


def first(args: argparse.Namespace) -> int:
    """V3 fast path: confirmed meeting JSON to the first real A4 preview."""

    output_dir = args.output_dir.expanduser().resolve()
    draft_args = argparse.Namespace(
        input_json=args.input_json,
        output_dir=output_dir,
        club_profile=args.club_profile,
        update_club_profile=args.update_club_profile,
        profile_root=args.profile_root,
    )
    draft_code, draft_payload = capture_stage(draft, draft_args)
    if draft_code != 0 or draft_payload.get("ok") is not True:
        emit(
            {
                **draft_payload,
                "ok": False,
                "stage": "first_failed",
                "failed_stage": "facts",
                "next_action": (
                    "Ask only for the missing or conflicting facts listed in errors. "
                    "After the user answers, update meeting.json and run first again."
                ),
            },
            error=True,
        )
        return 2

    draft_outputs = draft_payload.get("outputs")
    if not isinstance(draft_outputs, dict):
        emit(
            {
                "ok": False,
                "stage": "first_failed",
                "failed_stage": "facts",
                "errors": ["agenda draft returned no output manifest"],
            },
            error=True,
        )
        return 2
    try:
        computed_path = Path(str(draft_outputs["computed_json"])).resolve()
        computed = load_json_object(computed_path, "computed agenda")
        view = build_default_view(computed)
        view_path = output_dir / "agenda.view.json"
        view_path.write_text(
            json.dumps(view, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (KeyError, OSError, ValueError) as exc:
        emit(
            {
                "ok": False,
                "stage": "first_failed",
                "failed_stage": "view",
                "errors": [str(exc)],
                "next_action": "Keep the computed facts and fix only the visual intent.",
            },
            error=True,
        )
        return 2

    preview_args = argparse.Namespace(
        input_computed=computed_path,
        view=view_path,
        output_dir=output_dir,
    )
    preview_code, preview_payload = capture_stage(preview, preview_args)
    compact_retry = False
    if (
        (preview_code != 0 or preview_payload.get("ok") is not True)
        and is_only_single_page_overflow(preview_payload)
    ):
        compact_retry = True
        view["density"] = "compact"
        try:
            view_path.write_text(
                json.dumps(view, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            emit(
                {
                    "ok": False,
                    "stage": "first_failed",
                    "failed_stage": "view",
                    "errors": [str(exc)],
                },
                error=True,
            )
            return 2
        preview_code, preview_payload = capture_stage(preview, preview_args)

    if preview_code != 0 or preview_payload.get("ok") is not True:
        emit(
            {
                **preview_payload,
                "ok": False,
                "stage": "first_failed",
                "failed_stage": "preview",
                "compact_retry": compact_retry,
                "next_action": (
                    "Keep agenda.md and the previous usable preview. Fix only the visual "
                    "layer; do not hide content or reduce the text scale."
                ),
            },
            error=True,
        )
        return 2

    preview_outputs = preview_payload.get("outputs")
    if not isinstance(preview_outputs, dict):
        preview_outputs = {}
    outputs = {
        "computed_json": str(computed_path),
        "markdown": str(draft_outputs.get("markdown", output_dir / "agenda.md")),
        "diagnostics": str(
            draft_outputs.get("diagnostics", output_dir / "agenda.diagnostics.json")
        ),
        "draft_manifest": str(
            draft_outputs.get("manifest", output_dir / "agenda.manifest.json")
        ),
        "view": str(view_path),
        "html": str(preview_outputs.get("html", output_dir / "agenda.preview.html")),
        "pdf": str(preview_outputs.get("pdf", output_dir / "agenda.preview.pdf")),
        "png": str(preview_outputs.get("png", output_dir / "agenda.preview.png")),
        "preview_manifest": str(
            preview_outputs.get(
                "manifest", output_dir / V3_PREVIEW_MANIFEST_NAME
            )
        ),
    }
    if draft_outputs.get("club_profile"):
        outputs["club_profile"] = str(draft_outputs["club_profile"])
    emit(
        {
            "ok": True,
            "stage": "first_previewed",
            "outputs": outputs,
            "density": view["density"],
            "compact_retry": compact_retry,
            "facts_sha256": preview_payload.get("facts_sha256"),
            "view_sha256": preview_payload.get("view_sha256"),
            "next_action": (
                "Show agenda.preview.png now. The user may request one plain-language "
                "change or approve it for immediate delivery."
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


def finalize_v3_preview(args: argparse.Namespace) -> int:
    """Promote the exact PDF and PNG already approved during V3 preview."""

    html_path = args.input_html.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    current_pdf = output_dir / "agenda.pdf"
    current_png = output_dir / "agenda.png"
    has_last_good = has_complete_agenda_pair(output_dir)
    last_good_paths = (
        [str(current_pdf), str(current_png)] if has_last_good else []
    )

    errors, manifest_path, preview_pdf, preview_png = validate_v3_preview_bundle(
        html_path
    )
    if errors:
        return emit_finalize_failure(
            {
                "errors": errors,
                "preview_manifest": str(manifest_path),
            },
            export_exit_code=2,
            last_good_paths=last_good_paths,
        )

    previous_pdf = output_dir / "agenda.previous.pdf"
    previous_png = output_dir / "agenda.previous.png"
    previous_version_paths: list[str] = []
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
                (preview_pdf, current_pdf),
                (preview_png, current_png),
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
    emit(
        {
            "ok": True,
            "pages": 1,
            "pdf": str(current_pdf),
            "png": str(current_png),
            "pngs": [str(current_png)],
            "stage": "finalized",
            "preview_manifest": str(manifest_path),
            "previous_version_paths": previous_version_paths,
            "next_action": "Deliver the verified PDF and PNG. Do not redesign after approval.",
        }
    )
    return 0


def finalize(args: argparse.Namespace) -> int:
    v3_final = bool(getattr(args, "v3_final", False))
    if v3_final:
        return finalize_v3_preview(args)

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

    first_parser = subparsers.add_parser(
        "first", help="V3: build facts and immediately create the first A4 preview"
    )
    first_parser.add_argument("input_json", type=Path)
    first_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    first_parser.add_argument("--club-profile", type=str, default=None)
    first_parser.add_argument("--update-club-profile", action="store_true")
    first_parser.add_argument(
        "--profile-root", type=Path, default=None, help=argparse.SUPPRESS
    )
    first_parser.set_defaults(handler=first)

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
        "preview", help="V3: render confirmed facts to approvable HTML, PDF and PNG"
    )
    preview_parser.add_argument("input_computed", type=Path)
    preview_parser.add_argument("--view", type=Path, required=True)
    preview_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    preview_parser.set_defaults(handler=preview)

    final_parser = subparsers.add_parser(
        "final", help="V3: instantly promote an approved preview PDF and PNG"
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
