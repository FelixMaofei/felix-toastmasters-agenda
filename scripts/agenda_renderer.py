#!/usr/bin/env python3
"""V3 deterministic A4 renderer.

The renderer consumes two already-decided data objects:

* agenda.computed.json: the single source of meeting facts.
* agenda.view.json: a small semantic view contract.

It never chooses a meeting template, recalculates the agenda, or rewrites facts.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any


class AgendaRenderError(ValueError):
    """Raised when computed facts or the V3 view contract cannot be rendered."""


VIEW_KEYS = {
    "view_version",
    "content_emphasis",
    "display_columns",
    "component_flow",
    "density",
    "design",
}
REQUIRED_COLUMNS = ("time", "activity", "owner", "duration")
CORE_COLUMN_ORDER = {"time": 0, "activity": 1, "owner": 2, "duration": 10_000}
VALID_DENSITIES = {"comfortable", "balanced", "compact"}
VALID_TEXT_SCALES = {"standard", "large"}
VALID_CONTRASTS = {"soft", "clear"}
VALID_EMPHASIS = {"subtle", "clear"}
VALID_GROUPS = {"operations", "background"}
MAX_AUXILIARY_COLUMNS = 3
SAFE_COLUMN_RE = re.compile(r"^[a-z][a-z0-9_]*$")
FORBIDDEN_VIEW_KEYS = {
    "layout",
    "standard",
    "feature",
    "marathon",
    "template",
    "renderer",
    "mode",
    "visual_theme",
    "left",
    "right",
    "bottom",
    "sidebar",
    "grid_area",
    "x",
    "y",
    "width",
    "height",
    "column_width",
    "row_height",
    "ratio",
    "area",
    "margin",
    "padding",
    "px",
    "html",
    "css",
    "class",
    "style",
    "font",
    "color",
    "border",
    "gradient",
    "grow",
    "weight",
    "duration_ratio",
    "fill_height",
    "visible",
    "hidden",
    "max_lines",
    "truncate",
    "overflow",
    "zoom",
    "scale",
    "fit_to_page",
    "design_prompt",
    "notes",
}
KNOWN_GROUPS = {
    "backstage": "operations",
    "timer_rules": "operations",
    "officers": "operations",
    "toastmasters_intro": "background",
    "meeting_boundaries": "background",
    "club_intro": "background",
    "join_info": "background",
    "vpm_qr": "background",
    "voting_qr": "operations",
}
SECTION_LABELS = {
    "opening": ("开场", "Opening"),
    "first_half": ("上半场", "First Half"),
    "second_half": ("下半场", "Second Half"),
    "closing": ("收尾", "Closing"),
}
COLUMN_LABELS = {
    "time": ("时间", "Time"),
    "activity": ("会议流程", "Meeting Flow"),
    "owner": ("负责人", "Owner"),
    "pathways": ("Pathways", "Pathways"),
    "project": ("教育项目", "Project"),
    "duration": ("时长", "Duration"),
}
FONT_IMPORT_RE = re.compile(
    r"""@import\s+url\((?:"|')?\./fonts/noto-sans-sc/index\.css(?:"|')?\);\s*"""
)
FONT_URL_RE = re.compile(r"""url\((?:"|')?(\./files/[^)"']+)(?:"|')?\)""")
DATA_IMAGE_RE = re.compile(
    r"^data:image/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=\s]+$",
    re.IGNORECASE,
)


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _require_mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AgendaRenderError(f"{path} must be an object")
    return value


def _require_list(value: object, path: str) -> Sequence[Any]:
    if not _is_sequence(value):
        raise AgendaRenderError(f"{path} must be an array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    path: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise AgendaRenderError(f"{path} is missing: {', '.join(missing)}")
    if unknown:
        raise AgendaRenderError(f"{path} contains unsupported fields: {', '.join(unknown)}")


def _reject_forbidden_keys(value: object, path: str = "agenda.view.json") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_VIEW_KEYS:
                raise AgendaRenderError(
                    f"{path}.{key_text} is forbidden in the V3 semantic view contract"
                )
            _reject_forbidden_keys(child, f"{path}.{key_text}")
    elif _is_sequence(value):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _timeline(computed: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    raw_timeline = _require_list(computed.get("timeline"), "agenda.computed.timeline")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw_timeline):
        result.append(
            _require_mapping(item, f"agenda.computed.timeline[{index}]")
        )
    return result


def _nonempty_text(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if _is_sequence(value):
        return any(_nonempty_text(item) for item in value)
    return bool(str(value).strip())


def _item_column_value(item: Mapping[str, Any], column: str) -> object:
    if column == "time":
        return item.get("start", "")
    if column == "activity":
        return item.get("label", "")
    if column == "owner":
        return item.get("owner", "")
    if column == "duration":
        return item.get("duration", "")
    if column == "pathways":
        return item.get("pathways", "")
    return item.get(column, "")


def _normalize_component_id(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgendaRenderError(f"{path} must be a non-empty string")
    return value.strip()


def _block_group(block: Mapping[str, Any]) -> str | None:
    group = block.get("group")
    if group is None and block.get("kind") in VALID_GROUPS:
        group = block.get("kind")
    if group is None:
        return None
    group_text = str(group).strip()
    if group_text not in VALID_GROUPS:
        raise AgendaRenderError(
            f"support block {block.get('id', '<unknown>')!r} has unsupported group {group_text!r}"
        )
    return group_text


def _legacy_block(
    component_id: str,
    computed: Mapping[str, Any],
) -> dict[str, Any]:
    club = _require_mapping(computed.get("club", {}), "agenda.computed.club")
    language = str(club.get("language", "zh"))
    if component_id == "officers":
        return {
            "id": component_id,
            "group": "operations",
            "kind": "pairs",
            "title": _localize("当届官员团队", "Officer Team", language),
            "entries": [
                {"label": row.get("role", ""), "value": row.get("name", "")}
                for row in _require_list(club.get("officers", []), "club.officers")
                if isinstance(row, Mapping)
            ],
        }
    if component_id in {"club_intro", "join_info"}:
        key = component_id
        title = (
            _localize("俱乐部介绍", "About the Club", language)
            if component_id == "club_intro"
            else _localize("如何入会", "How to Join", language)
        )
        raw_lines = club.get(key, [])
        lines = list(raw_lines) if _is_sequence(raw_lines) else [raw_lines]
        return {
            "id": component_id,
            "group": "background",
            "kind": "prose",
            "title": title,
            "lines": lines,
        }
    return {
        "id": component_id,
        "group": KNOWN_GROUPS.get(component_id),
        "kind": "unmaterialized",
        "title": component_id,
    }


def _collect_support_blocks(
    computed: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    blocks: dict[str, dict[str, Any]] = {}

    def add(block: Mapping[str, Any], path: str) -> None:
        block_id = _normalize_component_id(block.get("id"), f"{path}.id")
        if block_id in blocks:
            raise AgendaRenderError(f"duplicate support block id: {block_id}")
        blocks[block_id] = dict(block)

    raw_blocks = computed.get("support_blocks")
    if raw_blocks is not None:
        for index, block in enumerate(
            _require_list(raw_blocks, "agenda.computed.support_blocks")
        ):
            add(
                _require_mapping(
                    block, f"agenda.computed.support_blocks[{index}]"
                ),
                f"agenda.computed.support_blocks[{index}]",
            )

    selected = computed.get("support_components", [])
    for index, value in enumerate(
        _require_list(selected, "agenda.computed.support_components")
    ):
        component_id = _normalize_component_id(
            value, f"agenda.computed.support_components[{index}]"
        )
        if component_id not in blocks:
            add(_legacy_block(component_id, computed), "legacy support component")

    for index, block in enumerate(
        _require_list(
            computed.get("custom_support_blocks", []),
            "agenda.computed.custom_support_blocks",
        )
    ):
        legacy = _require_mapping(
            block, f"agenda.computed.custom_support_blocks[{index}]"
        )
        block_id = _normalize_component_id(
            legacy.get("id"), f"agenda.computed.custom_support_blocks[{index}].id"
        )
        if block_id not in blocks:
            normalized = dict(legacy)
            normalized.setdefault("kind", "prose")
            normalized.setdefault("lines", legacy.get("lines", []))
            add(normalized, f"agenda.computed.custom_support_blocks[{index}]")

    backstage = _require_list(
        computed.get("backstage", []), "agenda.computed.backstage"
    )
    if backstage and "backstage" not in blocks:
        club = _require_mapping(computed.get("club", {}), "agenda.computed.club")
        language = str(club.get("language", "zh"))
        entries: list[dict[str, object]] = []
        for index, row in enumerate(backstage):
            item = _require_mapping(
                row, f"agenda.computed.backstage[{index}]"
            )
            entries.append(
                {
                    "label": item.get("label", item.get("role", "")),
                    "value": item.get("person", item.get("name", "")),
                }
            )
        add(
            {
                "id": "backstage",
                "group": "operations",
                "kind": "pairs",
                "title": _localize("幕后团队", "Backstage Team", language),
                "entries": entries,
            },
            "agenda.computed.backstage",
        )
    return blocks


def validate_view(
    computed: Mapping[str, Any],
    view: Mapping[str, Any],
) -> None:
    """Validate the minimal V3 view contract against computed facts."""

    computed = _require_mapping(computed, "agenda.computed.json")
    view = _require_mapping(view, "agenda.view.json")
    _reject_forbidden_keys(view)
    _exact_keys(view, VIEW_KEYS, "agenda.view.json")

    version = view["view_version"]
    if isinstance(version, bool) or version != 1:
        raise AgendaRenderError("agenda.view.json.view_version must be 1")

    timeline = _timeline(computed)
    item_ids: list[str] = []
    for index, item in enumerate(timeline):
        item_id = _normalize_component_id(
            item.get("id"), f"agenda.computed.timeline[{index}].id"
        )
        if item_id in item_ids:
            raise AgendaRenderError(f"duplicate timeline item id: {item_id}")
        item_ids.append(item_id)

    emphasis = view["content_emphasis"]
    if emphasis is not None:
        emphasis_map = _require_mapping(
            emphasis, "agenda.view.json.content_emphasis"
        )
        _exact_keys(
            emphasis_map,
            {"item_id", "strength"},
            "agenda.view.json.content_emphasis",
        )
        item_id = _normalize_component_id(
            emphasis_map["item_id"],
            "agenda.view.json.content_emphasis.item_id",
        )
        if item_id not in item_ids:
            raise AgendaRenderError(
                f"content_emphasis item_id does not exist in timeline: {item_id}"
            )
        if emphasis_map["strength"] not in VALID_EMPHASIS:
            raise AgendaRenderError(
                "content_emphasis.strength must be subtle or clear"
            )

    raw_columns = _require_list(
        view["display_columns"], "agenda.view.json.display_columns"
    )
    columns: list[str] = []
    for index, value in enumerate(raw_columns):
        if not isinstance(value, str) or not SAFE_COLUMN_RE.fullmatch(value):
            raise AgendaRenderError(
                f"agenda.view.json.display_columns[{index}] must be a safe field name"
            )
        if value in columns:
            raise AgendaRenderError(f"duplicate display column: {value}")
        columns.append(value)
    if len(columns) < 4:
        raise AgendaRenderError("display_columns must include the four required columns")
    if tuple(columns[:3]) != REQUIRED_COLUMNS[:3] or columns[-1] != "duration":
        raise AgendaRenderError(
            "display_columns order must be time, activity, owner, optional columns, duration"
        )
    if any(column not in columns for column in REQUIRED_COLUMNS):
        raise AgendaRenderError(
            "display_columns must include time, activity, owner, and duration"
        )
    auxiliary_columns = columns[3:-1]
    if len(auxiliary_columns) > MAX_AUXILIARY_COLUMNS:
        raise AgendaRenderError(
            f"display_columns supports at most {MAX_AUXILIARY_COLUMNS} auxiliary columns"
        )
    for column in auxiliary_columns:
        if column in CORE_COLUMN_ORDER:
            raise AgendaRenderError(f"{column} cannot be used as an auxiliary column")
        if not any(_nonempty_text(_item_column_value(item, column)) for item in timeline):
            raise AgendaRenderError(
                f"display column {column!r} has no real data in the timeline"
            )

    flow = _require_mapping(
        view["component_flow"], "agenda.view.json.component_flow"
    )
    _exact_keys(flow, VALID_GROUPS, "agenda.view.json.component_flow")
    blocks = _collect_support_blocks(computed)
    ordered_ids: list[str] = []
    group_by_id: dict[str, str] = {}
    for group in ("operations", "background"):
        raw_ids = _require_list(
            flow[group], f"agenda.view.json.component_flow.{group}"
        )
        for index, value in enumerate(raw_ids):
            component_id = _normalize_component_id(
                value,
                f"agenda.view.json.component_flow.{group}[{index}]",
            )
            if component_id in group_by_id:
                raise AgendaRenderError(
                    f"component {component_id!r} appears more than once"
                )
            ordered_ids.append(component_id)
            group_by_id[component_id] = group
    available = set(blocks)
    selected_ids = set(ordered_ids)
    if selected_ids != available:
        missing = sorted(available - selected_ids)
        unknown = sorted(selected_ids - available)
        parts = []
        if missing:
            parts.append(f"missing components: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown components: {', '.join(unknown)}")
        raise AgendaRenderError("; ".join(parts))
    for component_id, selected_group in group_by_id.items():
        block_group = _block_group(blocks[component_id])
        expected_group = block_group or KNOWN_GROUPS.get(component_id)
        if expected_group and expected_group != selected_group:
            raise AgendaRenderError(
                f"component {component_id!r} belongs in {expected_group}, not {selected_group}"
            )

    if view["density"] not in VALID_DENSITIES:
        raise AgendaRenderError(
            "density must be comfortable, balanced, or compact"
        )
    design = _require_mapping(view["design"], "agenda.view.json.design")
    _exact_keys(design, {"text_scale", "contrast"}, "agenda.view.json.design")
    if design["text_scale"] not in VALID_TEXT_SCALES:
        raise AgendaRenderError("design.text_scale must be standard or large")
    if design["contrast"] not in VALID_CONTRASTS:
        raise AgendaRenderError("design.contrast must be soft or clear")


def _localize(zh: str, en: str, language: str) -> str:
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def _section_label(section: object, language: str) -> str:
    section_text = str(section or "").strip()
    labels = SECTION_LABELS.get(section_text)
    if labels is None:
        return section_text
    return _localize(labels[0], labels[1], language)


def _format_minutes(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:g}"
    return str(value).strip()


def _display_value(value: object) -> str:
    if value is None:
        return ""
    if _is_sequence(value):
        return " / ".join(str(item) for item in value if _nonempty_text(item))
    if isinstance(value, Mapping):
        raise AgendaRenderError("timeline display values must not be objects")
    return str(value).strip()


def _column_label(
    column: str,
    language: str,
    computed: Mapping[str, Any],
) -> str:
    raw_labels = computed.get("column_labels", {})
    if isinstance(raw_labels, Mapping) and _nonempty_text(raw_labels.get(column)):
        return _display_value(raw_labels[column])
    if column in COLUMN_LABELS:
        zh, en = COLUMN_LABELS[column]
        return _localize(zh, en, language)
    return column.replace("_", " ").title()


def _contiguous_stage_ranges(
    timeline: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[str, str]]:
    """Return a range only for the first item of each contiguous section run."""

    ranges: dict[int, tuple[str, str]] = {}
    index = 0
    while index < len(timeline):
        section = str(timeline[index].get("section", "")).strip()
        run_end = index
        while run_end + 1 < len(timeline):
            next_section = str(timeline[run_end + 1].get("section", "")).strip()
            if next_section != section:
                break
            run_end += 1
        ranges[index] = (
            str(timeline[index].get("start", "")).strip(),
            str(timeline[run_end].get("end", "")).strip(),
        )
        index = run_end + 1
    return ranges


def _render_timeline(
    computed: Mapping[str, Any],
    view: Mapping[str, Any],
    language: str,
) -> str:
    timeline = _timeline(computed)
    columns = list(view["display_columns"])
    auxiliary = columns[3:-1]
    emphasis = view["content_emphasis"]
    emphasis_id = str(emphasis["item_id"]) if emphasis else None
    emphasis_strength = str(emphasis["strength"]) if emphasis else ""
    headers = "".join(
        f'<span class="column-{_e(column)}">{_e(_column_label(column, language, computed))}</span>'
        for column in columns
    )
    stage_ranges = _contiguous_stage_ranges(timeline)
    parts = [f'<div class="column-head">{headers}</div>']
    last_section: str | None = None
    for item_index, item in enumerate(timeline):
        section = str(item.get("section", "")).strip()
        if section != last_section:
            start, end = stage_ranges[item_index]
            parts.append(
                '<div class="stage-row"><div class="stage-label">'
                f"<span>{_e(_section_label(section, language))}</span>"
                f"<small>{_e(start)}-{_e(end)}</small>"
                "</div></div>"
            )
            last_section = section

        item_id = str(item.get("id", "")).strip()
        classes = ["agenda-row", f"type-{_safe_class(item.get('type', 'item'))}"]
        if item_id == emphasis_id:
            classes.extend(["feature", f"feature-{emphasis_strength}"])
        if str(item.get("type", "")) == "photo_break":
            classes.append("break-row")

        cells: list[str] = []
        details = item.get("details", [])
        detail_text = (
            " · ".join(_display_value(value) for value in details)
            if _is_sequence(details)
            else _display_value(details)
        )
        for column in columns:
            value = _item_column_value(item, column)
            text = _display_value(value)
            class_name = {
                "time": "time",
                "activity": "event",
                "owner": "owner",
                "duration": "duration",
            }.get(column, f"aux-column column-{_safe_class(column)}")
            if column == "duration" and text:
                text = f"{_format_minutes(value)} min"
            detail_html = (
                f'<span class="detail">{_e(detail_text)}</span>'
                if column == "activity" and detail_text
                else ""
            )
            cells.append(
                f'<div class="{class_name}" data-column="{_e(column)}">'
                f"{_e(text)}{detail_html}</div>"
            )
        parts.append(
            f'<div class="{" ".join(classes)}" data-item-id="{_e(item_id)}">'
            + "".join(cells)
            + "</div>"
        )
    return (
        f'<div class="agenda-grid aux-count-{len(auxiliary)}">'
        + "".join(parts)
        + "</div>"
    )


def _safe_class(value: object) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", str(value).lower()).strip("-")
    return text or "item"


def _block_payload(block: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    content = block.get("content")
    if content is not None:
        payload.update(_require_mapping(content, f"support block {block.get('id')}.content"))
    for key, value in block.items():
        if key not in {"id", "group", "kind", "type", "title", "content"}:
            payload[key] = value
    return payload


def _block_kind(block: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    raw_kind = block.get("kind")
    if raw_kind in VALID_GROUPS:
        raw_kind = block.get("type")
    if not raw_kind:
        raw_kind = block.get("type")
    if raw_kind:
        return str(raw_kind).strip()
    if payload.get("data_uri"):
        return "image"
    if payload.get("entries") is not None or payload.get("rows") is not None:
        return "pairs"
    if payload.get("lines") is not None:
        return "prose"
    return ""


def _entry_parts(entry: object, path: str) -> tuple[str, str, str]:
    tone = ""
    if isinstance(entry, Mapping):
        label = entry.get(
            "label",
            entry.get("role", entry.get("key", entry.get("band", ""))),
        )
        value = entry.get(
            "value",
            entry.get(
                "name",
                entry.get(
                    "person",
                    entry.get("text", entry.get("description", "")),
                ),
            ),
        )
        tone = str(entry.get("tone", entry.get("color", ""))).strip()
    elif _is_sequence(entry) and len(entry) == 2:
        label, value = entry
    else:
        raise AgendaRenderError(f"{path} must be an object or [label, value]")
    if not _nonempty_text(label) and not _nonempty_text(value):
        raise AgendaRenderError(f"{path} cannot be empty")
    return _display_value(label), _display_value(value), tone


def _render_pairs(
    entries: Sequence[Any],
    *,
    officers: bool,
    path: str,
) -> str:
    parts = [f'<dl class="pair-list{" officers" if officers else ""}">']
    for index, entry in enumerate(entries):
        label, value, _tone = _entry_parts(entry, f"{path}[{index}]")
        parts.append(f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>")
    parts.append("</dl>")
    return "".join(parts)


def _render_timing(entries: Sequence[Any], path: str) -> str:
    parts = ['<div class="timing-scale">']
    fallback_tones = ("green", "amber", "red")
    for index, entry in enumerate(entries):
        label, value, tone = _entry_parts(entry, f"{path}[{index}]")
        display_label = _compact_timing_label(label)
        safe_tone = tone if tone in fallback_tones else fallback_tones[min(index, 2)]
        parts.append(
            '<div class="timing-rule">'
            f'<strong title="{_e(label)}"><i class="color-dot {safe_tone}"></i>{_e(display_label)}</strong>'
            f"<span>{_e(value)}</span></div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _compact_timing_label(label: str) -> str:
    compact = re.sub(r"\s+", "", label).lower()
    aliases = {
        "3分钟及以下": "≤3分",
        "3分钟以下": "≤3分",
        "超过3分钟至10分钟": "3-10分",
        "3分钟至10分钟": "3-10分",
        "10分钟以上": "≥10分",
        "3minutesorless": "≤3m",
        "upto3minutes": "≤3m",
        "over3to10minutes": "3-10m",
        "3to10minutes": "3-10m",
        "10minutesormore": "≥10m",
    }
    return aliases.get(compact, label)


def _line_values(value: object, path: str) -> list[str]:
    values = _require_list(value, path)
    lines: list[str] = []
    for index, item in enumerate(values):
        if isinstance(item, Mapping):
            item = item.get("text", "")
        if isinstance(item, Mapping) or _is_sequence(item):
            raise AgendaRenderError(f"{path}[{index}] must be text")
        line = _display_value(item)
        if line:
            lines.append(line)
    return lines


def _render_prose_line(line: str) -> str:
    for prefix in ("定位：", "愿景：", "Positioning:", "Vision:"):
        if line.startswith(prefix):
            return f"<p><strong>{_e(prefix)}</strong>{_e(line[len(prefix):])}</p>"
    return f"<p>{_e(line)}</p>"


def _render_support_body(block: Mapping[str, Any]) -> str:
    block_id = str(block["id"])
    payload = _block_payload(block)
    kind = _block_kind(block, payload)
    if kind == "unmaterialized":
        raise AgendaRenderError(
            f"support block {block_id!r} has no materialized content in agenda.computed.json"
        )
    if kind in {"pairs", "people", "table"}:
        entries = payload.get("entries", payload.get("rows", []))
        return _render_pairs(
            _require_list(entries, f"support block {block_id}.entries"),
            officers=block_id == "officers",
            path=f"support block {block_id}.entries",
        )
    if kind == "timing":
        entries = payload.get("entries", payload.get("rows", []))
        return _render_timing(
            _require_list(entries, f"support block {block_id}.entries"),
            f"support block {block_id}.entries",
        )
    if kind in {"bullets", "list"}:
        lines = _line_values(
            payload.get("lines", []), f"support block {block_id}.lines"
        )
        return "<ul>" + "".join(f"<li>{_e(line)}</li>" for line in lines) + "</ul>"
    if kind in {"prose", "text", "custom"}:
        lines = _line_values(
            payload.get("lines", []), f"support block {block_id}.lines"
        )
        return "".join(_render_prose_line(line) for line in lines)
    if kind in {"image", "qr"}:
        data_uri = str(payload.get("data_uri", "")).strip()
        if not DATA_IMAGE_RE.fullmatch(data_uri):
            raise AgendaRenderError(
                f"support block {block_id!r} must contain an inline PNG, JPEG, or WebP data_uri"
            )
        alt = _display_value(payload.get("alt", block.get("title", "")))
        caption = _display_value(payload.get("caption", ""))
        caption_html = f"<figcaption>{_e(caption)}</figcaption>" if caption else ""
        return (
            '<figure class="support-image">'
            f'<img src="{_e(data_uri)}" alt="{_e(alt)}">{caption_html}</figure>'
        )
    raise AgendaRenderError(
        f"support block {block_id!r} has unsupported kind {kind!r}"
    )


def _span_plan(group: str, component_ids: Sequence[str]) -> list[int]:
    count = len(component_ids)
    if count <= 0:
        return []
    if count == 1:
        return [4]
    if count == 2:
        return [2, 2]
    if count == 3:
        return [1, 1, 2] if group == "operations" else [2, 2, 4]
    if count == 4:
        return [1, 1, 1, 1] if group == "operations" else [2, 2, 2, 2]
    if group == "operations":
        if count % 2:
            return [1, 1, 2] + [2] * (count - 3)
        return [2] * count
    if count % 2:
        return [2] * (count - 1) + [4]
    return [2] * count


def _render_support_groups(
    computed: Mapping[str, Any],
    view: Mapping[str, Any],
) -> str:
    blocks = _collect_support_blocks(computed)
    flow = view["component_flow"]
    groups: list[str] = []
    for group in ("operations", "background"):
        ids = list(flow[group])
        if not ids:
            continue
        spans = _span_plan(group, ids)
        cards: list[str] = []
        for block_id, span in zip(ids, spans):
            block = blocks[block_id]
            title = _display_value(block.get("title", ""))
            if not title:
                raise AgendaRenderError(
                    f"support block {block_id!r} must have a title"
                )
            body = _render_support_body(block)
            classes = [
                "support-card",
                f"span-{span}",
                f"component-{_safe_class(block_id)}",
            ]
            if block_id == "club_intro":
                classes.append("club-intro")
            cards.append(
                f'<section class="{" ".join(classes)}" data-component-id="{_e(block_id)}">'
                f"<h3>{_e(title)}</h3>{body}</section>"
            )
        groups.append(
            f'<div class="support-group support-{group}" data-support-group="{group}">'
            + "".join(cards)
            + "</div>"
        )
    if not groups:
        return ""
    return (
        '<section class="support-area" aria-label="Supporting meeting information">'
        '<div class="support-grid">'
        + "".join(groups)
        + "</div></section>"
    )


def _data_uri(path: Path, mime: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@lru_cache(maxsize=8)
def _bundled_assets(skill_dir_text: str) -> tuple[str, str]:
    skill_dir = Path(skill_dir_text)
    css_path = skill_dir / "assets" / "agenda.css"
    font_css_path = skill_dir / "assets" / "fonts" / "noto-sans-sc" / "index.css"
    logo_path = skill_dir / "assets" / "toastmasters-logo.png"
    for path in (css_path, font_css_path, logo_path):
        if not path.is_file():
            raise AgendaRenderError(f"required packaged asset is missing: {path.name}")

    css = css_path.read_text(encoding="utf-8")
    css = FONT_IMPORT_RE.sub("", css)
    font_css = font_css_path.read_text(encoding="utf-8")
    font_root = font_css_path.parent.resolve()

    def inline_font(match: re.Match[str]) -> str:
        relative = match.group(1)
        font_path = (font_css_path.parent / relative).resolve()
        try:
            font_path.relative_to(font_root)
        except ValueError as exc:
            raise AgendaRenderError("font CSS references an asset outside the package") from exc
        if not font_path.is_file():
            raise AgendaRenderError(f"packaged font file is missing: {font_path.name}")
        return f"url({_data_uri(font_path, 'font/woff2')})"

    inlined_fonts = FONT_URL_RE.sub(inline_font, font_css)
    if "url(./files/" in inlined_fonts:
        raise AgendaRenderError("not all packaged fonts were inlined")
    logo_uri = _data_uri(logo_path, "image/png")
    return f"{inlined_fonts}\n{css}", logo_uri


def _meeting_title_parts(
    meeting: Mapping[str, Any],
    language: str,
) -> tuple[str, str]:
    number = _display_value(meeting.get("number", ""))
    if language == "en":
        return (f"Meeting {number}" if number else "Club Meeting", "Meeting Agenda")
    if language == "bilingual":
        edition = f"第 {number} 期 / Meeting {number}" if number else "Club Meeting / 例会"
        return edition, "例会议程 / Meeting Agenda"
    return (f"第 {number} 期" if number else "例会", "例会议程")


def _time_check(computed_summary: Mapping[str, Any], language: str) -> str:
    item = _format_minutes(computed_summary.get("item_minutes", ""))
    transition = _format_minutes(computed_summary.get("transition_minutes", ""))
    total = _format_minutes(computed_summary.get("total_minutes", ""))
    status = str(computed_summary.get("status", ""))
    closed = status in {"exact", "exact_with_approved_overtime"}
    label = _localize(
        "时间闭环" if closed else "时间合计",
        "Time closed" if closed else "Time total",
        language,
    )
    if item and transition and total:
        return f"{label}：{item} + {transition} = {total} min"
    return f"{label}：{total} min" if total else label


def render_agenda(
    computed: Mapping[str, Any],
    view: Mapping[str, Any],
    *,
    skill_dir: Path | None = None,
) -> str:
    """Render one self-contained HTML document without changing either input."""

    computed = _require_mapping(computed, "agenda.computed.json")
    view = _require_mapping(view, "agenda.view.json")
    validate_view(computed, view)

    root = (skill_dir or Path(__file__).resolve().parent.parent).resolve()
    css, logo_uri = _bundled_assets(str(root))
    club = _require_mapping(computed.get("club", {}), "agenda.computed.club")
    meeting = _require_mapping(
        computed.get("meeting", {}), "agenda.computed.meeting"
    )
    summary = _require_mapping(
        computed.get("computed", {}), "agenda.computed.computed"
    )
    language = str(club.get("language", "zh")).strip() or "zh"
    if language not in {"zh", "en", "bilingual"}:
        raise AgendaRenderError(
            "agenda.computed.club.language must be zh, en, or bilingual"
        )

    edition, agenda_label = _meeting_title_parts(meeting, language)
    club_name = _display_value(club.get("name", ""))
    start = _display_value(summary.get("start", meeting.get("start", "")))
    end = _display_value(summary.get("final_end", meeting.get("end", "")))
    time_range = f"{start}-{end}" if start or end else ""
    theme = _display_value(meeting.get("theme", ""))
    title_theme = (
        f'<div class="theme-line"><strong>{_e(theme)}</strong></div>'
        if theme
        else ""
    )
    density = str(view["density"])
    design = view["design"]
    auxiliary_count = len(view["display_columns"]) - 4
    timeline_html = _render_timeline(computed, view, language)
    support_html = _render_support_groups(computed, view)
    document_language = "en" if language == "en" else "zh-CN"

    meta = [
        (
            _localize("日期", "Date", language),
            _display_value(meeting.get("date", "")),
            "",
        ),
        (_localize("时间", "Time", language), time_range, ""),
        (
            _localize("地点", "Location", language),
            _display_value(
                meeting.get("location", club.get("default_location", ""))
            ),
            "",
        ),
        (
            _localize("今日一词", "Word of the Day", language),
            _display_value(meeting.get("word_of_day", "")),
            "word",
        ),
        (
            _localize("会议经理", "Meeting Manager", language),
            _display_value(meeting.get("manager", "")),
            "",
        ),
    ]
    meta_html = "".join(
        f'<div class="meta-item{" " + css_class if css_class else ""}">'
        f'<span class="meta-label">{_e(label)}</span>'
        f'<span class="meta-value">{_e(value)}</span></div>'
        for label, value, css_class in meta
    )
    flow_heading = _localize("会议流程", "Meeting Flow", language)
    eyebrow = _localize("头马俱乐部例会", "TOASTMASTERS CLUB MEETING", language)
    page_title = " ".join(part for part in (edition, club_name, agenda_label) if part)

    return f"""<!doctype html>
<html lang="{_e(document_language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="agenda-page-count" content="1">
  <meta name="agenda-workflow" content="v3-preview">
  <title>{_e(page_title)}</title>
  <style>{css}</style>
</head>
<body>
  <article class="agenda-page" data-density="{_e(density)}" data-text-scale="{_e(design['text_scale'])}" data-contrast="{_e(design['contrast'])}" data-language="{_e(language)}" data-auxiliary-columns="{auxiliary_count}">
    <header class="brand-header">
      <div class="brand-logo"><img src="{logo_uri}" alt="Toastmasters International"></div>
      <div class="title-block">
        <p class="eyebrow">{_e(eyebrow)}</p>
        <h1 class="meeting-title">
          <span class="club-name">{_e(club_name)}</span>
          <span class="edition">{_e(edition)}</span>
          <span class="agenda-label">{_e(agenda_label)}</span>
        </h1>
        {title_theme}
      </div>
    </header>

    <section class="meta-strip" aria-label="{_e(_localize('会议信息', 'Meeting information', language))}">
      {meta_html}
    </section>

    <main>
      <section class="agenda-panel" aria-labelledby="flow-heading">
        <div class="panel-heading"><h2 id="flow-heading">{_e(flow_heading)}</h2><span class="meeting-range">{_e(time_range)}</span></div>
        {timeline_html}
      </section>
      {support_html}
    </main>

    <footer class="page-footer">
      <span class="club-footer">{_e(club_name)}</span>
      <span class="time-check">{_e(_time_check(summary, language))}</span>
      <span class="page-mark">1 / 1</span>
    </footer>
  </article>
</body>
</html>
"""


__all__ = ["AgendaRenderError", "render_agenda", "validate_view"]
