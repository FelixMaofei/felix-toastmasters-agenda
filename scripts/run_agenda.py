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
from copy import deepcopy
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_SCRIPT = SCRIPT_DIR / "build_agenda.py"
EXPORT_SCRIPT = SCRIPT_DIR / "export_a4.py"
RENDERER_SCRIPT = SCRIPT_DIR / "agenda_renderer.py"
SIMPLE_INPUT_SCRIPT = SCRIPT_DIR / "simple_input.py"
BUNDLED_PROFILE_ROOT = SCRIPT_DIR.parent / "profiles"
V3_PREVIEW_META_RE = re.compile(
    r"<meta\s+(?=[^>]*\bname\s*=\s*['\"]agenda-workflow['\"])(?=[^>]*\bcontent\s*=\s*['\"]v3-preview['\"])[^>]*>",
    re.IGNORECASE,
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
V3_PREVIEW_MANIFEST_NAME = "agenda.preview.manifest.json"
V3_VIEW_NAME = "agenda.view.json"
V3_VIEW_PATCH_NAME = "agenda.view.patch.json"
HEADLESS_RAF_POLYFILL = """<script id="agenda-headless-raf">
window.requestAnimationFrame = (callback) => window.setTimeout(
  () => callback(window.performance.now()), 16
);
</script>"""


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


def load_agenda_builder() -> Any:
    """Load the fact engine so first can call it directly rather than shelling out."""

    if not BUILD_SCRIPT.is_file():
        raise ValueError(f"agenda builder is not installed: {BUILD_SCRIPT}")
    spec = importlib.util.spec_from_file_location(
        "felix_toastmasters_agenda_builder", BUILD_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"agenda builder could not be loaded: {BUILD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    required = (
        "build_agenda",
        "deep_merge",
        "is_unresolved",
        "load_json",
        "normalized_club_name",
        "render_markdown",
        "resolve_profile_relative_paths",
        "stored_club_profile_path",
        "write_club_profile",
    )
    missing = [name for name in required if not callable(getattr(module, name, None))]
    if missing:
        raise ValueError(
            "agenda builder is missing required functions: " + ", ".join(missing)
        )
    return module


def load_simple_input() -> Any:
    """Load the small agent-facing input adapter when a simple payload is used."""

    if not SIMPLE_INPUT_SCRIPT.is_file():
        raise ValueError(f"simple input adapter is not installed: {SIMPLE_INPUT_SCRIPT}")
    spec = importlib.util.spec_from_file_location(
        "felix_toastmasters_agenda_simple_input", SIMPLE_INPUT_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise ValueError(
            f"simple input adapter could not be loaded: {SIMPLE_INPUT_SCRIPT}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    for name in ("is_simple_input", "convert_simple_input", "SimpleInputError"):
        if not hasattr(module, name):
            raise ValueError(f"simple input adapter is missing {name}")
    return module


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def stabilize_headless_visual_audit(source: str) -> str:
    """Make the renderer audit progress on headless Macs without a display link."""

    if "agenda-visual-audit" not in source or "<body>" not in source:
        return source
    return source.replace("<body>", f"<body>\n{HEADLESS_RAF_POLYFILL}", 1)


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
    """Validate the exact HTML/PDF/PNG set already shown to the user."""

    preview_dir = html_path.parent
    manifest_path = preview_dir / V3_PREVIEW_MANIFEST_NAME
    pdf_path = preview_dir / "agenda.preview.pdf"
    png_path = preview_dir / "agenda.preview.png"
    errors: list[str] = []

    if not has_v3_preview_marker(html_path):
        errors.append(
            "final requires HTML created by first; "
            "agenda-workflow=v3-preview marker is missing"
        )

    try:
        manifest = load_json_object(manifest_path, "preview manifest")
    except ValueError as exc:
        errors.append(str(exc))
        return errors, manifest_path, pdf_path, png_path

    if manifest.get("workflow_version") != 3 or manifest.get("stage") != "preview":
        errors.append("preview manifest has the wrong workflow version or stage")
    if manifest.get("page_count") != 1:
        errors.append("preview manifest must record exactly one A4 page")
    expected_outputs = {
        "html": html_path.name,
        "pdf": pdf_path.name,
        "png": png_path.name,
    }
    if manifest.get("outputs") != expected_outputs:
        errors.append("preview manifest does not describe this preview file set")

    for key in ("facts_sha256", "view_sha256"):
        if not is_sha256(manifest.get(key)):
            errors.append(f"preview manifest is missing a valid {key}")

    artifacts = (
        ("HTML", html_path, None, "html_sha256"),
        ("PDF", pdf_path, b"%PDF-", "pdf_sha256"),
        ("PNG", png_path, b"\x89PNG\r\n\x1a\n", "png_sha256"),
    )
    for label, path, signature, hash_key in artifacts:
        expected_hash = manifest.get(hash_key)
        if not is_sha256(expected_hash):
            errors.append(f"preview manifest is missing a valid {hash_key}")
            continue
        if signature is None:
            if not path.is_file():
                errors.append(f"preview {label} is missing: {path}")
                continue
        elif not is_valid_agenda_file(path, signature):
            errors.append(f"preview {label} is missing or invalid: {path}")
            continue
        try:
            actual_hash = file_sha256(path)
        except OSError as exc:
            errors.append(f"preview {label} could not be read: {exc}")
            continue
        if actual_hash != expected_hash:
            errors.append(
                f"preview {label} no longer matches the approved preview manifest"
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


def positive_half_minute(value: str) -> int | float:
    """Parse a positive CLI duration in exact half-minute increments."""

    text = value.strip()
    if re.fullmatch(r"(?:\d+)(?:\.0|\.5)?", text) is None:
        raise argparse.ArgumentTypeError(
            "must be a positive number in 0.5-minute increments"
        )
    number = float(text)
    if number <= 0:
        raise argparse.ArgumentTypeError(
            "must be a positive number in 0.5-minute increments"
        )
    return int(number) if number.is_integer() else number


def _same_minutes(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return abs(float(left) - float(right)) < 1e-9


def simple_overtime_gate(
    computed: dict[str, Any],
    confirmation: int | float | None,
) -> dict[str, Any] | None:
    """Return an Agent-facing stop payload when simple-input overtime is unresolved.

    The business engine remains the authority for the timeline calculation.  This
    gate only separates an initial overrun report from the explicit second CLI run
    that follows a user's approval.
    """

    raw_delta = computed.get("delta_minutes")
    delta = (
        raw_delta
        if isinstance(raw_delta, (int, float)) and not isinstance(raw_delta, bool)
        else None
    )
    if confirmation is None:
        if delta is None or delta <= 0:
            return None
        return {
            "error_type": "overtime_confirmation_required",
            "required_overtime_minutes": delta,
            "provided_overtime_minutes": None,
            "proposed_final_end": computed.get("final_end"),
            "next_action": (
                f"Stop and ask the user to approve exactly {delta:g} overtime minutes "
                f"(ending at {computed.get('final_end')}) or reduce content. Do not "
                "change meeting.end, do not write approved_overtime_minutes into "
                "meeting.json, and do not approve it yourself or use "
                "--confirm-overtime-minutes in this same turn. Only after the user "
                f"explicitly agrees, rerun first with --confirm-overtime-minutes {delta:g}."
            ),
        }
    if delta is None or delta <= 0:
        return {
            "error_type": "overtime_confirmation_rejected",
            "required_overtime_minutes": None,
            "provided_overtime_minutes": confirmation,
            "proposed_final_end": computed.get("final_end"),
            "next_action": (
                "Stop: there is no current overtime to approve. Remove "
                "--confirm-overtime-minutes; do not store approval in meeting.json "
                "or change meeting.end to manufacture a match."
            ),
        }
    if not _same_minutes(confirmation, delta):
        return {
            "error_type": "overtime_confirmation_mismatch",
            "required_overtime_minutes": delta,
            "provided_overtime_minutes": confirmation,
            "proposed_final_end": computed.get("final_end"),
            "next_action": (
                f"Stop: the current overrun is {delta:g} minutes, not "
                f"{confirmation:g}. Do not change meeting.end or approve it yourself. "
                f"Ask the user to approve exactly {delta:g} minutes or reduce content; "
                "only after explicit approval rerun first with "
                f"--confirm-overtime-minutes {delta:g}."
            ),
        }
    return None


def duration_confirmation_gate(computed: dict[str, Any]) -> dict[str, Any] | None:
    """Turn unconfirmed break/sharing proposals into one Agent-facing question."""

    raw_items = computed.get("duration_confirmation_items")
    if not isinstance(raw_items, list) or not raw_items:
        return None
    items = [item for item in raw_items if isinstance(item, dict)]
    if not items:
        return None
    suggested = computed.get("suggested_agenda_overrides")
    if not isinstance(suggested, list):
        suggested = []
    zh_labels = {
        "photo_break": "合影＋休息",
        "sharing": "真情分享",
    }
    proposals = "、".join(
        f"{zh_labels.get(str(item.get('id')), str(item.get('label', item.get('id', '环节'))))} "
        f"{item.get('suggested_minutes')} 分钟"
        for item in items
    )
    return {
        "error_type": "duration_confirmation_required",
        "required_duration_confirmations": items,
        "suggested_agenda_overrides": suggested,
        "next_action": (
            f"Stop and ask the user once: “我为你默认安排了{proposals}，你觉得 OK 吗？” "
            "If the user agrees, add every suggested entry to agenda_overrides and "
            "rerun first. If not, record the durations they choose or explicitly disable "
            "the unwanted item; do not infer either duration from spare meeting time."
        ),
    }


PROFILE_USER_FIELDS = (
    ("default_location", "常用地点"),
    ("language", "会单语言"),
    ("officers", "官员名单"),
    ("club_intro", "俱乐部简介"),
    ("join_info", "入会方式"),
    ("vpm_qr_image", "入会二维码"),
)


def profile_feedback(
    builder: Any,
    profile_path: Path | None,
    status: str,
) -> dict[str, Any]:
    """Describe only profile facts that were actually persisted or reused."""

    if profile_path is None or not profile_path.is_file():
        return {"status": "not_used", "saved_fields": [], "saved_labels": []}
    profile_data = builder.load_json(profile_path)
    club = profile_data.get("club", {})
    if not isinstance(club, dict):
        club = {}
    fields: list[str] = []
    labels: list[str] = []
    for field, label in PROFILE_USER_FIELDS:
        value = club.get(field)
        if value in (None, "", [], {}):
            continue
        fields.append(field)
        labels.append(label)
    custom_blocks = club.get("custom_support_blocks")
    if isinstance(custom_blocks, list) and custom_blocks:
        fields.append("custom_support_blocks")
        for block in custom_blocks:
            if not isinstance(block, dict):
                continue
            title = str(block.get("title", "")).strip()
            if title and title not in labels:
                labels.append(title)
    if status in {"created", "updated"}:
        message = (
            "已记住这家俱乐部的长期资料"
            + ("：" + "、".join(labels) if labels else "")
            + "。下次制作会单时，不需要再重复提供这些内容，只需告诉我本期角色接龙和变化。"
        )
    elif status == "bundled":
        message = (
            "已使用 Skill 内置的公开俱乐部资料"
            + ("：" + "、".join(labels) if labels else "")
            + "。你只需继续提供本期角色接龙和变化；本期明确内容仍然优先。"
        )
    else:
        message = (
            "已沿用这家俱乐部此前保存的长期资料"
            + ("：" + "、".join(labels) if labels else "")
            + "。本期明确内容仍然优先。"
        )
    return {
        "status": status,
        "saved_fields": fields,
        "saved_labels": labels,
        "user_message": message,
    }


def compute_facts(
    input_path: Path,
    output_dir: Path,
    *,
    club_profile: str | None = None,
    update_club_profile: bool = False,
    profile_root: Path | None = None,
    confirm_overtime_minutes: int | float | None = None,
) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
    """Build and persist the fact layer without invoking another CLI."""

    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stored_profile_path: Path | None = None
    stored_profile_existed = False
    profile_source_path: Path | None = None
    bundled_profile_used = False
    simple_mode = False
    try:
        if not input_path.is_file():
            raise ValueError(f"input JSON does not exist: {input_path}")
        if update_club_profile and not club_profile:
            raise ValueError("--update-club-profile requires --club-profile")
        if profile_root is not None and not club_profile:
            raise ValueError("--profile-root requires --club-profile")
        builder = load_agenda_builder()
        data = builder.load_json(input_path)
        simple_mode = isinstance(data, dict) and "simple_version" in data
        if simple_mode:
            simple_input = load_simple_input()
            try:
                data = simple_input.convert_simple_input(data)
            except simple_input.SimpleInputError as exc:
                payload = exc.to_payload()
                error_codes = {
                    issue.get("code")
                    for issue in payload.get("errors", [])
                    if isinstance(issue, dict)
                }
                if "overtime_approval_not_allowed" in error_codes:
                    next_action = (
                        "Remove meeting.approved_overtime_minutes from the simple JSON. "
                        "Run first without overtime approval and stop for the user's answer "
                        "if an overrun is reported. Do not change meeting.end and do not "
                        "approve overtime in the same turn."
                    )
                else:
                    next_action = (
                        "Continue the conversation using the listed unresolved items. "
                        "Group related questions when helpful, do not repeat confirmed facts, "
                        "then update the same JSON and run confirm again."
                    )
                payload.update(
                    {
                        "warnings": [],
                        "next_action": next_action,
                    }
                )
                return 2, payload, None
        elif confirm_overtime_minutes is not None:
            raise ValueError(
                "--confirm-overtime-minutes is only valid for simple_version 1 input; "
                "canonical input keeps its existing approved_overtime_minutes interface"
            )
        if club_profile:
            resolved_root = (
                profile_root.expanduser().resolve()
                if profile_root is not None
                else builder.PROFILE_ROOT
            )
            stored_profile_path = builder.stored_club_profile_path(
                club_profile, profile_root=resolved_root
            )
            stored_profile_existed = stored_profile_path.is_file()
            profile_source_path = stored_profile_path if stored_profile_existed else None
            if profile_source_path is None and profile_root is None:
                bundled_path = builder.stored_club_profile_path(
                    club_profile, profile_root=BUNDLED_PROFILE_ROOT
                )
                if bundled_path.is_file():
                    profile_source_path = bundled_path
                    bundled_profile_used = True
            if profile_source_path is not None:
                profile_data = builder.resolve_profile_relative_paths(
                    builder.load_json(profile_source_path), profile_source_path
                )
                stored_name = profile_data.get("club", {}).get("name", "")
                if builder.normalized_club_name(
                    stored_name
                ) != builder.normalized_club_name(club_profile):
                    raise ValueError(
                        "stored club profile identity does not match --club-profile"
                    )
                data = builder.deep_merge(profile_data, data)
                merged_name = data.get("club", {}).get("name", "")
                if builder.normalized_club_name(
                    merged_name
                ) != builder.normalized_club_name(club_profile):
                    raise ValueError(
                        "input club.name does not match the stored --club-profile"
                    )
            else:
                club = data.setdefault("club", {})
                if not isinstance(club, dict):
                    raise ValueError("club must be an object")
                input_name = club.get("name")
                if builder.is_unresolved(input_name):
                    club["name"] = club_profile
                elif builder.normalized_club_name(
                    input_name
                ) != builder.normalized_club_name(club_profile):
                    raise ValueError("input club.name does not match --club-profile")
        if simple_mode:
            meeting = data.setdefault("meeting", {})
            if not isinstance(meeting, dict):
                raise ValueError("meeting must be an object")
            # Override any stale profile value.  Approval is intentionally
            # ephemeral and never comes from the simple JSON or club profile.
            meeting["approved_overtime_minutes"] = (
                confirm_overtime_minutes
                if confirm_overtime_minutes is not None
                else 0
            )
        computed, errors, warnings = builder.build_agenda(
            data,
            source_dir=input_path.parent,
            facts_only=True,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "ok": False,
            "stage": "needs_input",
            "errors": [str(exc)],
            "warnings": [],
            "next_action": (
                "Correct the listed meeting input, then run first again. "
                "Do not change visual settings."
            ),
        }
        return 2, payload, None

    computed_summary = computed.get("computed", {})
    if not isinstance(computed_summary, dict):
        computed_summary = {}
    duration_stop = duration_confirmation_gate(computed_summary)
    overtime_stop = (
        simple_overtime_gate(computed_summary, confirm_overtime_minutes)
        if simple_mode and duration_stop is None
        else None
    )
    summary = {
        "ok": not errors,
        "computed": computed_summary,
        "warnings": warnings,
        "errors": errors,
    }
    diagnostics_path = output_dir / "agenda.diagnostics.json"
    diagnostics_path.write_bytes(json_bytes(summary))
    if errors or overtime_stop is not None or duration_stop is not None:
        next_action = (
            overtime_stop["next_action"]
            if overtime_stop is not None
            else duration_stop["next_action"]
            if duration_stop is not None
            else (
                "Explain the unresolved or conflicting facts and continue the conversation. "
                "Do not repeat confirmed facts. After the user answers, update meeting.json "
                "and run confirm again."
            )
        )
        return (
            2,
            {
                **summary,
                "ok": False,
                "stage": "needs_input",
                "outputs": {"diagnostics": str(diagnostics_path)},
                **(
                    {
                        key: value
                        for key, value in overtime_stop.items()
                        if key != "next_action"
                    }
                    if overtime_stop is not None
                    else {
                        key: value
                        for key, value in (duration_stop or {}).items()
                        if key != "next_action"
                    }
                ),
                "next_action": next_action,
            },
            None,
        )

    computed_result = deepcopy(computed)
    computed_result.pop("_assets", None)
    computed_path = output_dir / "agenda.computed.json"
    markdown_path = output_dir / "agenda.md"
    draft_manifest_path = output_dir / "agenda.manifest.json"
    computed_data = json_bytes(computed_result)
    draft_manifest = {
        "workflow_version": 3,
        "stage": "facts",
        "source": str(input_path),
        "facts_sha256": bytes_sha256(computed_data),
        "outputs": {
            "computed_json": computed_path.name,
            "markdown": markdown_path.name,
            "diagnostics": diagnostics_path.name,
        },
    }
    with tempfile.TemporaryDirectory(
        prefix="agenda-facts-staging-", dir=output_dir.parent
    ) as staging_text:
        staging_dir = Path(staging_text)
        staged_computed = staging_dir / computed_path.name
        staged_markdown = staging_dir / markdown_path.name
        staged_diagnostics = staging_dir / diagnostics_path.name
        staged_manifest = staging_dir / draft_manifest_path.name
        staged_computed.write_bytes(computed_data)
        staged_markdown.write_text(builder.render_markdown(computed), encoding="utf-8")
        staged_diagnostics.write_bytes(json_bytes(summary))
        staged_manifest.write_bytes(json_bytes(draft_manifest))
        try:
            copy_pairs_atomically(
                [
                    (staged_computed, computed_path),
                    (staged_markdown, markdown_path),
                    (staged_diagnostics, diagnostics_path),
                    (staged_manifest, draft_manifest_path),
                ]
            )
        except OSError as exc:
            return (
                2,
                {
                    **summary,
                    "ok": False,
                    "stage": "facts_failed",
                    "errors": [f"fact files could not be saved: {exc}"],
                },
                None,
            )

    saved_profile_path: Path | None = None
    profile_status = "not_used"
    try:
        if stored_profile_path and update_club_profile:
            builder.write_club_profile(
                data,
                stored_profile_path,
                source_dir=input_path.parent,
            )
            saved_profile_path = stored_profile_path
            profile_status = "updated" if stored_profile_existed else "created"
        elif stored_profile_path and stored_profile_existed:
            saved_profile_path = stored_profile_path
            profile_status = "reused"
        elif bundled_profile_used and profile_source_path is not None:
            saved_profile_path = profile_source_path
            profile_status = "bundled"
        elif stored_profile_path:
            builder.write_club_profile(
                data,
                stored_profile_path,
                source_dir=input_path.parent,
            )
            saved_profile_path = stored_profile_path
            profile_status = "created"
    except (OSError, ValueError) as exc:
        return (
            2,
            {
                **summary,
                "ok": False,
                "stage": "facts_failed",
                "errors": [f"club profile could not be saved: {exc}"],
            },
            None,
        )

    outputs = {
        "computed_json": str(computed_path),
        "markdown": str(markdown_path),
        "diagnostics": str(diagnostics_path),
        "manifest": str(draft_manifest_path),
    }
    if saved_profile_path:
        outputs["club_profile"] = str(saved_profile_path)
    profile = profile_feedback(builder, saved_profile_path, profile_status)
    return (
        0,
        {
            **summary,
            "stage": "facts_ready",
            "outputs": outputs,
            "profile": profile,
        },
        computed_result,
    )


def build_default_view(computed: dict[str, Any]) -> dict[str, Any]:
    """Choose a complete neutral view using only materialized fact data."""

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


def merge_view_patch(
    base: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    """Deep-merge a partial semantic view; arrays intentionally replace arrays."""

    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_view_patch(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def is_only_single_page_overflow(payload: dict[str, Any]) -> bool:
    errors = payload.get("errors")
    if not (
        isinstance(errors, list)
        and len(errors) == 1
        and isinstance(errors[0], str)
    ):
        return False
    error = errors[0]
    if "does not fit on one A4 page" in error:
        return True
    capacity_codes = (
        '"code": "page_height"',
        '"code": "page_overflow"',
        '"code": "outside_page"',
        '"code": "vertical_clip"',
    )
    return "agenda visual audit failed" in error and any(
        code in error for code in capacity_codes
    )


def render_preview_bundle(
    computed: dict[str, Any],
    view: dict[str, Any],
    output_dir: Path,
    *,
    facts_sha256: str,
    view_patch: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Render and atomically install the complete approvable preview bundle."""

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    view_data = json_bytes(view)
    view_sha256 = bytes_sha256(view_data)
    try:
        render_agenda = load_v3_renderer()
        rendered_html = render_agenda(computed, view, skill_dir=SCRIPT_DIR.parent)
        if not isinstance(rendered_html, str) or "<html" not in rendered_html.lower():
            raise ValueError("V3 renderer did not return a complete HTML document")
        rendered_html = stabilize_headless_visual_audit(rendered_html)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return (
            2,
            {
                "ok": False,
                "stage": "preview_failed",
                "errors": [str(exc)],
                "next_action": (
                    "Keep the previous usable preview. Correct only the semantic view; "
                    "do not change meeting facts."
                ),
            },
        )

    environment = os.environ.copy()
    if ".workbuddy" in str(SCRIPT_DIR).lower():
        environment["AGENDA_CHROME_NO_SANDBOX"] = "1"
    with tempfile.TemporaryDirectory(
        prefix="agenda-preview-staging-", dir=output_dir.parent
    ) as staging_text:
        staging_dir = Path(staging_text)
        staged_html = staging_dir / "agenda.preview.html"
        staged_view = staging_dir / V3_VIEW_NAME
        staged_html.write_text(rendered_html, encoding="utf-8")
        staged_view.write_bytes(view_data)
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
            return (
                2,
                {
                    **export_payload,
                    "ok": False,
                    "stage": "preview_failed",
                    "errors": errors,
                    "export_exit_code": export_code,
                    "next_action": (
                        "Keep the previous usable preview. Fix the visual result without "
                        "hiding or truncating meeting content."
                    ),
                },
            )

        preview_html = output_dir / staged_html.name
        preview_pdf = output_dir / "agenda.preview.pdf"
        preview_png = output_dir / "agenda.preview.png"
        preview_manifest = output_dir / V3_PREVIEW_MANIFEST_NAME
        view_path = output_dir / V3_VIEW_NAME
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
        staged_manifest.write_bytes(json_bytes(manifest))
        pairs = [
            (staged_html, preview_html),
            (staged_pdf, preview_pdf),
            (staged_png, preview_png),
            (staged_manifest, preview_manifest),
            (staged_view, view_path),
        ]
        patch_path: Path | None = None
        if view_patch is not None:
            staged_patch = staging_dir / V3_VIEW_PATCH_NAME
            staged_patch.write_bytes(json_bytes(view_patch))
            patch_path = output_dir / V3_VIEW_PATCH_NAME
            pairs.append((staged_patch, patch_path))
        try:
            copy_pairs_atomically(pairs)
        except OSError as exc:
            return (
                2,
                {
                    "ok": False,
                    "stage": "preview_failed",
                    "errors": [f"preview files could not be committed: {exc}"],
                    "next_action": "Keep the previous usable preview.",
                },
            )

    outputs = {
        "view": str(view_path),
        "html": str(preview_html),
        "pdf": str(preview_pdf),
        "png": str(preview_png),
        "preview_manifest": str(preview_manifest),
    }
    if patch_path is not None:
        outputs["view_patch"] = str(patch_path)
    return (
        0,
        {
            "ok": True,
            "stage": "preview_ready",
            "outputs": outputs,
            "facts_sha256": facts_sha256,
            "view_sha256": view_sha256,
            "density": view.get("density"),
            "next_action": (
                "Show agenda.preview.png now. The user may describe a change in plain "
                "language or approve this exact preview for immediate delivery."
            ),
        },
    )


def draft(args: argparse.Namespace) -> int:
    """Compatibility command for fact-only output."""

    code, payload, _ = compute_facts(
        args.input_json,
        args.output_dir,
        club_profile=getattr(args, "club_profile", None),
        update_club_profile=bool(getattr(args, "update_club_profile", False)),
        profile_root=getattr(args, "profile_root", None),
    )
    if code == 0:
        payload = {
            **payload,
            "stage": "drafted",
            "next_action": "Use first for the normal image-first workflow.",
        }
    emit(payload, error=code != 0)
    return code


def confirm_text(args: argparse.Namespace) -> int:
    """Build the fact layer and stop for human-readable content confirmation."""

    code, payload, _ = compute_facts(
        args.input_json,
        args.output_dir,
        club_profile=getattr(args, "club_profile", None),
        update_club_profile=bool(getattr(args, "update_club_profile", False)),
        profile_root=getattr(args, "profile_root", None),
        confirm_overtime_minutes=getattr(args, "confirm_overtime_minutes", None),
    )
    if code != 0:
        emit(payload, error=True)
        return 2

    outputs = dict(payload.get("outputs", {}))
    computed_path = Path(str(outputs["computed_json"])).expanduser().resolve()
    markdown_path = Path(str(outputs["markdown"])).expanduser().resolve()
    facts_sha256 = file_sha256(computed_path)
    outputs["confirmation_markdown"] = str(markdown_path)
    emit(
        {
            **payload,
            "stage": "text_confirmation_ready",
            "outputs": outputs,
            "facts_sha256": facts_sha256,
            "next_action": (
                "Show the complete confirmation Markdown to the user. Ask them to check "
                "all visible wording, names, order, durations, location, club information "
                "and joining information. Do not render an image until the user explicitly "
                "confirms it."
            ),
        }
    )
    return 0


def image_from_confirmed(args: argparse.Namespace) -> int:
    """Render only the exact computed facts the user has already confirmed."""

    try:
        computed_path = args.input_computed.expanduser().resolve()
        computed = load_json_object(computed_path, "confirmed agenda facts")
        current_hash = file_sha256(computed_path)
        confirmed_hash = str(args.confirmed_sha256).strip().lower()
        if confirmed_hash != current_hash:
            raise ValueError(
                "confirmed text no longer matches agenda.computed.json; show the updated "
                "text confirmation before rendering"
            )
        output_dir = args.output_dir.expanduser().resolve()
        explicit_patch = getattr(args, "view_patch", None)
        persisted_patch = output_dir / V3_VIEW_PATCH_NAME
        patch_path = (
            explicit_patch.expanduser().resolve()
            if explicit_patch is not None
            else persisted_patch
            if persisted_patch.is_file()
            else None
        )
        patch = (
            load_json_object(patch_path, "agenda view patch")
            if patch_path is not None
            else None
        )
        view = build_default_view(computed)
        if patch is not None:
            view = merge_view_patch(view, patch)
    except (OSError, ValueError) as exc:
        emit(
            {
                "ok": False,
                "stage": "text_confirmation_required",
                "errors": [str(exc)],
                "next_action": "Run confirm again and show the updated text before rendering.",
            },
            error=True,
        )
        return 2

    preview_code, preview_payload = render_preview_bundle(
        computed,
        view,
        output_dir,
        facts_sha256=current_hash,
        view_patch=patch,
    )
    compact_retry = False
    patch_controls_density = patch is not None and "density" in patch
    if (
        preview_code != 0
        and not patch_controls_density
        and is_only_single_page_overflow(preview_payload)
    ):
        compact_retry = True
        view["density"] = "compact"
        preview_code, preview_payload = render_preview_bundle(
            computed,
            view,
            output_dir,
            facts_sha256=current_hash,
            view_patch=patch,
        )
    if preview_code != 0:
        emit({**preview_payload, "compact_retry": compact_retry}, error=True)
        return 2

    preview_outputs = dict(preview_payload.get("outputs", {}))
    preview_outputs["computed_json"] = str(computed_path)
    markdown_path = computed_path.with_name("agenda.md")
    if markdown_path.is_file():
        preview_outputs["confirmation_markdown"] = str(markdown_path)
    emit(
        {
            **preview_payload,
            "stage": "preview_ready",
            "outputs": preview_outputs,
            "computed": computed.get("computed", {}),
            "language": computed.get("club", {}).get("language"),
            "warnings": [],
            "errors": [],
            "compact_retry": compact_retry,
        }
    )
    return 0


def preview(args: argparse.Namespace) -> int:
    """Compatibility command for rendering an already-computed fact file."""

    try:
        computed_path = args.input_computed.expanduser().resolve()
        computed = load_json_object(computed_path, "computed agenda")
        view = load_json_object(args.view.expanduser().resolve(), "agenda view")
        facts_hash = file_sha256(computed_path)
    except (OSError, ValueError) as exc:
        payload = {"ok": False, "stage": "preview_failed", "errors": [str(exc)]}
        emit(payload, error=True)
        return 2
    code, payload = render_preview_bundle(
        computed,
        view,
        args.output_dir,
        facts_sha256=facts_hash,
    )
    emit(payload, error=code != 0)
    return code


def first(args: argparse.Namespace) -> int:
    """Normal path: meeting facts to a complete one-page A4 preview."""

    output_dir = args.output_dir.expanduser().resolve()
    fact_code, fact_payload, computed = compute_facts(
        args.input_json,
        output_dir,
        club_profile=getattr(args, "club_profile", None),
        update_club_profile=bool(getattr(args, "update_club_profile", False)),
        profile_root=getattr(args, "profile_root", None),
        confirm_overtime_minutes=getattr(args, "confirm_overtime_minutes", None),
    )
    if fact_code != 0 or computed is None:
        emit(fact_payload, error=True)
        return 2

    explicit_patch = getattr(args, "view_patch", None)
    persisted_patch = output_dir / V3_VIEW_PATCH_NAME
    patch_path = (
        explicit_patch.expanduser().resolve()
        if explicit_patch is not None
        else persisted_patch
        if persisted_patch.is_file()
        else None
    )
    try:
        patch = (
            load_json_object(patch_path, "agenda view patch")
            if patch_path is not None
            else None
        )
        view = build_default_view(computed)
        if patch is not None:
            view = merge_view_patch(view, patch)
    except (OSError, ValueError) as exc:
        emit(
            {
                "ok": False,
                "stage": "preview_failed",
                "errors": [str(exc)],
                "next_action": "Correct only the view patch, then run first again.",
            },
            error=True,
        )
        return 2

    facts_outputs = fact_payload.get("outputs", {})
    computed_path = Path(
        str(facts_outputs.get("computed_json", output_dir / "agenda.computed.json"))
    )
    facts_hash = file_sha256(computed_path)
    preview_code, preview_payload = render_preview_bundle(
        computed,
        view,
        output_dir,
        facts_sha256=facts_hash,
        view_patch=patch,
    )
    compact_retry = False
    patch_controls_density = patch is not None and "density" in patch
    if (
        preview_code != 0
        and not patch_controls_density
        and is_only_single_page_overflow(preview_payload)
    ):
        compact_retry = True
        view["density"] = "compact"
        preview_code, preview_payload = render_preview_bundle(
            computed,
            view,
            output_dir,
            facts_sha256=facts_hash,
            view_patch=patch,
        )

    if preview_code != 0:
        emit(
            {
                **preview_payload,
                "compact_retry": compact_retry,
            },
            error=True,
        )
        return 2

    preview_outputs = preview_payload.get("outputs", {})
    outputs = {
        **facts_outputs,
        **preview_outputs,
    }
    emit(
        {
            **preview_payload,
            "stage": "preview_ready",
            "outputs": outputs,
            "computed": fact_payload.get("computed", {}),
            "language": computed.get("club", {}).get("language"),
            "warnings": fact_payload.get("warnings", []),
            "errors": [],
            "compact_retry": compact_retry,
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
    """Promote the already-rendered preview bytes without opening a browser."""

    html_path = args.input_html.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    current_pdf = output_dir / "agenda.pdf"
    current_png = output_dir / "agenda.png"
    has_last_good = has_complete_agenda_pair(output_dir)
    last_good_paths = [str(current_pdf), str(current_png)] if has_last_good else []

    errors, manifest_path, preview_pdf, preview_png = validate_v3_preview_bundle(
        html_path
    )
    if errors:
        return emit_finalize_failure(
            {"errors": errors, "preview_manifest": str(manifest_path)},
            export_exit_code=2,
            last_good_paths=last_good_paths,
        )

    previous_pdf = output_dir / "agenda.previous.pdf"
    previous_png = output_dir / "agenda.previous.png"
    previous_version_paths: list[str] = []
    commit_pairs: list[tuple[Path, Path]] = []
    if has_last_good:
        commit_pairs.extend(
            [(current_pdf, previous_pdf), (current_png, previous_png)]
        )
    commit_pairs.extend([(preview_pdf, current_pdf), (preview_png, current_png)])
    try:
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
            "stage": "finalized",
            "pages": 1,
            "pdf": str(current_pdf),
            "png": str(current_png),
            "pngs": [str(current_png)],
            "preview_manifest": str(manifest_path),
            "previous_version_paths": previous_version_paths,
            "next_action": "Deliver the PDF and PNG without redesigning them.",
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
                deprecated=True,
            )
        if return_code != 0 or payload.get("ok") is not True:
            return emit_finalize_failure(
                payload,
                export_exit_code=return_code,
                last_good_paths=last_good_paths,
                deprecated=True,
            )

        staged_pdf = staging_dir / "agenda.pdf"
        staged_png = staging_dir / "agenda.png"
        if not has_complete_agenda_pair(staging_dir):
            return emit_finalize_failure(
                {"errors": ["agenda export reported success without a complete PDF and PNG pair"]},
                export_exit_code=2,
                last_good_paths=last_good_paths,
                deprecated=True,
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
                deprecated=True,
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
            "deprecated": True,
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

    first_parser = subparsers.add_parser(
        "first", help="build facts and immediately create the first A4 preview"
    )
    first_parser.add_argument("input_json", type=Path)
    first_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    first_parser.add_argument("--club-profile", type=str, default=None)
    first_parser.add_argument("--update-club-profile", action="store_true")
    first_parser.add_argument(
        "--confirm-overtime-minutes",
        type=positive_half_minute,
        default=None,
        metavar="N",
        help=(
            "second run only: pass the exact overrun after the user explicitly approves it"
        ),
    )
    first_parser.add_argument(
        "--view-patch",
        type=Path,
        default=None,
        help="merge a partial semantic view and remember it after success",
    )
    first_parser.add_argument(
        "--profile-root", type=Path, default=None, help=argparse.SUPPRESS
    )
    first_parser.set_defaults(handler=first)

    confirm_parser = subparsers.add_parser(
        "confirm", help="build a complete text agenda and wait for user confirmation"
    )
    confirm_parser.add_argument("input_json", type=Path)
    confirm_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    confirm_parser.add_argument("--club-profile", type=str, default=None)
    confirm_parser.add_argument("--update-club-profile", action="store_true")
    confirm_parser.add_argument(
        "--confirm-overtime-minutes",
        type=positive_half_minute,
        default=None,
        metavar="N",
    )
    confirm_parser.add_argument(
        "--profile-root", type=Path, default=None, help=argparse.SUPPRESS
    )
    confirm_parser.set_defaults(handler=confirm_text)

    image_parser = subparsers.add_parser(
        "image", help="render the exact text-confirmed facts as an A4 preview"
    )
    image_parser.add_argument("input_computed", type=Path)
    image_parser.add_argument("--confirmed-sha256", required=True)
    image_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    image_parser.add_argument("--view-patch", type=Path, default=None)
    image_parser.set_defaults(handler=image_from_confirmed)

    final_parser = subparsers.add_parser(
        "final", help="promote the already-rendered preview PDF and PNG"
    )
    final_parser.add_argument("input_html", type=Path)
    final_parser.add_argument("--output-dir", type=Path, default=Path("output"))
    final_parser.set_defaults(handler=finalize, v3_final=True)

    args = parser.parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
