#!/usr/bin/env python3
"""Convert the small agent-facing agenda schema into canonical meeting JSON.

This module deliberately handles only lossless shape changes and exact aliases.  It
does not calculate a timeline, choose visual settings, or infer a role/position from
context.  The existing agenda builder remains the authority for business validation
and time closure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping


SIMPLE_VERSION = 1

TOP_LEVEL_FIELDS = {
    "simple_version",
    "club",
    "meeting",
    "roles",
    "speeches",
    "impromptu",
    "backstage",
    "special",
    # Optional canonical content controls.  They stay out of the ordinary example,
    # but keeping them here lets a later natural-language correction survive the
    # simple-input conversion without exposing visual implementation details.
    "participant_pathways",
    "custom_support_blocks",
    "agenda_overrides",
    "transition_overrides",
}

CLUB_FIELDS = {
    "name",
    "default_location",
    "language",
    "support_components",
    "custom_support_blocks",
    "officers",
    "club_intro",
    "join_info",
    "vpm_qr_image",
}

MEETING_FIELDS = {
    "number",
    "date",
    "start",
    "end",
    "location",
    "theme",
    "word_of_day",
    "manager",
    "president",
    "approved_overtime_minutes",
    "support_components",
    "custom_support_blocks",
    "voting_qr_image",
}

PASSTHROUGH_TOP_LEVEL_FIELDS = {
    "participant_pathways",
    "custom_support_blocks",
    "agenda_overrides",
    "transition_overrides",
}


def _token(value: Any) -> str:
    """Normalize an exact human label without performing fuzzy matching."""

    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "president": (
        "president",
        "club president",
        "会长",
        "主席",
        "俱乐部会长",
    ),
    "rules_host": (
        "rules_host",
        "rules host",
        "meeting rules",
        "meeting rules host",
        "会议规则",
        "会议规则负责人",
        "规则介绍",
        "规则宣讲",
        "规则官",
    ),
    "toastmaster": (
        "toastmaster",
        "toastmaster of the day",
        "tmod",
        "meeting toastmaster",
        "总主持",
        "总主持人",
        "大会主持",
        "会议总主持",
    ),
    "timer": (
        "timer",
        "timekeeper",
        "time keeper",
        "时间官",
        "计时官",
        "计时员",
    ),
    "ah_counter": (
        "ah_counter",
        "ah counter",
        "ah-counter",
        "filler word counter",
        "哼哈官",
        "赘语官",
        "语气词记录员",
    ),
    "grammarian": (
        "grammarian",
        "语法官",
    ),
    "guest_host": (
        "guest_host",
        "guest host",
        "guest introducer",
        "guest introduction",
        "guest introduction host",
        "嘉宾介绍",
        "嘉宾介绍人",
        "嘉宾介绍负责人",
        "嘉宾主持",
    ),
    "sharing_host": (
        "sharing_host",
        "sharing host",
        "sharing",
        "sharing session host",
        "真情分享",
        "真情分享主持",
        "真情分享主持人",
        "分享主持",
        "分享环节负责人",
    ),
    "general_evaluator": (
        "general_evaluator",
        "general evaluator",
        "ge",
        "总点评",
        "总点评官",
        "总评官",
    ),
    "awards_host": (
        "awards_host",
        "awards host",
        "award host",
        "awards",
        "颁奖主持",
        "颁奖负责人",
        "颁奖",
    ),
}

AMBIGUOUS_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    _token("主持人"): (
        "toastmaster",
        "guest_host",
        "sharing_host",
        "awards_host",
    ),
    _token("主持"): (
        "toastmaster",
        "guest_host",
        "sharing_host",
        "awards_host",
    ),
    _token("host"): (
        "toastmaster",
        "guest_host",
        "sharing_host",
        "awards_host",
    ),
    _token("evaluator"): (
        "general_evaluator",
        "speeches[].evaluator",
        "impromptu.evaluator",
    ),
    _token("点评"): (
        "general_evaluator",
        "speeches[].evaluator",
        "impromptu.evaluator",
    ),
}


def _alias_index(groups: Mapping[str, Iterable[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for canonical, aliases in groups.items():
        for alias in aliases:
            token = _token(alias)
            previous = result.get(token)
            if previous is not None and previous != canonical:
                raise RuntimeError(
                    f"alias {alias!r} maps to both {previous!r} and {canonical!r}"
                )
            result[token] = canonical
    return result


ROLE_INDEX = _alias_index(ROLE_ALIASES)

BACKSTAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "photographer": (
        "photographer",
        "photography",
        "photo",
        "拍照官",
        "摄影官",
        "摄影",
        "拍照",
    ),
    "slides": (
        "slides",
        "slide operator",
        "ppt",
        "ppt operator",
        "场控/ppt",
        "场控",
        "幻灯片",
        "幻灯片播放",
    ),
    "voting": (
        "voting",
        "vote",
        "voting link",
        "投票",
        "投票官",
        "投票链接",
    ),
}
BACKSTAGE_INDEX = _alias_index(BACKSTAGE_ALIASES)

LANGUAGE_INDEX = {
    _token("zh"): "zh",
    _token("zh-cn"): "zh",
    _token("中文"): "zh",
    _token("Chinese"): "zh",
    _token("en"): "en",
    _token("English"): "en",
    _token("英文"): "en",
    _token("bilingual"): "bilingual",
    _token("中英双语"): "bilingual",
    _token("双语"): "bilingual",
    _token("Chinese and English"): "bilingual",
}

STATIC_ANCHOR_ALIASES: dict[str, tuple[str, ...]] = {
    "guest_introduction": (
        "guest_introduction",
        "guest introduction",
        "guest intro",
        "嘉宾介绍",
    ),
    "table_topics": (
        "table_topics",
        "table topics",
        "impromptu speech",
        "impromptu speaking",
        "即兴演讲",
        "即兴环节",
    ),
    "photo_break": (
        "photo_break",
        "group photo & break",
        "group photo and break",
        "group photo break",
        "photo break",
        "合影休息",
        "合影加休息",
        "合影与休息",
        "合影中场休息",
        "合影＋中场休息",
        "合影+中场休息",
    ),
    "table_topics_evaluation": (
        "table_topics_evaluation",
        "table topics evaluation",
        "impromptu evaluation",
        "即兴点评",
        "即兴演讲点评",
    ),
    "sharing": (
        "sharing",
        "sharing session",
        "true feelings sharing",
        "真情分享",
    ),
}
STATIC_ANCHOR_INDEX = _alias_index(STATIC_ANCHOR_ALIASES)

AMBIGUOUS_ANCHORS: dict[str, tuple[str, ...]] = {
    _token("备稿演讲"): ("备稿演讲1", "备稿演讲2", "..."),
    _token("prepared speech"): ("Prepared Speech 1", "Prepared Speech 2", "..."),
    _token("speech"): ("Prepared Speech 1", "Prepared Speech 2", "..."),
    _token("备稿点评"): ("备稿点评1", "备稿点评2", "..."),
    _token("speech evaluation"): ("Speech Evaluation 1", "Speech Evaluation 2", "..."),
    _token("prepared evaluation"): (
        "Prepared Evaluation 1",
        "Prepared Evaluation 2",
        "...",
    ),
    _token("点评"): (
        "备稿点评1",
        "即兴点评",
        "总点评不支持作为 special.after",
    ),
    _token("evaluation"): (
        "Speech Evaluation 1",
        "Table Topics Evaluation",
    ),
    _token("break"): ("Group Photo & Break",),
    _token("休息"): ("合影休息",),
}

UNRESOLVED_TEXT = {
    "",
    "?",
    "？",
    "待定",
    "待确认",
    "招募中",
    "tbd",
    "pending",
    "todo",
}

_MISSING = object()


class SimpleInputError(ValueError):
    """One or more simple-schema fields could not be converted safely."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = deepcopy(errors)
        super().__init__("; ".join(error["message"] for error in self.errors))

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "stage": "needs_input",
            "error_type": "simple_input",
            "errors": deepcopy(self.errors),
        }


def _add_error(
    errors: list[dict[str, Any]],
    *,
    code: str,
    path: str,
    message: str,
    value: Any = _MISSING,
    candidates: Iterable[str] | None = None,
) -> None:
    issue: dict[str, Any] = {"code": code, "path": path, "message": message}
    if value is not _MISSING:
        issue["value"] = deepcopy(value)
    if candidates is not None:
        issue["candidates"] = list(candidates)
    errors.append(issue)


def _is_unresolved(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return unicodedata.normalize("NFKC", value).strip().casefold() in UNRESOLVED_TEXT


def _read_object(
    value: Any,
    path: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    _add_error(
        errors,
        code="invalid_type",
        path=path,
        message=f"{path} must be an object",
        value=value,
    )
    return {}


def _check_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    path: str,
    errors: list[dict[str, Any]],
) -> None:
    for field in sorted(set(value) - allowed):
        child_path = f"{path}.{field}" if path else field
        _add_error(
            errors,
            code="unknown_field",
            path=child_path,
            message=f"{child_path} is not part of simple_version 1",
            value=value[field],
        )


def _required_text(
    value: Any,
    path: str,
    errors: list[dict[str, Any]],
) -> str:
    if _is_unresolved(value):
        _add_error(
            errors,
            code="missing_value",
            path=path,
            message=f"{path} needs a confirmed value",
            value=value,
        )
        return ""
    if not isinstance(value, str):
        _add_error(
            errors,
            code="invalid_type",
            path=path,
            message=f"{path} must be text",
            value=value,
        )
        return ""
    return value.strip()


def _validate_minutes(
    value: Any,
    path: str,
    errors: list[dict[str, Any]],
    *,
    required: bool = False,
) -> None:
    if value is _MISSING:
        if required:
            _add_error(
                errors,
                code="missing_value",
                path=path,
                message=f"{path} needs a confirmed duration",
            )
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _add_error(
            errors,
            code="invalid_minutes",
            path=path,
            message=f"{path} must be a positive number in 0.5-minute increments",
            value=value,
        )
        return
    number = float(value)
    if number <= 0 or abs(number * 2 - round(number * 2)) > 1e-9:
        _add_error(
            errors,
            code="invalid_minutes",
            path=path,
            message=f"{path} must be a positive number in 0.5-minute increments",
            value=value,
        )


def _copy_known_fields(
    source: Mapping[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    return {key: deepcopy(source[key]) for key in source if key in allowed}


def normalize_role(
    value: Any,
    *,
    path: str = "role",
    errors: list[dict[str, Any]] | None = None,
) -> str | None:
    local_errors = errors if errors is not None else []
    text = _required_text(value, path, local_errors)
    if not text:
        if errors is None:
            raise SimpleInputError(local_errors)
        return None
    token = _token(text)
    if token in AMBIGUOUS_ROLE_ALIASES:
        _add_error(
            local_errors,
            code="ambiguous_role",
            path=path,
            message=f"{path} is ambiguous; use one specific role name",
            value=value,
            candidates=AMBIGUOUS_ROLE_ALIASES[token],
        )
        result = None
    else:
        result = ROLE_INDEX.get(token)
        if result is None:
            _add_error(
                local_errors,
                code="unknown_role",
                path=path,
                message=f"{path} is not a supported meeting role",
                value=value,
                candidates=ROLE_ALIASES.keys(),
            )
    if errors is None and local_errors:
        raise SimpleInputError(local_errors)
    return result


def _strip_anchor_wrapper(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    text = re.sub(r"^after\s+", "", text, flags=re.IGNORECASE)
    if text.startswith("在"):
        text = text[1:].strip()
    text = re.sub(r"(?:之后|以后|后)$", "", text).strip()
    return text


def normalize_after(
    value: Any,
    *,
    path: str = "after",
    errors: list[dict[str, Any]] | None = None,
) -> str | None:
    local_errors = errors if errors is not None else []
    text = _required_text(value, path, local_errors)
    if not text:
        if errors is None:
            raise SimpleInputError(local_errors)
        return None
    phrase = _strip_anchor_wrapper(text)
    canonical_match = re.fullmatch(
        r"(prepared_speech|prepared_evaluation)\s*:\s*([1-9]\d*)",
        phrase.casefold(),
    )
    if canonical_match:
        return f"{canonical_match.group(1)}:{int(canonical_match.group(2))}"
    token = _token(phrase)
    static = STATIC_ANCHOR_INDEX.get(token)
    if static is not None:
        return static

    dynamic_patterns: tuple[tuple[str, str], ...] = (
        (r"(?:第)?([1-9]\d*)(?:个|场)?备稿演讲", "prepared_speech"),
        (r"备稿演讲(?:第)?([1-9]\d*)(?:个|场)?", "prepared_speech"),
        (r"preparedspeech(?:number|no)?([1-9]\d*)", "prepared_speech"),
        (r"speech(?:number|no)?([1-9]\d*)", "prepared_speech"),
        (r"(?:第)?([1-9]\d*)(?:个|场)?备稿点评", "prepared_evaluation"),
        (r"备稿点评(?:第)?([1-9]\d*)(?:个|场)?", "prepared_evaluation"),
        (r"speechevaluation(?:number|no)?([1-9]\d*)", "prepared_evaluation"),
        (r"prepared(?:speech)?evaluation(?:number|no)?([1-9]\d*)", "prepared_evaluation"),
    )
    for pattern, prefix in dynamic_patterns:
        match = re.fullmatch(pattern, token)
        if match:
            return f"{prefix}:{int(match.group(1))}"

    if token in AMBIGUOUS_ANCHORS:
        _add_error(
            local_errors,
            code="ambiguous_after",
            path=path,
            message=f"{path} is ambiguous; name the exact preceding agenda item",
            value=value,
            candidates=AMBIGUOUS_ANCHORS[token],
        )
    else:
        _add_error(
            local_errors,
            code="unknown_after",
            path=path,
            message=f"{path} is not a supported agenda position",
            value=value,
            candidates=(
                "嘉宾介绍 / Guest Introduction",
                "备稿演讲N / Prepared Speech N",
                "即兴演讲 / Table Topics",
                "合影休息 / Group Photo & Break",
                "备稿点评N / Speech Evaluation N",
                "即兴点评 / Table Topics Evaluation",
                "真情分享 / Sharing",
            ),
        )
    if errors is None:
        raise SimpleInputError(local_errors)
    return None


def _convert_roles(value: Any, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        _add_error(
            errors,
            code="invalid_type",
            path="roles",
            message="roles must be an array",
            value=value,
        )
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        path = f"roles[{index}]"
        row = _read_object(raw, path, errors)
        _check_fields(row, {"role", "person"}, path, errors)
        role_id = normalize_role(row.get("role"), path=f"{path}.role", errors=errors)
        person = _required_text(row.get("person"), f"{path}.person", errors)
        if role_id is None:
            continue
        if role_id in seen:
            _add_error(
                errors,
                code="duplicate_role",
                path=f"{path}.role",
                message=f"{role_id} appears more than once in roles",
                value=row.get("role"),
            )
            continue
        seen.add(role_id)
        result.append({"id": role_id, "person": person})
    return result


SPEECH_FIELDS = {
    "speaker",
    "title",
    "project",
    "minutes",
    "evaluator",
    "evaluation_minutes",
    "evaluation_enabled",
}


def _convert_speeches(value: Any, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        _add_error(
            errors,
            code="invalid_type",
            path="speeches",
            message="speeches must be an array",
            value=value,
        )
        return []
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        path = f"speeches[{index}]"
        row = _read_object(raw, path, errors)
        _check_fields(row, SPEECH_FIELDS, path, errors)
        converted = _copy_known_fields(row, SPEECH_FIELDS)
        converted["speaker"] = _required_text(
            row.get("speaker"), f"{path}.speaker", errors
        )
        _validate_minutes(row.get("minutes", _MISSING), f"{path}.minutes", errors)
        _validate_minutes(
            row.get("evaluation_minutes", _MISSING),
            f"{path}.evaluation_minutes",
            errors,
        )
        evaluation_enabled = row.get("evaluation_enabled", True)
        if not isinstance(evaluation_enabled, bool):
            _add_error(
                errors,
                code="invalid_type",
                path=f"{path}.evaluation_enabled",
                message=f"{path}.evaluation_enabled must be true or false",
                value=evaluation_enabled,
            )
        elif evaluation_enabled:
            converted["evaluator"] = _required_text(
                row.get("evaluator"), f"{path}.evaluator", errors
            )
        else:
            if "evaluator" in row and not _is_unresolved(row.get("evaluator")):
                _add_error(
                    errors,
                    code="conflicting_fields",
                    path=f"{path}.evaluator",
                    message=(
                        f"{path}.evaluator must be omitted when evaluation_enabled is false"
                    ),
                    value=row.get("evaluator"),
                )
            if "evaluation_minutes" in row:
                _add_error(
                    errors,
                    code="conflicting_fields",
                    path=f"{path}.evaluation_minutes",
                    message=(
                        f"{path}.evaluation_minutes must be omitted when "
                        "evaluation_enabled is false"
                    ),
                    value=row.get("evaluation_minutes"),
                )
            converted.pop("evaluator", None)
            converted.pop("evaluation_minutes", None)
        result.append(converted)
    return result


IMPROMPTU_FIELDS = {"host", "minutes", "evaluator", "evaluation_minutes", "details"}


def _convert_impromptu(value: Any, errors: list[dict[str, Any]]) -> dict[str, Any] | None:
    if value is None:
        return None
    row = _read_object(value, "impromptu", errors)
    _check_fields(row, IMPROMPTU_FIELDS, "impromptu", errors)
    converted = _copy_known_fields(row, IMPROMPTU_FIELDS)
    converted["host"] = _required_text(row.get("host"), "impromptu.host", errors)
    _validate_minutes(row.get("minutes", _MISSING), "impromptu.minutes", errors)
    if "evaluator" in row:
        converted["evaluator"] = _required_text(
            row.get("evaluator"), "impromptu.evaluator", errors
        )
    elif "evaluation_minutes" in row:
        _add_error(
            errors,
            code="conflicting_fields",
            path="impromptu.evaluation_minutes",
            message="impromptu.evaluation_minutes needs impromptu.evaluator",
            value=row.get("evaluation_minutes"),
        )
    _validate_minutes(
        row.get("evaluation_minutes", _MISSING),
        "impromptu.evaluation_minutes",
        errors,
    )
    return converted


def _convert_backstage(value: Any, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        _add_error(
            errors,
            code="invalid_type",
            path="backstage",
            message="backstage must be an array",
            value=value,
        )
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        path = f"backstage[{index}]"
        row = _read_object(raw, path, errors)
        _check_fields(row, {"role", "person", "label"}, path, errors)
        role = _required_text(row.get("role"), f"{path}.role", errors)
        person = _required_text(row.get("person"), f"{path}.person", errors)
        role_id = BACKSTAGE_INDEX.get(_token(role), role)
        if role_id in seen:
            _add_error(
                errors,
                code="duplicate_role",
                path=f"{path}.role",
                message=f"{role_id} appears more than once in backstage",
                value=row.get("role"),
            )
            continue
        seen.add(role_id)
        label = row.get("label", role)
        label_text = _required_text(label, f"{path}.label", errors)
        result.append({"id": role_id, "person": person, "label": label_text})
    return result


SPECIAL_FIELDS = {"title", "owner", "minutes", "after", "details"}


def _convert_special(value: Any, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        _add_error(
            errors,
            code="invalid_type",
            path="special",
            message="special must be an array",
            value=value,
        )
        return []
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        path = f"special[{index}]"
        row = _read_object(raw, path, errors)
        _check_fields(row, SPECIAL_FIELDS, path, errors)
        converted = _copy_known_fields(row, SPECIAL_FIELDS)
        converted["title"] = _required_text(row.get("title"), f"{path}.title", errors)
        converted["owner"] = _required_text(row.get("owner"), f"{path}.owner", errors)
        _validate_minutes(
            row.get("minutes", _MISSING), f"{path}.minutes", errors, required=True
        )
        anchor = normalize_after(row.get("after"), path=f"{path}.after", errors=errors)
        if anchor is not None:
            converted["after"] = anchor
        result.append(converted)
    return result


def is_simple_input(data: Any) -> bool:
    return isinstance(data, dict) and "simple_version" in data


def convert_simple_input(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical meeting JSON or raise :class:`SimpleInputError`.

    Every conversion is deterministic.  Errors are accumulated so an agent can ask
    all necessary questions once instead of discovering them one at a time.
    """

    errors: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        _add_error(
            errors,
            code="invalid_type",
            path="$",
            message="simple input must be a JSON object",
            value=data,
        )
        raise SimpleInputError(errors)

    _check_fields(data, TOP_LEVEL_FIELDS, "", errors)
    version = data.get("simple_version")
    if isinstance(version, bool) or version != SIMPLE_VERSION:
        _add_error(
            errors,
            code="invalid_simple_version",
            path="simple_version",
            message=f"simple_version must be {SIMPLE_VERSION}",
            value=version,
        )

    club = _read_object(data.get("club", {}), "club", errors)
    meeting = _read_object(data.get("meeting", {}), "meeting", errors)
    _check_fields(club, CLUB_FIELDS, "club", errors)
    _check_fields(meeting, MEETING_FIELDS, "meeting", errors)

    canonical_club = _copy_known_fields(club, CLUB_FIELDS)
    if "language" in canonical_club:
        raw_language = canonical_club["language"]
        normalized_language = LANGUAGE_INDEX.get(_token(raw_language))
        if normalized_language is None:
            _add_error(
                errors,
                code="unknown_language",
                path="club.language",
                message="club.language must be Chinese, English, or bilingual",
                value=raw_language,
                candidates=("zh / 中文", "en / English", "bilingual / 中英双语"),
            )
        else:
            canonical_club["language"] = normalized_language

    canonical: dict[str, Any] = {
        "club": canonical_club,
        "meeting": _copy_known_fields(meeting, MEETING_FIELDS),
        "roles": _convert_roles(data.get("roles", []), errors),
        "prepared_speeches": _convert_speeches(data.get("speeches", []), errors),
        "impromptu": _convert_impromptu(data.get("impromptu"), errors),
        "backstage": _convert_backstage(data.get("backstage", []), errors),
        "special_segments": _convert_special(data.get("special", []), errors),
    }
    for field in PASSTHROUGH_TOP_LEVEL_FIELDS:
        if field in data:
            canonical[field] = deepcopy(data[field])

    if errors:
        raise SimpleInputError(errors)
    return canonical


# The shorter name reads naturally from an orchestration script.  Keep one
# implementation so the two names cannot drift.
normalize_simple_input = convert_simple_input


def _write_json(payload: Any, destination: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if destination is None:
        sys.stdout.write(text)
    else:
        destination.expanduser().resolve().write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert simple_version 1 agenda input to canonical meeting JSON."
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input_json.expanduser().resolve().read_text(encoding="utf-8"))
        canonical = convert_simple_input(data)
        _write_json(canonical, args.output)
    except SimpleInputError as exc:
        sys.stderr.write(json.dumps(exc.to_payload(), ensure_ascii=False) + "\n")
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        payload = {
            "ok": False,
            "stage": "needs_input",
            "error_type": "simple_input",
            "errors": [
                {
                    "code": "input_read_error",
                    "path": str(args.input_json),
                    "message": str(exc),
                }
            ],
        }
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
