#!/usr/bin/env python3
"""Build a validated, time-closed Toastmasters agenda from minimal meeting facts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGO = SKILL_ROOT / "assets" / "toastmasters-logo.png"
PROFILE_ROOT_OVERRIDE = os.environ.get("TOASTMASTERS_AGENDA_PROFILE_ROOT")
if PROFILE_ROOT_OVERRIDE:
    PROFILE_ROOT = Path(PROFILE_ROOT_OVERRIDE).expanduser()
    if not PROFILE_ROOT.is_absolute():
        raise ValueError("TOASTMASTERS_AGENDA_PROFILE_ROOT must be an absolute path")
else:
    PROFILE_ROOT = Path.home() / ".toastmasters-agenda" / "profiles"

UNRESOLVED = {"", "?", "？", "🌺", "待定", "待确认", "招募中", "tbd", "pending", "todo"}
LANGUAGES = {"zh", "en", "bilingual"}
LAYOUTS = {"auto", "standard", "feature", "marathon"}
VISUAL_THEMES = {
    "auto",
    "general",
    "learning",
    "technology",
    "wellness",
    "voice",
    "leadership",
    "celebration",
}
VISUAL_TEXT_SIZES = {"compact", "standard", "large"}
FEATURE_EMPHASIS_LEVELS = {"compact", "standard", "strong"}
OWNER_ALIGNMENTS = {"default", "left", "center"}
HTML_RENDERERS = {"auto", "classic", "editorial"}

CLASSIC_VISUAL_AUDIT_SCRIPT = r"""
<script id="agenda-audit-result" type="application/json"></script>
<script>
(() => {
  const report = { ok: true, failures: [] };
  const fail = (code, detail) => {
    report.ok = false;
    report.failures.push({ code, detail });
  };
  const inspect = async () => {
    try {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      const pages = [...document.querySelectorAll(".page")];
      if (pages.length !== 1) fail("page-count", pages.length);
      pages.forEach((page, pageIndex) => {
        if (page.scrollWidth > page.clientWidth + 1) {
          fail("page-horizontal-overflow", pageIndex);
        }
      });
      document.querySelectorAll(".timeline table").forEach((table, tableIndex) => {
        const headers = [...table.querySelectorAll("thead th")].map((cell) => cell.getBoundingClientRect());
        const headerOwner = table.querySelector("thead th:nth-child(3)");
        const expectedOwnerAlign = headerOwner ? getComputedStyle(headerOwner).textAlign : "";
        table.querySelectorAll("tbody tr:not(.section-row)").forEach((row, rowIndex) => {
          const cells = [...row.cells];
          if (cells.length !== headers.length) {
            fail("timeline-column-count", { table: tableIndex, row: rowIndex, cells: cells.length });
            return;
          }
          cells.forEach((cell, columnIndex) => {
            const actual = cell.getBoundingClientRect();
            const expected = headers[columnIndex];
            if (expected && (Math.abs(actual.left - expected.left) > .75 || Math.abs(actual.right - expected.right) > .75)) {
              fail("timeline-column-edge", { table: tableIndex, row: rowIndex, column: columnIndex });
            }
            if (cell.scrollWidth > cell.clientWidth + 1) {
              fail("timeline-cell-overflow", { table: tableIndex, row: rowIndex, column: columnIndex });
            }
          });
          if (cells[2] && expectedOwnerAlign && getComputedStyle(cells[2]).textAlign !== expectedOwnerAlign) {
            fail("owner-alignment-mismatch", { table: tableIndex, row: rowIndex });
          }
        });
      });
    } catch (error) {
      fail("audit-runtime", error && error.stack ? error.stack : String(error));
    }
    const output = document.querySelector("#agenda-audit-result");
    if (output) output.textContent = JSON.stringify(report);
    document.documentElement.dataset.agendaAudit = report.ok ? "ok" : "failed";
  };
  window.addEventListener("load", inspect, { once: true });
})();
</script>
"""

STANDARD_TYPES = {
    "rules",
    "president_opening",
    "toastmaster_opening",
    "guest_introduction",
    "photo_break",
    "sharing",
    "awards",
    "president_closing",
}

ROLE_IDS = {
    "president",
    "rules_host",
    "toastmaster",
    "timer",
    "ah_counter",
    "grammarian",
    "guest_host",
    "sharing_host",
    "general_evaluator",
    "awards_host",
}

DEFAULT_DURATIONS: dict[str, int | None] = {
    "rules": 2,
    "president_opening": 3,
    "toastmaster_opening": 2,
    "timer_intro": 2,
    "ah_counter_intro": 2,
    "grammarian_intro": 2,
    "guest_introduction": 5,
    "prepared_speech": 7,
    "table_topics": None,
    "photo_break": 5,
    "prepared_evaluation": 3,
    "table_topics_evaluation": None,
    "grammarian_report": 3,
    "ah_counter_report": 3,
    "timer_report": 3,
    "sharing": 6,
    "general_evaluation": 8,
    "awards": 3,
    "president_closing": 2,
    "special": None,
    "buffer": None,
}

LABELS = {
    "rules": ("规则介绍", "Meeting Rules"),
    "president_opening": ("会长致辞", "President's Opening Remarks"),
    "toastmaster_opening": ("总主持开场", "Toastmaster's Opening"),
    "timer_intro": ("时间官宣言", "Timer's Introduction"),
    "ah_counter_intro": ("哼哈官宣言", "Ah-Counter's Introduction"),
    "grammarian_intro": ("语法官宣言", "Grammarian's Introduction"),
    "guest_introduction": ("嘉宾介绍", "Guest Introduction"),
    "prepared_speech": ("备稿演讲", "Prepared Speech"),
    "table_topics": ("即兴演讲", "Table Topics"),
    "photo_break": ("合影＋中场休息", "Group Photo & Break"),
    "prepared_evaluation": ("备稿点评", "Speech Evaluation"),
    "table_topics_evaluation": ("即兴点评", "Table Topics Evaluation"),
    "grammarian_report": ("语法官报告", "Grammarian's Report"),
    "ah_counter_report": ("哼哈官报告", "Ah-Counter's Report"),
    "timer_report": ("时间官报告", "Timer's Report"),
    "sharing": ("真情分享", "Sharing"),
    "general_evaluation": ("总点评", "General Evaluation"),
    "awards": ("颁奖", "Awards"),
    "president_closing": ("闭幕致辞", "President's Closing Remarks"),
    "special": ("特别环节", "Special Session"),
    "buffer": ("缓冲", "Buffer"),
}

SECTION_LABELS = {
    "opening": ("开场", "Opening"),
    "first_half": ("上半场", "First Half"),
    "second_half": ("下半场", "Second Half"),
    "closing": ("收尾", "Closing"),
}

NO_TRANSITION_AFTER = {"rules", "president_opening", "photo_break"}
FLEX_BOUNDS = {
    "photo_break": (1, 15),
    "sharing": (1, 20),
}
AUTO_EVALUATION_MAX_DEVIATION = 2

CORE_OFFICER_ALIASES = {
    "president": {"president", "会长", "主席"},
    "vpe": {
        "vpe",
        "vice president education",
        "vice president of education",
        "教育副会长",
    },
    "vpm": {
        "vpm",
        "vice president membership",
        "vice president of membership",
        "会员副会长",
    },
    "vppr": {
        "vppr",
        "vice president public relations",
        "vice president of public relations",
        "公关副会长",
    },
    "secretary": {"secretary", "秘书", "秘书长"},
    "treasurer": {"treasurer", "财务官"},
    "saa": {"saa", "sergeant at arms", "sergeant-at-arms", "事务官"},
}

SUPPORT_COMPONENTS = {
    "timer_rules",
    "toastmasters_intro",
    "meeting_boundaries",
    "officers",
    "club_intro",
    "join_info",
    "vpm_qr",
    "voting_qr",
}

TOASTMASTERS_INTRO = {
    "zh": (
        "头马国际演讲会成立于1924年，是一个通过全球俱乐部网络帮助会员建立自信、"
        "提升公众演讲、沟通与领导力的非营利教育组织。"
    ),
    "en": (
        "Toastmasters International, founded in 1924, is a nonprofit educational "
        "organization that builds confidence and teaches public speaking, communication "
        "and leadership through a worldwide network of clubs."
    ),
}

MEETING_BOUNDARIES = {
    "zh": [
        "安静：会议过程中保持安静，手机调至静音或震动。",
        "四类禁忌：演讲不涉及政治、宗教、色情或传销。",
        "整洁：结束后带走个人物品与垃圾。",
    ],
    "en": [
        "Quiet: keep phones silent or on vibrate during the meeting.",
        "Four boundaries: avoid politics, religion, pornography and pyramid selling.",
        "Clean: take personal belongings and rubbish when leaving.",
    ],
}

TIMER_RULES = [
    {
        "band_zh": "3分钟及以下",
        "band_en": "3 min or less",
        "green_zh": "剩余1分钟",
        "green_en": "1 min left",
        "yellow_zh": "剩余30秒",
        "yellow_en": "30 sec left",
        "red_zh": "时间到",
        "red_en": "Time",
        "bell_zh": "超时15秒响铃",
        "bell_en": "Bell at +15 sec",
    },
    {
        "band_zh": "超过3分钟至10分钟",
        "band_en": "Over 3 to 10 min",
        "green_zh": "剩余2分钟",
        "green_en": "2 min left",
        "yellow_zh": "剩余1分钟",
        "yellow_en": "1 min left",
        "red_zh": "时间到",
        "red_en": "Time",
        "bell_zh": "超时30秒响铃",
        "bell_en": "Bell at +30 sec",
    },
    {
        "band_zh": "10分钟以上",
        "band_en": "Over 10 min",
        "green_zh": "剩余5分钟",
        "green_en": "5 min left",
        "yellow_zh": "剩余2分钟",
        "yellow_en": "2 min left",
        "red_zh": "时间到",
        "red_en": "Time",
        "bell_zh": "超时30秒响铃",
        "bell_en": "Bell at +30 sec",
    },
]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def is_unresolved(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text.lower() in UNRESOLVED or text in UNRESOLVED or "{{" in text or "}}" in text


def half_minute_value(value: Any, *, allow_zero: bool) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    ticks = round(number * 2)
    if abs(number * 2 - ticks) > 1e-9:
        return None
    if ticks < 0 or (ticks == 0 and not allow_zero):
        return None
    return ticks // 2 if ticks % 2 == 0 else ticks / 2


def positive_minutes(value: Any) -> int | float | None:
    return half_minute_value(value, allow_zero=False)


def nonnegative_minutes(value: Any) -> int | float | None:
    return half_minute_value(value, allow_zero=True)


def minute_ticks(value: int | float) -> int:
    return round(float(value) * 2)


def minutes_from_ticks(ticks: int) -> int | float:
    return ticks // 2 if ticks % 2 == 0 else ticks / 2


def format_minutes(value: int | float) -> str:
    return str(minutes_from_ticks(minute_ticks(value)))


def parse_clock(value: Any) -> int | float:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", str(value))
    if not match:
        raise ValueError(f"invalid clock time {value!r}; use HH:MM or HH:MM:30")
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and second in {0, 30}):
        raise ValueError(f"invalid clock time {value!r}")
    return minutes_from_ticks((hour * 60 + minute) * 2 + second // 30)


def format_clock(value: int | float) -> str:
    ticks = minute_ticks(value) % (24 * 60 * 2)
    whole_minutes, half_tick = divmod(ticks, 2)
    hour, minute = divmod(whole_minutes, 60)
    suffix = ":30" if half_tick else ""
    return f"{hour:02d}:{minute:02d}{suffix}"


def display_label(item_type: str, language: str, override: Any = None) -> str:
    if not is_unresolved(override):
        return str(override).strip()
    zh, en = LABELS.get(item_type, (item_type, item_type))
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def section_label(section: str, language: str) -> str:
    zh, en = SECTION_LABELS.get(section, (section, section))
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def localized(zh: str, en: str, language: str) -> str:
    if language == "en":
        return en
    if language == "bilingual":
        return f"{zh} / {en}"
    return zh


def toastmasters_intro(language: str) -> str:
    if language == "en":
        return TOASTMASTERS_INTRO["en"]
    if language == "bilingual":
        return TOASTMASTERS_INTRO["zh"] + " " + TOASTMASTERS_INTRO["en"]
    return TOASTMASTERS_INTRO["zh"]


def meeting_boundaries(language: str) -> list[str]:
    if language == "en":
        return list(MEETING_BOUNDARIES["en"])
    if language == "bilingual":
        return [
            f"{zh} / {en}"
            for zh, en in zip(MEETING_BOUNDARIES["zh"], MEETING_BOUNDARIES["en"])
        ]
    return list(MEETING_BOUNDARIES["zh"])


def normalize_details(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if not is_unresolved(item)]
    if is_unresolved(value):
        return []
    return [str(value).strip()]


def normalize_support_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if not is_unresolved(item)]
    if is_unresolved(value):
        return []
    text = str(value).strip()
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_visual_preferences(value: Any, errors: list[str]) -> dict[str, str]:
    defaults = {
        "text_size": "standard",
        "feature_emphasis": "standard",
        "owner_alignment": "default",
    }
    if value is None:
        return defaults
    if not isinstance(value, dict):
        errors.append("meeting.visual_preferences must be an object")
        return defaults
    unknown = set(value) - set(defaults)
    if unknown:
        errors.append(
            "meeting.visual_preferences has unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    text_size = str(value.get("text_size", "standard")).strip().lower()
    feature_emphasis = str(
        value.get("feature_emphasis", "standard")
    ).strip().lower()
    owner_alignment = str(value.get("owner_alignment", "default")).strip().lower()
    if text_size not in VISUAL_TEXT_SIZES:
        errors.append(
            "meeting.visual_preferences.text_size must be compact, standard, or large"
        )
        text_size = "standard"
    if feature_emphasis not in FEATURE_EMPHASIS_LEVELS:
        errors.append(
            "meeting.visual_preferences.feature_emphasis must be compact, standard, or strong"
        )
        feature_emphasis = "standard"
    if owner_alignment not in OWNER_ALIGNMENTS:
        errors.append(
            "meeting.visual_preferences.owner_alignment must be default, left, or center"
        )
        owner_alignment = "default"
    return {
        "text_size": text_size,
        "feature_emphasis": feature_emphasis,
        "owner_alignment": owner_alignment,
    }


def normalized_club_name(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def stored_club_profile_path(
    club_name: Any, profile_root: Path | None = None
) -> Path:
    canonical = normalized_club_name(club_name)
    if not canonical:
        raise ValueError("club profile name cannot be empty")
    slug = re.sub(r"[^\w-]+", "-", canonical, flags=re.UNICODE)
    slug = re.sub(r"[_-]+", "-", slug).strip("-")[:48] or "club"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    return (profile_root or PROFILE_ROOT) / f"{slug}-{digest}.json"


def resolve_profile_relative_paths(
    profile: dict[str, Any], profile_path: Path
) -> dict[str, Any]:
    resolved = deepcopy(profile)
    club = resolved.get("club")
    if not isinstance(club, dict):
        return resolved
    raw_qr = club.get("vpm_qr_image")
    if not is_unresolved(raw_qr):
        qr_path = Path(str(raw_qr)).expanduser()
        if not qr_path.is_absolute():
            club["vpm_qr_image"] = str((profile_path.parent / qr_path).resolve())
    return resolved


def club_profile_from_data(
    data: dict[str, Any], source_dir: Path | None = None
) -> dict[str, Any]:
    """Keep only confirmed, reusable club facts for a later meeting task."""
    source = data.get("club")
    if not isinstance(source, dict):
        source = {}
    profile: dict[str, Any] = {
        "name": str(source.get("name", "")).strip(),
        "default_location": str(source.get("default_location", "")).strip(),
        "language": str(source.get("language", "zh")).strip().lower(),
    }
    for key in (
        "support_components",
        "custom_support_blocks",
        "officers",
        "club_intro",
        "join_info",
        "vpm_qr_image",
    ):
        if key in source:
            profile[key] = deepcopy(source[key])
    if "vpm_qr_image" in profile and source_dir is not None:
        qr_path = Path(str(profile["vpm_qr_image"])).expanduser()
        if not qr_path.is_absolute():
            profile["vpm_qr_image"] = str((source_dir / qr_path).resolve())
    return {"club": profile}


def write_club_profile(
    data: dict[str, Any], destination: Path, source_dir: Path
) -> None:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    profile = club_profile_from_data(data, source_dir=source_dir)
    club = profile["club"]
    raw_qr = club.get("vpm_qr_image")
    if not is_unresolved(raw_qr):
        source_qr = Path(str(raw_qr)).expanduser()
        if source_qr.is_file():
            suffix = source_qr.suffix.lower() or ".png"
            asset_dir = destination.parent / "assets" / destination.stem
            asset_dir.mkdir(parents=True, exist_ok=True)
            copied_qr = asset_dir / f"vpm-qr{suffix}"
            if source_qr.resolve() != copied_qr.resolve():
                shutil.copy2(source_qr, copied_qr)
            club["vpm_qr_image"] = str(copied_qr.relative_to(destination.parent))
        else:
            club.pop("vpm_qr_image", None)
    destination.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def normalize_officer_key(value: Any) -> str | None:
    token = re.sub(r"[^a-z]", "", str(value).lower())
    original = str(value).strip().lower()
    for key, aliases in CORE_OFFICER_ALIASES.items():
        for alias in aliases:
            alias_lower = alias.lower()
            alias_token = re.sub(r"[^a-z]", "", alias_lower)
            if original == alias_lower or (token and alias_token and token == alias_token):
                return key
    return None


def parse_officers(value: Any, errors: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        errors.append("club.officers is required and must list the current officer team")
        return []
    result: list[dict[str, str]] = []
    seen_core: set[str] = set()
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            errors.append(f"club.officers[{index}] must be an object")
            continue
        role = row.get("role")
        name = row.get("name")
        if is_unresolved(role):
            errors.append(f"club.officers[{index}] is missing role")
        if is_unresolved(name):
            errors.append(f"club.officers[{index}] is missing name")
        role_text = "" if role is None else str(role).strip()
        name_text = "" if name is None else str(name).strip()
        core_key = normalize_officer_key(role_text)
        if core_key:
            if core_key in seen_core:
                errors.append(f"club.officers contains duplicate core role: {role_text}")
            seen_core.add(core_key)
        result.append({"role": role_text, "name": name_text})
    missing = [key.upper() if key.startswith("vp") or key == "saa" else key.title() for key in CORE_OFFICER_ALIASES if key not in seen_core]
    if missing:
        errors.append("club.officers is missing core roles: " + ", ".join(missing))
    return result


def parse_support_components(value: Any, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(
            "support_components must be an explicit array; ask the user which fixed-content "
            "components to include"
        )
        return []
    result: list[str] = []
    for index, item in enumerate(value, start=1):
        component = str(item).strip()
        if component not in SUPPORT_COMPONENTS:
            errors.append(f"support_components[{index}] is unsupported: {component!r}")
            continue
        if component in result:
            errors.append(f"duplicate support component: {component}")
            continue
        result.append(component)
    return result


def parse_custom_support_blocks(
    value: Any, errors: list[str]
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append("custom_support_blocks must be an array")
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            errors.append(f"custom_support_blocks[{index}] must be an object")
            continue
        block_id = str(row.get("id", "")).strip()
        title = row.get("title")
        lines = normalize_support_text(row.get("lines", row.get("content")))
        placement = str(row.get("placement", "auto")).strip().lower()
        if not block_id:
            errors.append(f"custom_support_blocks[{index}] is missing id")
            continue
        if block_id in seen or block_id in SUPPORT_COMPONENTS:
            errors.append(f"duplicate or reserved custom support block id: {block_id}")
            continue
        if is_unresolved(title):
            errors.append(f"custom support block {block_id} is missing title")
        if not lines:
            errors.append(f"custom support block {block_id} has no content")
        if placement not in {"auto", "left", "bottom"}:
            errors.append(
                f"custom support block {block_id} placement must be auto, left, or bottom"
            )
            placement = "auto"
        seen.add(block_id)
        result.append(
            {
                "id": block_id,
                "title": "" if title is None else str(title).strip(),
                "lines": lines,
                "placement": placement,
            }
        )
    return result


def find_photographer(backstage: list[dict[str, Any]]) -> str | None:
    for row in backstage:
        token = f"{row.get('id', '')} {row.get('role', '')} {row.get('label', '')}".lower()
        if re.search(r"photographer|photo|摄影|拍照", token):
            person = row.get("person", row.get("name"))
            if not is_unresolved(person):
                return str(person).strip()
    return None


def select_layout(
    meeting: dict[str, Any],
    items: list[dict[str, Any]],
    errors: list[str],
) -> str:
    requested = str(meeting.get("layout", "auto")).strip().lower()
    if requested not in LAYOUTS:
        errors.append("meeting.layout must be auto, standard, feature, or marathon")
        requested = "auto"
    if requested != "auto":
        return requested
    if not is_unresolved(meeting.get("feature_item")):
        return "feature"
    prepared_count = sum(1 for item in items if item["type"] == "prepared_speech")
    has_feature = any(
        item["type"] == "special" and float(item["duration"]) >= 15
        for item in items
    ) or any(
        item["type"] == "prepared_speech" and float(item["duration"]) >= 20
        for item in items
    )
    if has_feature:
        return "feature"
    if prepared_count >= 5:
        return "marathon"
    return "standard"


def select_feature_item(
    meeting: dict[str, Any],
    items: list[dict[str, Any]],
    layout: str,
    errors: list[str],
) -> str | None:
    raw_requested = meeting.get("feature_item")
    requested = "" if is_unresolved(raw_requested) else str(raw_requested).strip()
    if requested:
        if not any(item["id"] == requested for item in items):
            errors.append(f"meeting.feature_item references missing agenda item: {requested!r}")
            return None
        return requested
    if layout != "feature":
        return None
    candidates = [
        item
        for item in items
        if (item["type"] == "special" and float(item["duration"]) >= 15)
        or (item["type"] == "prepared_speech" and float(item["duration"]) >= 20)
    ]
    if not candidates:
        return None
    longest = max(float(item["duration"]) for item in candidates)
    return next(item["id"] for item in candidates if float(item["duration"]) == longest)


def select_visual_theme(
    meeting: dict[str, Any],
    items: list[dict[str, Any]],
    errors: list[str],
) -> str:
    requested = str(meeting.get("visual_theme", "auto")).strip().lower()
    if requested not in VISUAL_THEMES:
        errors.append(
            "meeting.visual_theme must be auto, general, learning, technology, "
            "wellness, voice, leadership, or celebration"
        )
        requested = "auto"
    if requested != "auto":
        return requested
    primary_text = " ".join(
        [str(meeting.get("theme", "")), str(meeting.get("word_of_day", ""))]
    ).lower()
    secondary_text = " ".join(
        [
            *[str(item.get("label", "")) for item in items],
            *[
                str(detail)
                for item in items
                for detail in item.get("details", [])
            ],
        ]
    ).lower()
    keyword_groups = [
        ("technology", ("ai", "vibe", "coding", "code", "科技", "代码", "数字", "智能")),
        ("wellness", ("health", "wellness", "健康", "体质", "疗愈", "自然", "冥想")),
        ("voice", ("voice", "speech", "story", "声音", "表达", "演讲", "故事")),
        ("celebration", ("celebration", "anniversary", "周年", "庆典", "庆祝", "颁奖")),
        ("leadership", ("leadership", "leader", "领导", "领导力", "影响力")),
        ("learning", ("learn", "brain", "knowledge", "book", "学习", "思考", "大脑", "知识", "成长")),
    ]
    for text in (primary_text, secondary_text):
        for theme, keywords in keyword_groups:
            if any(keyword in text for keyword in keywords):
                return theme
    return "general"


def make_item(
    item_type: str,
    owner: Any,
    language: str,
    section: str,
    *,
    item_id: str | None = None,
    label: Any = None,
    duration: int | float | None = None,
    locked: bool = True,
    preferred: int | float | None = None,
    details: Any = None,
    transition_after: int | float | None = None,
    owner_required: bool = True,
    source: str = "generated",
) -> dict[str, Any]:
    return {
        "id": item_id or item_type,
        "type": item_type,
        "label": display_label(item_type, language, label),
        "owner": "" if owner is None else str(owner).strip(),
        "owner_required": owner_required,
        "section": section,
        "details": normalize_details(details),
        "duration": duration,
        "duration_locked": locked,
        "preferred_duration": preferred,
        "transition_after_override": transition_after,
        "source": source,
    }


def parse_roles(data: Any, errors: list[str]) -> tuple[list[str], dict[str, str]]:
    if data is None:
        return [], {}
    if not isinstance(data, list):
        errors.append("roles must be an array")
        return [], {}
    order: list[str] = []
    mapping: dict[str, str] = {}
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"roles[{index}] must be an object")
            continue
        role_id = str(row.get("id", "")).strip()
        if role_id not in ROLE_IDS:
            errors.append(f"roles[{index}] has unsupported id: {role_id!r}")
            continue
        if role_id in mapping:
            errors.append(f"duplicate role id: {role_id}")
            continue
        person = row.get("person")
        if is_unresolved(person):
            errors.append(f"role {role_id} exists but its person is unresolved")
            mapping[role_id] = ""
        else:
            mapping[role_id] = str(person).strip()
        order.append(role_id)
    return order, mapping


def parse_backstage(data: Any, errors: list[str]) -> list[dict[str, Any]]:
    if data is None:
        return []
    if not isinstance(data, list):
        errors.append("backstage must be an array")
        return []
    result: list[dict[str, Any]] = []
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"backstage[{index}] must be an object")
            continue
        role_id = str(row.get("id", row.get("role", ""))).strip()
        person = row.get("person", row.get("name"))
        if not role_id:
            errors.append(f"backstage[{index}] is missing id/role")
        if is_unresolved(person):
            errors.append(f"backstage role {role_id or index} has unresolved person")
        result.append(
            {
                "id": role_id,
                "label": str(row.get("label", row.get("role", role_id))).strip(),
                "person": "" if person is None else str(person).strip(),
            }
        )
    return result


def parse_overrides(data: Any, errors: list[str]) -> dict[str, dict[str, Any]]:
    if data is None:
        return {}
    if not isinstance(data, list):
        errors.append("standard_overrides must be an array")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"standard_overrides[{index}] must be an object")
            continue
        item_id = str(row.get("id", "")).strip()
        if item_id not in STANDARD_TYPES:
            errors.append(f"standard_overrides[{index}] has unsupported id: {item_id!r}")
            continue
        if item_id in result:
            errors.append(f"duplicate standard override: {item_id}")
            continue
        normalized = deepcopy(row)
        if "enabled" in row and not isinstance(row["enabled"], bool):
            errors.append(f"standard override {item_id} enabled must be a boolean")
        if "minutes" in row:
            minutes = positive_minutes(row["minutes"])
            if minutes is None:
                errors.append(
                    f"standard override {item_id} minutes must be positive in 0.5-minute increments"
                )
                normalized.pop("minutes", None)
            else:
                normalized["minutes"] = minutes
        if "transition_after" in row:
            transition = nonnegative_minutes(row["transition_after"])
            if transition is None:
                errors.append(
                    f"standard override {item_id} transition_after must be nonnegative "
                    "in 0.5-minute increments"
                )
                normalized.pop("transition_after", None)
            else:
                normalized["transition_after"] = transition
        result[item_id] = normalized
    return result


def parse_agenda_overrides(
    data: Any, errors: list[str]
) -> dict[str, dict[str, Any]]:
    if data is None:
        return {}
    if not isinstance(data, list):
        errors.append("agenda_overrides must be an array")
        return {}
    allowed_fields = {
        "id",
        "enabled",
        "minutes",
        "owner",
        "label",
        "transition_after",
        "after",
    }
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"agenda_overrides[{index}] must be an object")
            continue
        item_id = str(row.get("id", "")).strip()
        if not item_id:
            errors.append(f"agenda_overrides[{index}] is missing id")
            continue
        if item_id in result:
            errors.append(f"duplicate agenda override: {item_id}")
            continue
        unknown = set(row) - allowed_fields
        if unknown:
            errors.append(
                f"agenda override {item_id} has unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        normalized = {"id": item_id}
        if "enabled" in row:
            if not isinstance(row["enabled"], bool):
                errors.append(f"agenda override {item_id} enabled must be a boolean")
            else:
                normalized["enabled"] = row["enabled"]
        if "minutes" in row:
            minutes = positive_minutes(row["minutes"])
            if minutes is None:
                errors.append(
                    f"agenda override {item_id} minutes must be positive "
                    "in 0.5-minute increments"
                )
            else:
                normalized["minutes"] = minutes
        if "transition_after" in row:
            transition = nonnegative_minutes(row["transition_after"])
            if transition is None:
                errors.append(
                    f"agenda override {item_id} transition_after must be nonnegative "
                    "in 0.5-minute increments"
                )
            else:
                normalized["transition_after"] = transition
        if "owner" in row:
            if is_unresolved(row["owner"]):
                errors.append(f"agenda override {item_id} owner is unresolved")
            else:
                normalized["owner"] = str(row["owner"]).strip()
        if "label" in row:
            if is_unresolved(row["label"]):
                errors.append(f"agenda override {item_id} label is unresolved")
            else:
                normalized["label"] = str(row["label"]).strip()
        if "after" in row:
            if is_unresolved(row["after"]):
                errors.append(f"agenda override {item_id} after is unresolved")
            else:
                normalized["after"] = str(row["after"]).strip()
        result[item_id] = normalized
    return result


def reorder_agenda_items(
    items: list[dict[str, Any]],
    moves: list[tuple[str, str]],
    errors: list[str],
) -> list[dict[str, Any]]:
    if not moves:
        return items
    existing_ids = {item["id"] for item in items}
    move_map = dict(moves)
    invalid = False
    for item_id, anchor_id in moves:
        if item_id not in existing_ids:
            errors.append(f"agenda reorder references missing item: {item_id!r}")
            invalid = True
        if anchor_id not in existing_ids:
            errors.append(
                f"agenda override {item_id} references missing after anchor: {anchor_id!r}"
            )
            invalid = True
        if item_id == anchor_id:
            errors.append(f"agenda override {item_id} cannot be placed after itself")
            invalid = True

    for start in move_map:
        seen: set[str] = set()
        cursor = start
        while cursor in move_map:
            if cursor in seen:
                errors.append(f"agenda reorder contains a cycle involving {start!r}")
                invalid = True
                break
            seen.add(cursor)
            cursor = move_map[cursor]
    if invalid:
        return items

    ordered_moves: list[tuple[str, str]] = []
    visited: set[str] = set()

    def append_after_anchor(item_id: str) -> None:
        if item_id in visited:
            return
        anchor_id = move_map[item_id]
        if anchor_id in move_map:
            append_after_anchor(anchor_id)
        visited.add(item_id)
        ordered_moves.append((item_id, anchor_id))

    for item_id, _ in moves:
        append_after_anchor(item_id)

    reordered = list(items)
    shared_anchor_tails: dict[str, str] = {}
    for item_id, requested_anchor in ordered_moves:
        anchor_id = shared_anchor_tails.get(requested_anchor, requested_anchor)
        item_index = next(
            index for index, item in enumerate(reordered) if item["id"] == item_id
        )
        item = reordered.pop(item_index)
        anchor_index = next(
            index for index, candidate in enumerate(reordered) if candidate["id"] == anchor_id
        )
        anchor = reordered[anchor_index]
        item["section"] = anchor["section"]
        reordered.insert(anchor_index + 1, item)
        shared_anchor_tails[requested_anchor] = item_id
    return reordered


def apply_agenda_overrides(
    items: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    standard_overrides: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in items}
    removed: set[str] = set()
    moves: list[tuple[str, str]] = []
    for item_id, override in overrides.items():
        item = by_id.get(item_id)
        if item is None:
            errors.append(f"agenda override references missing item: {item_id!r}")
            continue
        legacy = standard_overrides.get(item_id, {})
        overlapping = (set(override) - {"id"}) & set(legacy)
        if overlapping:
            errors.append(
                f"agenda item {item_id} is overridden twice for: "
                + ", ".join(sorted(overlapping))
            )
            continue
        if override.get("enabled") is False:
            removed.add(item_id)
            continue
        if "minutes" in override:
            item["duration"] = override["minutes"]
            item["duration_locked"] = True
            item["computed_flexible"] = False
        if "owner" in override:
            item["owner"] = override["owner"]
        if "label" in override:
            item["label"] = override["label"]
        if "transition_after" in override:
            if item.get("transition_after_override") is not None:
                errors.append(
                    f"transition for {item_id} is defined twice; keep one override"
                )
            else:
                item["transition_after_override"] = override["transition_after"]
        if "after" in override:
            moves.append((item_id, override["after"]))
    filtered = [item for item in items if item["id"] not in removed]
    filtered = reorder_agenda_items(filtered, moves, errors)
    remaining_ids = {item["id"] for item in filtered}
    for item in filtered:
        item_id = str(item["id"])
        if item_id.startswith("prepared_evaluation:"):
            number = item_id.split(":", 1)[1]
            if f"prepared_speech:{number}" not in remaining_ids:
                errors.append(
                    f"{item_id} remains but prepared_speech:{number} was removed"
                )
        if item_id == "table_topics_evaluation" and "table_topics" not in remaining_ids:
            errors.append("table_topics_evaluation remains but table_topics was removed")
    return filtered


def parse_transition_overrides(
    data: Any, errors: list[str]
) -> dict[str, int | float]:
    if data is None:
        return {}
    if not isinstance(data, list):
        errors.append("transition_overrides must be an array")
        return {}
    result: dict[str, int | float] = {}
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            errors.append(f"transition_overrides[{index}] must be an object")
            continue
        item_id = str(row.get("id", "")).strip()
        if not item_id:
            errors.append(f"transition_overrides[{index}] is missing id")
            continue
        if item_id in result:
            errors.append(f"duplicate transition override: {item_id}")
            continue
        minutes = nonnegative_minutes(row.get("minutes"))
        if minutes is None:
            errors.append(
                f"transition override {item_id} minutes must be nonnegative "
                "in 0.5-minute increments"
            )
            continue
        result[item_id] = minutes
    return result


def attach_transition_overrides(
    items: list[dict[str, Any]],
    overrides: dict[str, int | float],
    errors: list[str],
) -> None:
    by_id = {item["id"]: item for item in items}
    for item_id, minutes in overrides.items():
        item = by_id.get(item_id)
        if item is None:
            errors.append(f"transition override references missing item: {item_id!r}")
            continue
        existing = item.get("transition_after_override")
        if existing is not None:
            errors.append(
                f"transition for {item_id} is defined twice; keep either the item-specific "
                "value or transition_overrides"
            )
            continue
        item["transition_after_override"] = minutes


def build_items(
    data: dict[str, Any],
    language: str,
    meeting: dict[str, Any],
    role_order: list[str],
    roles: dict[str, str],
    backstage: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    photographer = find_photographer(backstage)
    president = meeting.get("president") or roles.get("president")

    def standard(
        item_type: str,
        owner: Any,
        section: str,
        *,
        flexible: bool = False,
    ) -> dict[str, Any] | None:
        override = overrides.get(item_type, {})
        if override.get("enabled", True) is False:
            return None
        resolved_owner = override.get("owner", owner)
        explicit_minutes = override.get("minutes")
        if explicit_minutes is not None:
            duration = explicit_minutes
            locked = True
            preferred = None
        elif flexible:
            duration = None
            locked = False
            preferred = DEFAULT_DURATIONS[item_type]
        else:
            duration = DEFAULT_DURATIONS[item_type]
            locked = True
            preferred = None
        return make_item(
            item_type,
            resolved_owner,
            language,
            section,
            label=override.get("label"),
            duration=duration,
            locked=locked,
            preferred=preferred,
            transition_after=override.get("transition_after"),
            source="standard",
        )

    for item in (
        standard("rules", roles.get("rules_host"), "opening"),
        standard("president_opening", president, "opening"),
        standard("toastmaster_opening", roles.get("toastmaster"), "opening"),
    ):
        if item:
            items.append(item)

    function_role_types = {
        "timer": ("timer_intro", "timer_report"),
        "ah_counter": ("ah_counter_intro", "ah_counter_report"),
        "grammarian": ("grammarian_intro", "grammarian_report"),
    }
    present_functions = [role_id for role_id in role_order if role_id in function_role_types]
    for role_id in present_functions:
        intro_type, _ = function_role_types[role_id]
        items.append(
            make_item(
                intro_type,
                roles[role_id],
                language,
                "opening",
                duration=DEFAULT_DURATIONS[intro_type],
                source="role",
            )
        )

    guest = standard("guest_introduction", roles.get("guest_host"), "opening")
    if guest:
        items.append(guest)

    speeches = data.get("prepared_speeches", [])
    if speeches is None:
        speeches = []
    if not isinstance(speeches, list):
        errors.append("prepared_speeches must be an array")
        speeches = []
    evaluation_items: list[dict[str, Any]] = []
    for index, speech in enumerate(speeches, start=1):
        if not isinstance(speech, dict):
            errors.append(f"prepared_speeches[{index}] must be an object")
            continue
        speaker = speech.get("speaker")
        if is_unresolved(speaker):
            errors.append(f"prepared speech {index} has unresolved speaker")
        minutes_value = speech.get("minutes")
        if minutes_value is None:
            project_text = f"{speech.get('project', '')} {speech.get('title', '')}"
            duration = 6 if re.search(r"ice\s*breaker|破冰", project_text, re.I) else 7
        else:
            duration = positive_minutes(minutes_value)
            if duration is None:
                errors.append(
                    f"prepared speech {index} minutes must be positive in 0.5-minute increments"
                )
                duration = 7
        details = []
        if not is_unresolved(speech.get("title")):
            details.append(str(speech["title"]).strip())
        if not is_unresolved(speech.get("project")):
            details.append(str(speech["project"]).strip())
        label_override = speech.get("label")
        label = display_label("prepared_speech", language, label_override)
        label = f"{label} {index}"
        items.append(
            make_item(
                "prepared_speech",
                speaker,
                language,
                "first_half",
                item_id=f"prepared_speech:{index}",
                label=label,
                duration=duration,
                details=details,
                source="prepared_speech",
            )
        )
        evaluation_enabled = speech.get("evaluation_enabled", True)
        if not isinstance(evaluation_enabled, bool):
            errors.append(f"prepared speech {index} evaluation_enabled must be a boolean")
            evaluation_enabled = True
        if evaluation_enabled:
            evaluator = speech.get("evaluator")
            if is_unresolved(evaluator):
                errors.append(f"prepared speech {index} requires an evaluator but the name is unresolved")
            evaluation_minutes = speech.get("evaluation_minutes")
            if evaluation_minutes is None:
                evaluation_duration = 3
            else:
                evaluation_duration = positive_minutes(evaluation_minutes)
                if evaluation_duration is None:
                    errors.append(
                        f"prepared speech {index} evaluation_minutes must be positive "
                        "in 0.5-minute increments"
                    )
                    evaluation_duration = 3
            eval_label = display_label("prepared_evaluation", language, speech.get("evaluation_label"))
            evaluation_items.append(
                make_item(
                    "prepared_evaluation",
                    evaluator,
                    language,
                    "second_half",
                    item_id=f"prepared_evaluation:{index}",
                    label=f"{eval_label} {index}",
                    duration=evaluation_duration,
                    details=details[:1],
                    source="prepared_speech",
                )
            )
        elif "evaluator" in speech and not is_unresolved(speech.get("evaluator")):
            errors.append(
                f"prepared speech {index} sets evaluation_enabled false but also supplies an evaluator"
            )

    impromptu = data.get("impromptu")
    table_topics_item: dict[str, Any] | None = None
    table_topics_evaluation_item: dict[str, Any] | None = None
    if impromptu is not None:
        if not isinstance(impromptu, dict):
            errors.append("impromptu must be an object or null")
        else:
            host = impromptu.get("host")
            if is_unresolved(host):
                errors.append("impromptu exists but its host is unresolved")
            minutes_value = impromptu.get("minutes")
            if minutes_value is None:
                tt_duration = None
                tt_locked = False
            else:
                tt_duration = positive_minutes(minutes_value)
                tt_locked = True
                if tt_duration is None:
                    errors.append(
                        "impromptu.minutes must be positive in 0.5-minute increments"
                    )
                    tt_duration = 15
            table_topics_item = make_item(
                "table_topics",
                host,
                language,
                "first_half",
                duration=tt_duration,
                locked=tt_locked,
                preferred=15 if not tt_locked else None,
                details=impromptu.get("details"),
                source="impromptu",
            )
            items.append(table_topics_item)
            if "evaluator" in impromptu:
                evaluator = impromptu.get("evaluator")
                if is_unresolved(evaluator):
                    errors.append("impromptu requires an evaluator but the name is unresolved")
                evaluation_minutes = impromptu.get("evaluation_minutes")
                if evaluation_minutes is None:
                    eval_duration = None
                    eval_locked = False
                else:
                    eval_duration = positive_minutes(evaluation_minutes)
                    eval_locked = True
                    if eval_duration is None:
                        errors.append(
                            "impromptu.evaluation_minutes must be positive in 0.5-minute increments"
                        )
                        eval_duration = 7
                table_topics_evaluation_item = make_item(
                    "table_topics_evaluation",
                    evaluator,
                    language,
                    "second_half",
                    duration=eval_duration,
                    locked=eval_locked,
                    preferred=None,
                    source="impromptu",
                )

    photo_break = standard("photo_break", photographer, "first_half", flexible=True)
    if photo_break:
        items.append(photo_break)

    items.extend(evaluation_items)
    if table_topics_evaluation_item:
        items.append(table_topics_evaluation_item)

    for role_id in reversed(present_functions):
        _, report_type = function_role_types[role_id]
        items.append(
            make_item(
                report_type,
                roles[role_id],
                language,
                "second_half",
                duration=DEFAULT_DURATIONS[report_type],
                source="role",
            )
        )

    sharing = standard("sharing", roles.get("sharing_host"), "closing", flexible=True)
    if sharing:
        items.append(sharing)

    if "general_evaluator" in roles:
        items.append(
            make_item(
                "general_evaluation",
                roles["general_evaluator"],
                language,
                "closing",
                duration=8,
                source="role",
            )
        )

    awards = standard("awards", roles.get("awards_host"), "closing")
    if awards:
        items.append(awards)
    closing = standard("president_closing", president, "closing")
    if closing:
        items.append(closing)

    specials = data.get("special_segments", [])
    if specials is None:
        specials = []
    if not isinstance(specials, list):
        errors.append("special_segments must be an array")
        specials = []
    last_anchor: dict[str, str] = {}
    for index, segment in enumerate(specials, start=1):
        if not isinstance(segment, dict):
            errors.append(f"special_segments[{index}] must be an object")
            continue
        title = segment.get("title")
        owner = segment.get("owner")
        duration = positive_minutes(segment.get("minutes"))
        if is_unresolved(title):
            errors.append(f"special segment {index} has unresolved title")
        if is_unresolved(owner):
            errors.append(f"special segment {index} has unresolved owner")
        if duration is None:
            errors.append(
                f"special segment {index} minutes must be positive in 0.5-minute increments"
            )
            duration = 1
        anchor = str(segment.get("after", "guest_introduction")).strip()
        anchor = last_anchor.get(anchor, anchor)
        anchor_index = next((i for i, item in enumerate(items) if item["id"] == anchor), None)
        if anchor_index is None:
            errors.append(f"special segment {index} references missing anchor: {anchor!r}")
            continue
        special_id = f"special:{index}"
        special = make_item(
            "special",
            owner,
            language,
            str(segment.get("section", items[anchor_index]["section"])),
            item_id=special_id,
            label=title,
            duration=duration,
            details=segment.get("details"),
            transition_after=segment.get("transition_after"),
            source="special",
        )
        items.insert(anchor_index + 1, special)
        original_anchor = str(segment.get("after", "guest_introduction")).strip()
        last_anchor[original_anchor] = special_id

    return items


def apply_transitions(
    items: list[dict[str, Any]], errors: list[str]
) -> int | float:
    total_ticks = 0
    for index, item in enumerate(items):
        override = item.get("transition_after_override")
        if override is not None:
            transition = nonnegative_minutes(override)
            if transition is None:
                errors.append(
                    f"{item['id']} transition_after must be nonnegative "
                    "in 0.5-minute increments"
                )
                transition = 0
        elif index == len(items) - 1 or item["type"] in NO_TRANSITION_AFTER:
            transition = 0
        else:
            transition = 1
        item["transition_after"] = transition
        total_ticks += minute_ticks(transition)
    return minutes_from_ticks(total_ticks)


def score_flexible_solution(
    actual: dict[str, int | float],
    table_topics_present: bool,
    table_topics_evaluation_present: bool,
) -> float:
    score = 0.0
    if table_topics_present and table_topics_evaluation_present:
        score += abs(actual["table_topics_evaluation"] - actual["table_topics"] / 2) * 20
    if "photo_break" in actual:
        score += (actual["photo_break"] - 5) ** 2
    if "sharing" in actual:
        score += (actual["sharing"] - 6) ** 2
    if "table_topics" in actual:
        score += (actual["table_topics"] - 15) ** 2 * 0.01
    score += sum(minute_ticks(value) % 2 for value in actual.values()) * 0.5
    return score


def solve_flexible(
    items: list[dict[str, Any]], target_item_minutes: int | float
) -> bool:
    variables = [item for item in items if item.get("duration") is None]
    locked_total_ticks = sum(
        minute_ticks(item["duration"])
        for item in items
        if item.get("duration") is not None
    )
    required_ticks = minute_ticks(target_item_minutes) - locked_total_ticks
    if not variables:
        return required_ticks == 0
    if required_ticks < len(variables) * 2:
        return False

    by_type = {item["type"]: item for item in variables}
    tt_item = next((item for item in items if item["type"] == "table_topics"), None)
    eval_item = next((item for item in items if item["type"] == "table_topics_evaluation"), None)
    tt_variable = "table_topics" in by_type
    eval_variable = "table_topics_evaluation" in by_type

    tt_values = range(2, required_ticks + 1) if tt_variable else [None]
    eval_values = range(2, required_ticks + 1) if eval_variable else [None]
    remaining_types = [
        item_type for item_type in ("photo_break", "sharing") if item_type in by_type
    ]
    unsupported = [item["type"] for item in variables if item["type"] not in {
        "table_topics", "table_topics_evaluation", "photo_break", "sharing"
    }]
    if unsupported:
        return False

    best: tuple[float, dict[str, int]] | None = None
    for tt_value in tt_values:
        for eval_value in eval_values:
            assignment: dict[str, int] = {}
            used_ticks = 0
            if tt_variable:
                assignment["table_topics"] = int(tt_value)
                used_ticks += int(tt_value)
            if eval_variable:
                assignment["table_topics_evaluation"] = int(eval_value)
                used_ticks += int(eval_value)
            remainder_ticks = required_ticks - used_ticks
            if not remaining_types:
                if remainder_ticks != 0:
                    continue
            elif len(remaining_types) == 1:
                item_type = remaining_types[0]
                lower, upper = FLEX_BOUNDS[item_type]
                lower_ticks = minute_ticks(lower)
                upper_ticks = minute_ticks(upper)
                if not (lower_ticks <= remainder_ticks <= upper_ticks):
                    continue
                assignment[item_type] = remainder_ticks
            else:
                first, second = remaining_types
                first_pref = minute_ticks(5 if first == "photo_break" else 6)
                second_pref = minute_ticks(5 if second == "photo_break" else 6)
                first_min, first_max = FLEX_BOUNDS[first]
                second_min, second_max = FLEX_BOUNDS[second]
                first_min_ticks = minute_ticks(first_min)
                first_max_ticks = minute_ticks(first_max)
                second_min_ticks = minute_ticks(second_min)
                second_max_ticks = minute_ticks(second_max)
                feasible_min = max(
                    first_min_ticks, remainder_ticks - second_max_ticks
                )
                feasible_max = min(
                    first_max_ticks, remainder_ticks - second_min_ticks
                )
                if feasible_min > feasible_max:
                    continue
                ideal_first = (
                    remainder_ticks + first_pref - second_pref
                ) / 2
                first_value = min(
                    range(feasible_min, feasible_max + 1),
                    key=lambda value: (
                        value % 2 + (remainder_ticks - value) % 2,
                        abs(value - ideal_first),
                    ),
                )
                assignment[first] = first_value
                assignment[second] = remainder_ticks - first_value

            actual: dict[str, int | float] = {}
            for item_type in ("table_topics", "table_topics_evaluation", "photo_break", "sharing"):
                item = next((row for row in items if row["type"] == item_type), None)
                if item is None:
                    continue
                if item_type in assignment:
                    actual[item_type] = minutes_from_ticks(assignment[item_type])
                else:
                    actual[item_type] = item["duration"]
            if (tt_variable or eval_variable) and {
                "table_topics",
                "table_topics_evaluation",
            }.issubset(actual):
                evaluation_gap = abs(
                    float(actual["table_topics_evaluation"])
                    - float(actual["table_topics"]) / 2
                )
                if evaluation_gap > AUTO_EVALUATION_MAX_DEVIATION:
                    continue
            score = score_flexible_solution(
                actual,
                table_topics_present=tt_item is not None,
                table_topics_evaluation_present=eval_item is not None,
            )
            if best is None or score < best[0]:
                best = (score, assignment)

    if best is None:
        return False
    for item_type, duration_ticks in best[1].items():
        by_type[item_type]["duration"] = minutes_from_ticks(duration_ticks)
        by_type[item_type]["computed_flexible"] = True
    return True


def fill_flexible_preferences(items: list[dict[str, Any]]) -> None:
    tt_duration: int | float | None = None
    for item in items:
        if item["type"] == "table_topics" and item.get("duration") is not None:
            tt_duration = item["duration"]
    for item in items:
        if item.get("duration") is not None:
            continue
        if item["type"] == "table_topics":
            item["duration"] = 15
            tt_duration = 15
        elif item["type"] == "table_topics_evaluation":
            half_ticks = math.floor(float(tt_duration or 15) + 0.5)
            item["duration"] = max(1, minutes_from_ticks(half_ticks))
        else:
            item["duration"] = positive_minutes(item.get("preferred_duration")) or 1


def validate_owners(items: list[dict[str, Any]], errors: list[str]) -> None:
    for item in items:
        if item.get("owner_required", True) and is_unresolved(item.get("owner")):
            errors.append(f"{item['label']} is missing its responsible person")


def validate_role_relationships(items: list[dict[str, Any]], warnings: list[str]) -> None:
    tt = next((item for item in items if item["type"] == "table_topics"), None)
    evaluation = next((item for item in items if item["type"] == "table_topics_evaluation"), None)
    if evaluation and not tt:
        warnings.append("table topics evaluation exists without a table topics session")
    if tt and evaluation and tt.get("duration") and evaluation.get("duration"):
        difference = abs(float(evaluation["duration"]) - float(tt["duration"]) / 2)
        if difference > AUTO_EVALUATION_MAX_DEVIATION:
            warnings.append(
                "table topics evaluation is "
                f"{format_minutes(evaluation['duration'])} minutes while table topics is "
                f"{format_minutes(tt['duration'])} minutes; confirm this intentional deviation"
            )


def validate_auto_flexible_durations(
    items: list[dict[str, Any]], warnings: list[str]
) -> None:
    comfortable = {
        "photo_break": (3, 10),
        "sharing": (3, 10),
    }
    for item in items:
        if not item.get("computed_flexible") or item["type"] not in comfortable:
            continue
        lower, upper = comfortable[item["type"]]
        duration = float(item["duration"])
        if duration < lower or duration > upper:
            warnings.append(
                f"{item['type']} was automatically set to {format_minutes(item['duration'])} "
                f"minutes; confirm this is operationally suitable or rebalance the agenda"
            )


def assign_timeline(
    items: list[dict[str, Any]], start: int | float
) -> int | float:
    cursor = start
    for item in items:
        item["start"] = format_clock(cursor)
        cursor += item["duration"]
        item["end"] = format_clock(cursor)
        cursor += item["transition_after"]
    return cursor


def build_agenda(
    data: dict[str, Any],
    source_dir: Path | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    normalized = deepcopy(data)
    errors: list[str] = []
    warnings: list[str] = []

    club = normalized.get("club")
    if not isinstance(club, dict):
        errors.append("club must be an object")
        club = {}
    for field in ("name", "default_location", "language"):
        if is_unresolved(club.get(field)):
            errors.append(f"club.{field} is required")
    language = str(club.get("language", "zh")).strip().lower()
    if language not in LANGUAGES:
        errors.append("club.language must be zh, en, or bilingual")
        language = "zh"
    meeting = normalized.get("meeting")
    if not isinstance(meeting, dict):
        errors.append("meeting must be an object")
        meeting = {}
    visual_preferences = parse_visual_preferences(
        meeting.get("visual_preferences"), errors
    )
    for field in ("number", "date", "start"):
        if is_unresolved(meeting.get(field)):
            errors.append(f"meeting.{field} is required")
    location = meeting.get("location", club.get("default_location"))
    if is_unresolved(location):
        errors.append("meeting location is unresolved")
    meeting["location"] = "" if location is None else str(location).strip()
    support_components = parse_support_components(
        meeting.get("support_components", club.get("support_components")),
        errors,
    )
    custom_support_blocks = parse_custom_support_blocks(
        meeting.get(
            "custom_support_blocks",
            club.get(
                "custom_support_blocks",
                normalized.get("custom_support_blocks"),
            ),
        ),
        errors,
    )
    officers = (
        parse_officers(club.get("officers"), errors)
        if "officers" in support_components
        else []
    )
    club_intro = normalize_support_text(club.get("club_intro"))
    join_info = normalize_support_text(club.get("join_info"))
    if "club_intro" in support_components and not club_intro:
        errors.append("club_intro component is selected but club.club_intro is empty")
    if "join_info" in support_components and not join_info:
        errors.append("join_info component is selected but club.join_info is empty")
    resolved_source_dir = (source_dir or Path.cwd()).expanduser().resolve()
    vpm_qr_data = ""
    if "vpm_qr" in support_components:
        if is_unresolved(club.get("vpm_qr_image")):
            errors.append("vpm_qr component is selected but club.vpm_qr_image is missing")
        else:
            vpm_qr_data = resolve_support_image(
                club.get("vpm_qr_image"),
                resolved_source_dir,
                errors,
                "club.vpm_qr_image",
            )
    voting_qr_data = ""
    if "voting_qr" in support_components:
        if is_unresolved(meeting.get("voting_qr_image")):
            errors.append(
                "voting_qr component is selected but meeting.voting_qr_image is missing"
            )
        else:
            voting_qr_data = resolve_support_image(
                meeting.get("voting_qr_image"),
                resolved_source_dir,
                errors,
                "meeting.voting_qr_image",
            )
    theme_art_data = ""
    if not is_unresolved(meeting.get("theme_image")):
        theme_art_data = resolve_support_image(
            meeting.get("theme_image"),
            resolved_source_dir,
            errors,
            "meeting.theme_image",
        )

    try:
        start = parse_clock(meeting.get("start"))
    except ValueError as exc:
        errors.append(str(exc))
        start = 0
    if is_unresolved(meeting.get("end")):
        declared_end = start + 120
        meeting["end"] = format_clock(declared_end)
    else:
        try:
            declared_end = parse_clock(meeting.get("end"))
            if declared_end == start:
                errors.append("meeting.end must differ from meeting.start")
                declared_end = start + 120
            elif declared_end < start:
                declared_end += 24 * 60
        except ValueError as exc:
            errors.append(str(exc))
            declared_end = start + 120
    declared_window = declared_end - start
    if declared_window > 360:
        errors.append(
            f"meeting window is {format_minutes(declared_window)} minutes; "
            "use a window of 360 minutes or less"
        )
    if declared_window != 120:
        warnings.append(
            f"current meeting window is {format_minutes(declared_window)} minutes, "
            "not the 120-minute default"
        )

    approved_overtime = nonnegative_minutes(
        meeting.get("approved_overtime_minutes", 0)
    )
    if approved_overtime is None:
        errors.append(
            "meeting.approved_overtime_minutes must be nonnegative "
            "in 0.5-minute increments"
        )
        approved_overtime = 0
    role_order, roles = parse_roles(normalized.get("roles"), errors)
    backstage = parse_backstage(normalized.get("backstage"), errors)
    overrides = parse_overrides(normalized.get("standard_overrides"), errors)
    agenda_overrides = parse_agenda_overrides(
        normalized.get("agenda_overrides"), errors
    )
    transition_overrides = parse_transition_overrides(
        normalized.get("transition_overrides"), errors
    )
    items = build_items(
        normalized,
        language,
        meeting,
        role_order,
        roles,
        backstage,
        overrides,
        errors,
    )
    items = apply_agenda_overrides(
        items,
        agenda_overrides,
        overrides,
        errors,
    )
    attach_transition_overrides(items, transition_overrides, errors)
    layout = select_layout(meeting, items, errors)
    feature_item_id = select_feature_item(meeting, items, layout, errors)
    visual_theme = select_visual_theme(meeting, items, errors)
    validate_owners(items, errors)
    transition_minutes = apply_transitions(items, errors)
    target_item_minutes = declared_window - transition_minutes
    solved = solve_flexible(items, target_item_minutes)
    if not solved:
        fill_flexible_preferences(items)

    total_item_minutes = minutes_from_ticks(
        sum(minute_ticks(item["duration"]) for item in items)
    )
    total_minutes = minutes_from_ticks(
        minute_ticks(total_item_minutes) + minute_ticks(transition_minutes)
    )
    delta = minutes_from_ticks(
        minute_ticks(total_minutes) - minute_ticks(declared_window)
    )
    if delta > 0:
        if approved_overtime != delta:
            errors.append(
                "timeline overruns the declared meeting window by "
                f"{format_minutes(delta)} minutes; approved_overtime_minutes is "
                f"{format_minutes(approved_overtime)}. Ask the user to approve exactly "
                f"{format_minutes(delta)} minutes or reduce content"
            )
    elif delta < 0:
        errors.append(
            f"timeline has {format_minutes(abs(delta))} unexplained minutes remaining; "
            "adjust the flexible sessions or add an explicit buffer"
        )
    elif approved_overtime > 0:
        errors.append(
            "approved_overtime_minutes no longer matches a current overrun; reset it to 0 and "
            "reconfirm any later overrun"
        )

    final_cursor = assign_timeline(items, start)
    validate_role_relationships(items, warnings)
    validate_auto_flexible_durations(items, warnings)
    effective_window = minutes_from_ticks(
        minute_ticks(declared_window) + minute_ticks(approved_overtime)
    )
    page_item_limit = 36 if layout == "marathon" else 30 if layout == "standard" else 28
    if len(items) > page_item_limit:
        errors.append(
            f"single-page A4 capacity exceeded: {len(items)} agenda rows; "
            f"reduce or combine content to {page_item_limit} rows or fewer"
        )
    estimated_page_count = 1

    computed = {
        "status": (
            "exact_with_approved_overtime"
            if delta > 0 and approved_overtime == delta and not errors
            else "exact"
            if delta == 0 and not errors
            else "needs_confirmation"
        ),
        "declared_window_minutes": declared_window,
        "approved_overtime_minutes": approved_overtime,
        "effective_window_minutes": effective_window,
        "item_minutes": total_item_minutes,
        "transition_minutes": transition_minutes,
        "total_minutes": total_minutes,
        "delta_minutes": delta,
        "start": format_clock(start),
        "declared_end": format_clock(declared_end),
        "final_end": format_clock(final_cursor),
        "row_count": len(items),
        "page_count": estimated_page_count,
        "layout": layout,
        "feature_item": feature_item_id,
        "visual_theme": visual_theme,
    }

    result = {
        "schema_version": 2,
        "club": {
            "name": str(club.get("name", "")).strip(),
            "default_location": str(club.get("default_location", "")).strip(),
            "language": language,
            "support_components": support_components,
            "officers": officers,
            "club_intro": club_intro,
            "join_info": join_info,
            "vpm_qr_present": bool(vpm_qr_data),
        },
        "meeting": {
            key: meeting.get(key)
            for key in (
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
                "visual_preferences",
            )
            if key in meeting
        },
        "timeline": items,
        "backstage": backstage,
        "computed": computed,
        "warnings": warnings,
        "support_components": support_components,
        "custom_support_blocks": custom_support_blocks,
        "layout": layout,
        "feature_item": feature_item_id,
        "visual_theme": visual_theme,
        "visual_preferences": visual_preferences,
        "agenda_overrides": list(agenda_overrides.values()),
        "_assets": {
            "vpm_qr_data_uri": vpm_qr_data,
            "voting_qr_data_uri": voting_qr_data,
            "theme_art_data_uri": theme_art_data,
        },
    }
    result["meeting"]["voting_qr_present"] = bool(voting_qr_data)
    return result, errors, warnings


def render_markdown(result: dict[str, Any]) -> str:
    club = result["club"]
    meeting = result["meeting"]
    computed = result["computed"]
    language = club["language"]
    if language == "en":
        title = f"# {club['name']} · Meeting {meeting.get('number', '')} Agenda"
        labels = {
            "theme": "Theme",
            "date": "Date",
            "time": "Time",
            "location": "Location",
            "word": "Word of the Day",
            "manager": "Meeting Manager",
            "time_col": "Time",
            "agenda": "Agenda",
            "owner": "Role Taker",
            "duration": "Duration",
            "backstage": "Backstage Team",
            "summary": "Time check",
        }
    elif language == "bilingual":
        title = f"# {club['name']} · 第 {meeting.get('number', '')} 期 / Meeting {meeting.get('number', '')} Agenda"
        labels = {
            "theme": "主题 / Theme",
            "date": "日期 / Date",
            "time": "时间 / Time",
            "location": "地点 / Location",
            "word": "今日一词 / Word of the Day",
            "manager": "会议经理 / Meeting Manager",
            "time_col": "时间 / Time",
            "agenda": "会议流程 / Agenda",
            "owner": "负责人 / Role Taker",
            "duration": "时长 / Duration",
            "backstage": "幕后团队 / Backstage Team",
            "summary": "时间校验 / Time check",
        }
    else:
        title = f"# {club['name']} · 第 {meeting.get('number', '')} 期会单"
        labels = {
            "theme": "主题",
            "date": "日期",
            "time": "时间",
            "location": "地点",
            "word": "今日一词",
            "manager": "会议经理",
            "time_col": "时间",
            "agenda": "会议流程",
            "owner": "负责人",
            "duration": "时长",
            "backstage": "幕后团队",
            "summary": "时间校验",
        }

    lines = [title, ""]
    metadata = [
        (labels["theme"], meeting.get("theme")),
        (labels["date"], meeting.get("date")),
        (labels["time"], f"{computed['start']}-{computed['final_end']}"),
        (labels["location"], meeting.get("location")),
        (labels["word"], meeting.get("word_of_day")),
        (labels["manager"], meeting.get("manager")),
    ]
    for label, value in metadata:
        if not is_unresolved(value):
            lines.append(f"- {label}：{value}")
    lines.extend(
        [
            "",
            f"| {labels['time_col']} | {labels['agenda']} | {labels['owner']} | {labels['duration']} |",
            "|---|---|---|---:|",
        ]
    )
    last_section = None
    for item in result["timeline"]:
        current_section = section_label(item["section"], language)
        if current_section != last_section:
            lines.append(f"|  | **{current_section}** |  |  |")
            last_section = current_section
        details = "<br>".join(item.get("details", []))
        activity = item["label"] + (f"<br><small>{details}</small>" if details else "")
        lines.append(
            f"| {item['start']}-{item['end']} | {activity} | {item['owner']} | "
            f"{format_minutes(item['duration'])} min |"
        )
    lines.extend(
        [
            "",
            f"**{labels['summary']}：** {format_minutes(computed['item_minutes'])} min + "
            f"{format_minutes(computed['transition_minutes'])} min transitions = "
            f"{format_minutes(computed['total_minutes'])} min；"
            f"{computed['start']}-{computed['final_end']}。",
        ]
    )
    if result["backstage"]:
        backstage_text = " · ".join(
            f"{row['label']}：{row['person']}" for row in result["backstage"]
        )
        lines.extend(["", f"**{labels['backstage']}：** {backstage_text}"])
    support_components = result.get("support_components", [])
    custom_support_blocks = result.get("custom_support_blocks", [])
    if support_components or custom_support_blocks:
        lines.extend(
            [
                "",
                f"## {localized('固定信息组件', 'Support Components', language)}",
            ]
        )
    if "timer_rules" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('时间官规则', 'Timer Rules', language)}",
                "",
                f"| {localized('演讲时长', 'Speech length', language)} | "
                f"{localized('绿牌', 'Green', language)} | "
                f"{localized('黄牌', 'Yellow', language)} | "
                f"{localized('红牌', 'Red', language)} | "
                f"{localized('响铃', 'Bell', language)} |",
                "|---|---|---|---|---|",
            ]
        )
        for row in TIMER_RULES:
            lines.append(
                f"| {localized(row['band_zh'], row['band_en'], language)} | "
                f"{localized(row['green_zh'], row['green_en'], language)} | "
                f"{localized(row['yellow_zh'], row['yellow_en'], language)} | "
                f"{localized(row['red_zh'], row['red_en'], language)} | "
                f"{localized(row['bell_zh'], row['bell_en'], language)} |"
            )
    if "toastmasters_intro" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('头马国际演讲会', 'Toastmasters International', language)}",
                "",
                toastmasters_intro(language),
            ]
        )
    if "meeting_boundaries" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('会议秩序与内容边界', 'Meeting Conduct & Content Boundaries', language)}",
                "",
                f"- {localized('安静：会议过程中保持安静，手机调至静音或震动。', 'Quiet: keep phones silent or on vibrate during the meeting.', language)}",
                f"- {localized('四类禁忌：演讲不涉及政治、宗教、色情或传销。', 'Four boundaries: avoid politics, religion, pornography and pyramid selling.', language)}",
                f"- {localized('整洁：结束后带走个人物品与垃圾。', 'Clean: take personal belongings and rubbish when leaving.', language)}",
            ]
        )
    if "officers" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('当届官员团队', 'Current Officer Team', language)}",
                "",
                f"| {localized('职务', 'Role', language)} | {localized('姓名', 'Name', language)} |",
                "|---|---|",
            ]
        )
        for officer in result["club"]["officers"]:
            lines.append(f"| {officer['role']} | {officer['name']} |")
    if "club_intro" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('俱乐部介绍', 'About the Club', language)}",
                "",
                *[f"- {line}" for line in result["club"]["club_intro"]],
            ]
        )
    if "join_info" in support_components:
        lines.extend(
            [
                "",
                f"### {localized('如何入会', 'How to Join', language)}",
                "",
                *[f"- {line}" for line in result["club"]["join_info"]],
            ]
        )
    if "vpm_qr" in support_components:
        lines.extend(
            [
                "",
                f"- {localized('VPM 入会二维码：见会单信息区。', 'VPM joining QR: see the agenda information area.', language)}",
            ]
        )
    if "voting_qr" in support_components:
        lines.extend(
            [
                "",
                f"- {localized('本期投票二维码：见会单信息区。', 'Meeting voting QR: see the agenda information area.', language)}",
            ]
        )
    for block in custom_support_blocks:
        lines.extend(
            [
                "",
                f"### {block['title']}",
                "",
                *[f"- {line}" for line in block["lines"]],
            ]
        )
    return "\n".join(lines) + "\n"


def image_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"unsupported image format: {path.suffix}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def resolve_support_image(
    value: Any,
    source_dir: Path,
    errors: list[str],
    label: str,
) -> str:
    if is_unresolved(value):
        return ""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = source_dir / path
    path = path.resolve()
    if not path.is_file():
        errors.append(f"{label} does not exist: {path}")
        return ""
    try:
        return image_data_uri(path)
    except (OSError, ValueError) as exc:
        errors.append(f"{label}: {exc}")
        return ""


def render_html(result: dict[str, Any]) -> str:
    club = result["club"]
    meeting = result["meeting"]
    computed = result["computed"]
    language = club["language"]
    layout = result.get("layout", "standard")
    feature_item_id = result.get("feature_item")
    visual_theme = result.get("visual_theme", "general")
    visual_preferences = result.get("visual_preferences", {})
    text_size = str(visual_preferences.get("text_size", "standard"))
    feature_emphasis = str(
        visual_preferences.get("feature_emphasis", "standard")
    )
    owner_alignment = str(visual_preferences.get("owner_alignment", "default"))
    theme_art = result.get("_assets", {}).get("theme_art_data_uri", "")
    logo = image_data_uri(DEFAULT_LOGO)
    row_count = len(result["timeline"])
    timeline_pages = [result["timeline"]]
    support_components = result.get("support_components", [])
    custom_support_blocks = result.get("custom_support_blocks", [])
    has_support = bool(support_components or custom_support_blocks)
    density = "ultra" if row_count >= 22 else "compact" if row_count >= 18 else "normal"

    meta_parts = [
        str(meeting.get("date", "")).strip(),
        f"{computed['start']}-{computed['final_end']}",
        str(meeting.get("location", "")).strip(),
    ]
    meta = " · ".join(html.escape(part) for part in meta_parts if part)
    meeting_number = html.escape(str(meeting.get("number", "")))
    if language == "en":
        kicker = f"Meeting {meeting_number}"
    elif language == "bilingual":
        kicker = f"第 {meeting_number} 期 / Meeting {meeting_number}"
    else:
        kicker = f"第 {meeting_number} 期例会"
    theme = html.escape(str(meeting.get("theme", "")).strip())
    word = html.escape(str(meeting.get("word_of_day", "")).strip())
    manager = html.escape(str(meeting.get("manager", "")).strip())

    backstage = "  |  ".join(
        f"{html.escape(row['label'])}：{html.escape(row['person'])}"
        for row in result["backstage"]
    )
    backstage_rows = "".join(
        "<div>"
        f"<strong>{html.escape(row['label'])}</strong>"
        f"<span>{html.escape(row['person'])}</span>"
        "</div>"
        for row in result["backstage"]
    )
    if language == "en":
        backstage_label = "Backstage Team"
        time_label = "Time check"
        word_label = "Word of the Day"
        manager_label = "Meeting Manager"
        table_headers = ("Time", "Agenda", "Role Taker", "Duration")
    elif language == "bilingual":
        backstage_label = "幕后团队 / Backstage Team"
        time_label = "时间闭环 / Time check"
        word_label = "今日一词 / Word of the Day"
        manager_label = "会议经理 / Meeting Manager"
        table_headers = (
            "时间 / Time",
            "会议流程 / Agenda",
            "负责人 / Role Taker",
            "时长 / Duration",
        )
    else:
        backstage_label = "幕后团队"
        time_label = "时间闭环"
        word_label = "今日一词"
        manager_label = "会议经理"
        table_headers = ("时间", "会议流程", "负责人", "时长")
    website = "toastmasters.org"
    section_ranges: dict[str, dict[str, str]] = {}
    for item in result["timeline"]:
        section = item["section"]
        section_ranges.setdefault(section, {"start": item["start"], "end": item["end"]})
        section_ranges[section]["end"] = item["end"]

    def page_rows(page_items: list[dict[str, Any]]) -> str:
        rows: list[str] = []
        last_section = None
        for item in page_items:
            current_section = section_label(item["section"], language)
            if current_section != last_section:
                time_range = section_ranges[item["section"]]
                rows.append(
                    '<tr class="section-row"><td colspan="4">'
                    f'<div>{html.escape(current_section)}<span>({html.escape(time_range["start"])}-{html.escape(time_range["end"])})</span></div>'
                    "</td></tr>"
                )
                last_section = current_section
            details = " · ".join(html.escape(value) for value in item.get("details", []))
            detail_html = f'<div class="detail">{details}</div>' if details else ""
            if layout == "feature" and item["id"] == feature_item_id:
                feature_details = "".join(
                    f"<span>{html.escape(value)}</span>"
                    for value in item.get("details", [])
                )
                feature_details_html = (
                    f'<div class="feature-beats">{feature_details}</div>'
                    if feature_details
                    else ""
                )
                duration = format_minutes(item["duration"])
                rows.append(
                    f'<tr class="feature-highlight" data-minutes="{duration}">'
                    f'<td class="feature-time time">{html.escape(item["start"])}</td>'
                    '<td class="feature-copy activity">'
                    f'<strong>{html.escape(item["label"])}</strong>{feature_details_html}'
                    "</td>"
                    '<td class="feature-owner owner">'
                    f'<strong>{html.escape(item["owner"])}</strong>'
                    "</td>"
                    '<td class="feature-duration duration">'
                    f'<strong>{duration}</strong><span>min</span>'
                    "</td></tr>"
                )
                continue
            rows.append(
                f'<tr class="item-row type-{html.escape(item["type"])}">'
                f'<td class="time">{html.escape(item["start"])}</td>'
                f'<td class="activity">{html.escape(item["label"])}{detail_html}</td>'
                f'<td class="owner">{html.escape(item["owner"])}</td>'
                f'<td class="duration">{format_minutes(item["duration"])} min</td>'
                "</tr>"
            )
        return "".join(rows)

    def marathon_flow(page_items: list[dict[str, Any]]) -> str:
        speeches = [item for item in page_items if item["type"] == "prepared_speech"]
        evaluations = {
            item["id"].split(":", 1)[1]: item
            for item in page_items
            if item["type"] == "prepared_evaluation" and ":" in item["id"]
        }
        paired_ids = {item["id"] for item in speeches} | {
            item["id"] for item in evaluations.values()
        }
        remaining = [item for item in page_items if item["id"] not in paired_ids]

        section_order: list[str] = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in remaining:
            section = item["section"]
            if section not in grouped:
                section_order.append(section)
                grouped[section] = []
            grouped[section].append(item)

        def compact_section(section: str, items: list[dict[str, Any]]) -> str:
            cards = []
            for item in items:
                details = " / ".join(
                    html.escape(value) for value in item.get("details", [])
                )
                details_html = f"<small>{details}</small>" if details else ""
                cards.append(
                    f'<article class="marathon-item type-{html.escape(item["type"])}">'
                    f'<time>{html.escape(item["start"])}</time>'
                    '<div class="marathon-copy">'
                    f'<strong>{html.escape(item["label"])}</strong>{details_html}'
                    "</div>"
                    f'<div class="marathon-owner">{html.escape(item["owner"])}</div>'
                    f'<div class="marathon-duration">{format_minutes(item["duration"])} min</div>'
                    "</article>"
                )
            start = items[0]["start"]
            end = items[-1]["end"]
            return (
                f'<section class="marathon-section section-{html.escape(section)}">'
                '<header>'
                f'<strong>{html.escape(section_label(section, language))}</strong>'
                f'<span>{html.escape(start)}-{html.escape(end)}</span>'
                "</header>"
                f'<div class="marathon-cards">{"".join(cards)}</div>'
                "</section>"
            )

        blocks: list[str] = []
        if "opening" in grouped:
            blocks.append(compact_section("opening", grouped.pop("opening")))
            section_order.remove("opening")

        if speeches:
            pair_cards: list[str] = []
            pair_end = speeches[-1]["end"]
            for index, speech in enumerate(speeches, start=1):
                suffix = speech["id"].split(":", 1)[1]
                evaluation = evaluations.get(suffix)
                speech_details = " / ".join(
                    html.escape(value) for value in speech.get("details", [])
                )
                evaluation_html = (
                    '<div class="pair-evaluation">'
                    f'<time>{html.escape(evaluation["start"])}</time>'
                    f'<span>{html.escape(localized("点评", "Evaluation", language))}</span>'
                    f'<strong>{html.escape(evaluation["owner"])}</strong>'
                    f'<small>{format_minutes(evaluation["duration"])} min</small>'
                    "</div>"
                    if evaluation
                    else '<div class="pair-evaluation missing">-</div>'
                )
                if evaluation:
                    pair_end = evaluation["end"]
                pair_cards.append(
                    '<article class="speech-pair">'
                    f'<div class="pair-number">{index}</div>'
                    '<div class="pair-speech">'
                    f'<time>{html.escape(speech["start"])}</time>'
                    f'<strong>{html.escape(speech["label"])}</strong>'
                    f'<small>{speech_details}</small>'
                    f'<span>{html.escape(speech["owner"])}</span>'
                    f'<b>{format_minutes(speech["duration"])} min</b>'
                    "</div>"
                    f"{evaluation_html}"
                    "</article>"
                )
            blocks.append(
                '<section class="marathon-section paired-section">'
                '<header>'
                f'<strong>{html.escape(localized("演讲与点评", "Speeches & Evaluations", language))}</strong>'
                f'<span>{html.escape(speeches[0]["start"])}-{html.escape(pair_end)}</span>'
                "</header>"
                f'<div class="speech-pair-grid">{"".join(pair_cards)}</div>'
                "</section>"
            )

        for section in section_order:
            if grouped.get(section):
                blocks.append(compact_section(section, grouped[section]))
        return f'<div class="marathon-flow">{"".join(blocks)}</div>'

    page_blocks: list[str] = []
    total_pages = 1
    for page_index, page_items in enumerate(timeline_pages, start=1):
        page_marker = f"{page_index}/{total_pages}"
        sparse_class = " sparse-page" if len(page_items) < 12 else ""
        mode_class = " with-support" if has_support else " no-support"
        theme_art_class = " has-theme-art" if theme_art else ""
        timeline_markup = (
            marathon_flow(page_items)
            if layout == "marathon"
            else "<table>"
            f"<thead><tr><th>{table_headers[0]}</th><th>{table_headers[1]}</th><th>{table_headers[2]}</th><th>{table_headers[3]}</th></tr></thead>"
            f"<tbody>{page_rows(page_items)}</tbody>"
            "</table>"
        )
        page_blocks.append(
            f"""
<main class="page {density} lang-{html.escape(language)}{sparse_class}{mode_class}{theme_art_class} layout-{html.escape(layout)} visual-{html.escape(visual_theme)} text-size-{html.escape(text_size)} feature-emphasis-{html.escape(feature_emphasis)} owner-align-{html.escape(owner_alignment)}">
  <div class="brand-ribbon" aria-hidden="true"><span></span><span></span><span></span></div>
  <header class="masthead">
    {"<img class='logo' src='" + logo + "' alt='Toastmasters International'>" if logo else "<div class='logo-fallback'>TOASTMASTERS<br>INTERNATIONAL</div>"}
    {"<img class='theme-art' src='" + html.escape(theme_art, quote=True) + "' alt=''>" if theme_art else ""}
    <div class="title-block">
      <div class="kicker">{kicker}</div>
      <h1>{html.escape(club['name'])} {html.escape(localized('例会议程', 'Meeting Agenda', language))}</h1>
      <div class="theme-line"><span></span><strong>{theme or html.escape(localized('本期例会', 'Club Meeting', language))}</strong><span></span></div>
    </div>
  </header>
  <section class="meta-strip">
    <div class="meta-cell"><b>{html.escape(localized('日期', 'Date', language))}</b><span>{html.escape(str(meeting.get('date', '')).strip()) or '-'}</span></div>
    <div class="meta-cell"><b>{html.escape(localized('时间', 'Time', language))}</b><span>{computed['start']}-{computed['final_end']}</span></div>
    <div class="meta-cell location-cell"><b>{html.escape(localized('地点', 'Location', language))}</b><span>{html.escape(str(meeting.get('location', '')).strip()) or '-'}</span></div>
    <div class="meta-cell"><b>{word_label}</b><span class="word-value">{word or '-'}</span></div>
    <div class="meta-cell"><b>{manager_label}</b><span>{manager or '-'}</span></div>
  </section>
  <section class="backstage-strip"><strong>{backstage_label}</strong><span>{backstage or '-'}</span></section>
  <section class="main-grid">
    <aside class="left-rail">
      <article class="module backstage-module">
        <h2>{backstage_label}</h2>
        <div class="backstage-list">{backstage_rows or '<div><span>-</span></div>'}</div>
      </article>
      <!-- LEFT_SUPPORT_SLOT -->
    </aside>
    <section class="timeline-panel">
      <h2>{html.escape(localized('会议流程', 'Meeting Flow', language))}<span>{computed['start']}-{computed['final_end']}</span></h2>
      <div class="timeline">
        {timeline_markup}
      </div>
    </section>
  </section>
  <section class="bottom-grid"><!-- BOTTOM_SUPPORT_SLOT --></section>
  <footer class="footer">
    <div class="footer-club">{html.escape(club['name'])}</div>
    <div class="timecheck"><strong>{time_label}</strong> · {format_minutes(computed['item_minutes'])} + {format_minutes(computed['transition_minutes'])} = {format_minutes(computed['total_minutes'])} min</div>
    <div class="site">{website} · {page_marker}</div>
  </footer>
</main>"""
        )

    if has_support:
        support_cards: dict[str, str] = {}

        def support_card(
            card_key: str, title: str, body: str, wide: bool = False
        ) -> str:
            safe_key = re.sub(r"[^a-z0-9_-]+", "-", card_key.lower()).strip("-")
            card_class = f"support-card component-{safe_key}"
            if wide:
                card_class += " wide"
            return (
                f'<article class="module {card_class}">'
                f'<h2>{html.escape(title)}</h2>{body}</article>'
            )

        for component in support_components:
            if component in {"vpm_qr", "voting_qr"}:
                continue
            if component == "timer_rules":
                timer_rows = []
                for row in TIMER_RULES:
                    timer_rows.append(
                        '<div class="timer-rule">'
                        f"<strong>{html.escape(localized(row['band_zh'], row['band_en'], language))}</strong>"
                        f'<span class="green">● {html.escape(localized(row["green_zh"], row["green_en"], language))}</span>'
                        f'<span class="yellow">● {html.escape(localized(row["yellow_zh"], row["yellow_en"], language))}</span>'
                        f'<span class="red">● {html.escape(localized(row["red_zh"], row["red_en"], language))}</span>'
                        f"<small>{html.escape(localized(row['bell_zh'], row['bell_en'], language))}</small>"
                        "</div>"
                    )
                timer_body = f'<div class="timer-rules">{"".join(timer_rows)}</div>'
                support_cards[component] = support_card(
                    component,
                    localized("时间官规则", "Timer Rules", language),
                    timer_body,
                )
            elif component == "toastmasters_intro":
                support_cards[component] = support_card(
                    component,
                    localized(
                        "头马国际演讲会",
                        "Toastmasters International",
                        language,
                    ),
                    f"<p>{html.escape(toastmasters_intro(language))}</p>",
                )
            elif component == "meeting_boundaries":
                boundaries = meeting_boundaries(language)
                support_cards[component] = support_card(
                    component,
                    localized(
                        "会议秩序与内容边界",
                        "Meeting Conduct & Content Boundaries",
                        language,
                    ),
                    "<ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in boundaries) + "</ul>",
                )
            elif component == "officers":
                officer_rows = "".join(
                    f"<div><strong>{html.escape(row['role'])}</strong><span>{html.escape(row['name'])}</span></div>"
                    for row in club["officers"]
                )
                support_cards[component] = support_card(
                    component,
                    localized("当届官员团队", "Current Officer Team", language),
                    f'<div class="officer-list">{officer_rows}</div>',
                )
            elif component == "club_intro":
                support_cards[component] = support_card(
                    component,
                    localized("俱乐部介绍", "About the Club", language),
                    "<ul>"
                    + "".join(
                        f"<li>{html.escape(line)}</li>" for line in club["club_intro"]
                    )
                    + "</ul>",
                )
            elif component == "join_info":
                support_cards[component] = support_card(
                    component,
                    localized("如何入会", "How to Join", language),
                    "<ul>"
                    + "".join(
                        f"<li>{html.escape(line)}</li>" for line in club["join_info"]
                    )
                    + "</ul>",
                )

        qr_items: list[str] = []
        assets = result.get("_assets", {})
        if "vpm_qr" in support_components:
            qr_items.append(
                '<div class="qr-item">'
                f'<img src="{html.escape(assets.get("vpm_qr_data_uri", ""), quote=True)}" alt="VPM QR">'
                f"<strong>{html.escape(localized('入会咨询', 'Join Us', language))}</strong>"
                "</div>"
            )
        if "voting_qr" in support_components:
            qr_items.append(
                '<div class="qr-item">'
                f'<img src="{html.escape(assets.get("voting_qr_data_uri", ""), quote=True)}" alt="Voting QR">'
                f"<strong>{html.escape(localized('本期投票', 'Meeting Vote', language))}</strong>"
                "</div>"
            )
        if qr_items:
            support_cards["qr_codes"] = support_card(
                "qr_codes",
                localized("二维码", "QR Codes", language),
                f'<div class="qr-grid">{"".join(qr_items)}</div>',
                wide=True,
            )

        custom_placements: dict[str, str] = {}
        custom_weights: dict[str, int] = {}
        custom_keys: list[str] = []
        for block in custom_support_blocks:
            key = f"custom:{block['id']}"
            support_cards[key] = support_card(
                key,
                block["title"],
                "<ul>"
                + "".join(f"<li>{html.escape(line)}</li>" for line in block["lines"])
                + "</ul>",
            )
            custom_placements[key] = block["placement"]
            text_units = sum(len(line) for line in block["lines"]) // 55
            custom_weights[key] = min(8, max(2, 1 + len(block["lines"]) + text_units))
            custom_keys.append(key)

        built_in_sequence = [
            key
            for key in (
                "timer_rules",
                "officers",
                "toastmasters_intro",
                "meeting_boundaries",
                "club_intro",
                "join_info",
                "qr_codes",
            )
            if key in support_cards
        ]
        placement = {
            "timer_rules": "left",
            "officers": "left",
            "toastmasters_intro": "auto",
            "meeting_boundaries": "auto",
            "club_intro": "bottom",
            "join_info": "bottom",
            "qr_codes": "bottom",
            **custom_placements,
        }
        weight = {
            "timer_rules": 6,
            "officers": 5,
            "toastmasters_intro": 3,
            "meeting_boundaries": 4,
            "club_intro": 3,
            "join_info": 2,
            "qr_codes": 5,
            **custom_weights,
        }
        left_capacity = 23
        left_weight = 3
        left_keys: list[str] = []
        bottom_keys: list[str] = []
        all_keys = [*built_in_sequence, *custom_keys]
        if layout == "marathon":
            bottom_keys = all_keys
        else:
            for key in all_keys:
                preferred = placement.get(key, "auto")
                if preferred == "left":
                    left_keys.append(key)
                    left_weight += weight.get(key, 3)
                elif preferred == "bottom":
                    bottom_keys.append(key)
                elif left_weight + weight.get(key, 3) <= left_capacity:
                    left_keys.append(key)
                    left_weight += weight.get(key, 3)
                else:
                    bottom_keys.append(key)

        left_html = "".join(support_cards[key] for key in left_keys)
        bottom_html = "".join(support_cards[key] for key in bottom_keys)
        bottom_count = len(bottom_keys)
        page_blocks[0] = page_blocks[0].replace("<!-- LEFT_SUPPORT_SLOT -->", left_html)
        page_blocks[0] = page_blocks[0].replace(
            "<!-- BOTTOM_SUPPORT_SLOT -->", bottom_html
        )
        page_blocks[0] = page_blocks[0].replace(
            'class="bottom-grid"', f'class="bottom-grid count-{bottom_count}"'
        )
    else:
        page_blocks[0] = page_blocks[0].replace("<!-- LEFT_SUPPORT_SLOT -->", "")
        page_blocks[0] = page_blocks[0].replace("<!-- BOTTOM_SUPPORT_SLOT -->", "")

    return f"""<!doctype html>
<html lang="{html.escape(language)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="agenda-page-count" content="{total_pages}">
<meta name="agenda-visual-audit" content="required">
<title>{html.escape(club['name'])} · {kicker}</title>
<style>
@page {{ size: A4 portrait; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #e8edf0; color: #15344a; font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }}
.page {{ position: relative; width: 210mm; min-height: 297mm; height: auto; margin: 0 auto; overflow: visible; background: #fff; color: #092f50; padding: 5mm 6mm 4mm; display: flex; flex-direction: column; }}
.logo {{ object-fit: contain; }}
.logo-fallback {{ width: 18mm; height: 18mm; border: .35mm solid #004165; color: #004165; border-radius: 50%; display: grid; place-items: center; font-weight: 800; font-size: 7px; text-align: center; }}
.kicker {{ margin-top: 1mm; color: #F2DF74; font-size: 3.1mm; font-weight: 800; }}
.timeline {{ flex: 1; min-height: 0; border: .35mm solid #d5dde1; border-radius: 2mm; overflow: visible; background: white; }}
table {{ width: 100%; height: 100%; border-collapse: collapse; table-layout: fixed; }}
.sparse-page table {{ height: auto; }}
thead th {{ background: #772432; color: white; font-size: 2.6mm; padding: 1.1mm 1.2mm; text-align: left; }}
thead th:nth-child(1) {{ width: 20mm; }}
thead th:nth-child(3) {{ width: 32mm; }}
thead th:nth-child(4) {{ width: 18mm; text-align: right; }}
tbody td {{ border-bottom: .22mm solid #dfe5e8; padding: .9mm 1.2mm; font-size: 2.5mm; line-height: 1.12; vertical-align: middle; }}
tbody tr:last-child td {{ border-bottom: 0; }}
.section-row td {{ background: #eaf1f4; color: #004165; font-weight: 900; padding: .7mm 1.2mm; font-size: 2.3mm; letter-spacing: .15mm; }}
.time {{ color: #b17b00; font-weight: 900; }}
.activity {{ font-weight: 750; }}
.detail {{ margin-top: .3mm; color: #62727d; font-size: 1.95mm; font-weight: 400; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.owner {{ color: #004165; font-weight: 700; text-align: left; }}
.duration {{ text-align: right; color: #5a6670; white-space: nowrap; }}
.owner-align-left thead th:nth-child(3),
.owner-align-left tbody td.owner {{ text-align: left; }}
.owner-align-center thead th:nth-child(3),
.owner-align-center tbody td.owner {{ text-align: center; }}
.footer {{ margin-top: 2mm; background: #004165; color: white; border-radius: 2mm; padding: 1.8mm 2.4mm; display: grid; grid-template-columns: minmax(0,1.7fr) minmax(0,1fr) auto; gap: 2mm; align-items: center; font-size: 2.3mm; }}
.footer strong {{ color: #F2DF74; }}
.backstage {{ white-space: normal; overflow: visible; line-height: 1.18; }}
.timecheck {{ white-space: nowrap; }}
.site {{ color: #F2DF74; font-weight: 800; }}
.lang-bilingual .footer {{ font-size: 1.95mm; }}
.support-card {{ border: .25mm solid #d5dde1; border-radius: 1.5mm; background: white; padding: 1.7mm; font-size: 2.1mm; line-height: 1.22; }}
.support-card h2 {{ margin: 0 0 .8mm; color: #772432; font-size: 2.8mm; line-height: 1.1; }}
.support-card p {{ margin: 0; }}
.support-card ul {{ margin: 0; padding-left: 3.2mm; }}
.support-card li + li {{ margin-top: .35mm; }}
.timer-rules {{ display: grid; gap: .7mm; }}
.timer-rule {{ display: grid; gap: .2mm; padding-bottom: .55mm; border-bottom: .18mm solid #e5eaed; }}
.timer-rule:last-child {{ padding-bottom: 0; border-bottom: 0; }}
.timer-rule strong {{ color: #004165; }}
.timer-rule span, .timer-rule small {{ font-size: 1.85mm; }}
.timer-rule .green {{ color: #18764a; }}
.timer-rule .yellow {{ color: #a56f00; }}
.timer-rule .red {{ color: #a12832; }}
.timer-rule small {{ color: #5a6670; }}
.officer-list {{ display: grid; gap: .35mm; }}
.officer-list div {{ display: grid; grid-template-columns: 1fr 1.05fr; gap: 1mm; padding-bottom: .3mm; border-bottom: .15mm solid #e5eaed; }}
.officer-list div:last-child {{ border-bottom: 0; }}
.officer-list span {{ color: #004165; font-weight: 700; }}
.qr-grid {{ display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); justify-items: center; gap: 1.5mm; }}
.qr-item {{ display: grid; justify-items: center; gap: .6mm; color: #004165; text-align: center; }}
.qr-item img {{ width: 23mm; height: 23mm; object-fit: contain; image-rendering: auto; }}
.lang-bilingual .support-card {{ font-size: 1.8mm; }}
.lang-bilingual .support-card h2 {{ font-size: 2.4mm; }}

/* A4 editorial agenda layout: brand masthead, operational rail, primary timeline. */
.brand-ribbon {{ height: 3mm; display: grid; grid-template-columns: 34mm 24mm 26mm 1fr; gap: 2mm; margin: -5mm -6mm 1.5mm; overflow: hidden; }}
.brand-ribbon span:nth-child(1), .brand-ribbon span:nth-child(4) {{ background: #004165; }}
.brand-ribbon span:nth-child(2) {{ background: #f2c94c; transform: skewX(-35deg); }}
.brand-ribbon span:nth-child(3) {{ background: #a6192e; transform: skewX(-35deg); }}
.masthead {{ position: relative; min-height: 31mm; display: grid; grid-template-columns: 33mm 1fr; gap: 5mm; align-items: center; padding: 1mm 5mm 2.5mm; overflow: hidden; border-bottom: .45mm solid #c89524; }}
.masthead::before {{ content: ""; position: absolute; left: -30mm; top: -31mm; width: 74mm; height: 54mm; border: 2.2mm solid #004165; border-radius: 50%; opacity: .9; pointer-events: none; }}
.masthead .logo {{ position: relative; z-index: 1; width: 29mm; height: 29mm; }}
.title-block {{ position: relative; z-index: 1; min-width: 0; text-align: center; }}
.title-block .kicker {{ margin: 0 0 .8mm; color: #9b6a00; font-size: 2.6mm; letter-spacing: .35mm; }}
.title-block h1 {{ margin: 0; color: #07366a; font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; font-size: 7.2mm; font-weight: 800; line-height: 1.05; letter-spacing: .05mm; text-wrap: balance; }}
.theme-line {{ margin-top: 1.8mm; display: grid; grid-template-columns: minmax(15mm,1fr) auto minmax(15mm,1fr); gap: 3mm; align-items: center; color: #b47b00; font-size: 4.2mm; }}
.theme-line span {{ height: .35mm; background: #c89524; }}
.theme-line strong {{ max-width: 105mm; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.meta-strip {{ display: grid; grid-template-columns: 1fr 1fr 1.45fr 1fr 1fr; border-top: .35mm solid #d5a42e; border-bottom: .35mm solid #d5a42e; margin: 2.3mm 0; }}
.meta-cell {{ min-width: 0; min-height: 13mm; padding: 1.6mm 2.2mm; display: grid; align-content: center; gap: .8mm; border-right: .22mm solid #8aa0b5; font-size: 2.35mm; }}
.meta-cell:last-child {{ border-right: 0; }}
.meta-cell b {{ color: #07366a; font-size: 2.4mm; }}
.meta-cell span {{ color: #1d2730; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.meta-cell .word-value {{ color: #b47b00; font-size: 3.8mm; font-weight: 800; }}
.main-grid {{ flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(51mm,.31fr) minmax(0,.69fr); gap: 2.4mm; align-items: stretch; }}
.backstage-strip {{ display: none; min-height: 8mm; margin-bottom: 1.8mm; padding: 1.4mm 2mm; border: .3mm solid #174f7f; border-left: 2mm solid #d6a329; align-items: center; gap: 3mm; font-size: 2.25mm; }}
.backstage-strip strong {{ color: #004165; }}
.no-support .backstage-strip {{ display: flex; }}
.no-support .main-grid {{ grid-template-columns: minmax(0,1fr); }}
.no-support .left-rail {{ display: none; }}
.left-rail {{ min-width: 0; display: flex; flex-direction: column; gap: 1.7mm; }}
.module {{ border: .3mm solid #174f7f; border-radius: 1.2mm; background: #fff; padding: 1.5mm; font-size: 2.15mm; line-height: 1.28; overflow: hidden; }}
.module h2 {{ margin: -1.5mm -1.5mm 1.2mm; padding: 1mm 1.5mm; background: #004165; border-bottom: .5mm solid #d6a329; color: white; font-size: 2.8mm; line-height: 1.05; letter-spacing: .08mm; }}
.backstage-list {{ display: grid; }}
.backstage-list > div {{ min-height: 5.6mm; display: grid; grid-template-columns: 1.2fr 1fr; align-items: center; gap: 1mm; padding: .7mm .5mm; border-bottom: .18mm solid #c9d5df; }}
.backstage-list > div:last-child {{ border-bottom: 0; }}
.backstage-list strong {{ color: #0b3f6b; }}
.timeline-panel {{ min-width: 0; display: flex; flex-direction: column; border: .32mm solid #174f7f; border-radius: 1.2mm; overflow: hidden; background: white; }}
.timeline-panel > h2 {{ margin: 0; min-height: 7mm; display: flex; justify-content: space-between; align-items: center; gap: 3mm; padding: 1.2mm 2mm; background: #004165; border-bottom: .5mm solid #d6a329; color: white; font-size: 3.2mm; }}
.timeline-panel > h2 span {{ color: #f2df74; font-size: 2.3mm; font-variant-numeric: tabular-nums; }}
.timeline {{ flex: 1; border: 0; border-radius: 0; }}
.timeline table {{ height: 100%; }}
.timeline thead th {{ background: #073e70; color: white; padding: .8mm 1mm; font-size: 2.2mm; }}
.timeline thead th:nth-child(1) {{ width: 18mm; }}
.timeline thead th:nth-child(3) {{ width: 28mm; }}
.timeline thead th:nth-child(4) {{ width: 15mm; }}
.timeline tbody td {{ padding: .55mm 1mm; font-size: 2.2mm; line-height: 1.08; }}
.timeline .section-row td {{ padding: .7mm 1mm; background: #edf4f8; color: #073e70; font-size: 2.35mm; text-align: center; }}
.timeline .section-row td > div {{ display: flex; justify-content: center; align-items: baseline; gap: 1.2mm; }}
.timeline .section-row span {{ font-size: 2mm; font-weight: 700; }}
.timeline .detail {{ font-size: 1.85mm; }}
.timeline .type-special .activity,
.timeline .type-special .owner,
.timeline .type-special .duration {{ color: #772432; font-weight: 800; }}
.timer-rules {{ gap: .8mm; }}
.timer-rule {{ padding: .25mm .4mm .65mm; }}
.timer-rule strong {{ font-size: 2.2mm; }}
.timer-rule span, .timer-rule small {{ font-size: 1.9mm; }}
.officer-list div {{ min-height: 4mm; align-items: center; font-size: 1.95mm; }}
.qr-item img {{ width: 19mm; height: 19mm; }}
.bottom-grid {{ margin-top: 1.8mm; display: grid; grid-template-columns: repeat(auto-fit,minmax(40mm,1fr)); gap: 1.8mm; }}
.bottom-grid:empty {{ display: none; }}
.bottom-grid.count-1 {{ grid-template-columns: 1fr; }}
.bottom-grid.count-2 {{ grid-template-columns: repeat(2,minmax(0,1fr)); }}
.bottom-grid.count-3 {{ grid-template-columns: repeat(3,minmax(0,1fr)); }}
.bottom-grid.count-4 {{ grid-template-columns: repeat(4,minmax(0,1fr)); }}
.bottom-grid .module {{ min-height: 18mm; font-size: 1.95mm; }}
.bottom-grid .module h2 {{ font-size: 2.55mm; }}
.footer {{ margin-top: 1.8mm; min-height: 10mm; border-radius: 0; padding: 1.8mm 3mm; background: #003b70; border-bottom: 1.1mm solid #c89524; font-size: 2.25mm; }}
.footer-club {{ color: #f2df74; font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif; font-weight: 800; font-size: 3mm; }}
.lang-bilingual .title-block h1 {{ font-size: 6.2mm; }}
.lang-bilingual .meta-cell {{ font-size: 1.95mm; }}
.lang-bilingual .timeline tbody td {{ font-size: 1.95mm; }}
.lang-bilingual .module {{ font-size: 2.1mm; }}
.page {{ --theme-accent: #c89524; --theme-soft: #edf4f8; }}
.visual-learning {{ --theme-accent: #b77a00; --theme-soft: #fff7df; }}
.visual-technology {{ --theme-accent: #557b96; --theme-soft: #edf4f8; }}
.visual-wellness {{ --theme-accent: #65806f; --theme-soft: #eef5ef; }}
.visual-voice {{ --theme-accent: #772432; --theme-soft: #f7edef; }}
.visual-leadership {{ --theme-accent: #772432; --theme-soft: #f5edef; }}
.visual-celebration {{ --theme-accent: #c89524; --theme-soft: #fff5d8; }}
.theme-line {{ color: var(--theme-accent); }}
.theme-line span {{ background: var(--theme-accent); }}
.meta-cell .word-value {{ color: var(--theme-accent); }}
.timeline .section-row td {{ background: var(--theme-soft); }}
.masthead::after {{ content: ""; position: absolute; z-index: 0; right: -8mm; top: -12mm; width: 62mm; height: 48mm; opacity: .45; pointer-events: none; }}
.visual-learning .masthead::after {{ background: radial-gradient(circle at 75% 45%, transparent 0 10mm, color-mix(in srgb,var(--theme-accent) 22%,transparent) 10.3mm 10.6mm, transparent 11mm), radial-gradient(circle at 78% 45%, color-mix(in srgb,var(--theme-accent) 15%,transparent) 0 1.2mm, transparent 1.4mm); background-size: 100% 100%, 9mm 9mm; }}
.visual-technology .masthead::after {{ background: repeating-linear-gradient(0deg,transparent 0 6mm,color-mix(in srgb,var(--theme-accent) 22%,transparent) 6.2mm 6.5mm), repeating-linear-gradient(90deg,transparent 0 9mm,color-mix(in srgb,var(--theme-accent) 18%,transparent) 9.2mm 9.5mm); transform: skewX(-16deg); }}
.visual-wellness .masthead::after {{ border: 1mm solid color-mix(in srgb,var(--theme-accent) 45%,transparent); border-radius: 70% 0 70% 0; transform: rotate(-18deg); background: radial-gradient(ellipse at 50% 100%,color-mix(in srgb,var(--theme-accent) 18%,transparent),transparent 65%); }}
.visual-voice .masthead::after {{ background: repeating-radial-gradient(ellipse at 90% 50%,transparent 0 4mm,color-mix(in srgb,var(--theme-accent) 28%,transparent) 4.2mm 4.5mm,transparent 4.7mm 8mm); }}
.visual-leadership .masthead::after {{ background: linear-gradient(135deg,transparent 42%,color-mix(in srgb,var(--theme-accent) 24%,transparent) 42% 44%,transparent 44% 56%,color-mix(in srgb,var(--theme-accent) 18%,transparent) 56% 58%,transparent 58%); }}
.visual-celebration .masthead::after {{ background: radial-gradient(circle,color-mix(in srgb,var(--theme-accent) 42%,transparent) 0 1mm,transparent 1.2mm); background-size: 9mm 9mm; transform: rotate(12deg); }}
.text-size-large .meta-cell {{ font-size: 2.48mm; }}
.text-size-large .meta-cell b {{ font-size: 2.55mm; }}
.text-size-large .timeline tbody td {{ font-size: 2.32mm; }}
.text-size-large .timeline .section-row td {{ font-size: 2.48mm; }}
.text-size-large .timeline .detail {{ font-size: 1.95mm; }}
.text-size-large .module {{ font-size: 2.28mm; }}
.text-size-large .module h2 {{ font-size: 2.95mm; }}
.text-size-large .timer-rule span,
.text-size-large .timer-rule small {{ font-size: 2mm; }}
.text-size-large .footer {{ font-size: 2.38mm; }}
.text-size-compact .meta-cell {{ font-size: 2.2mm; }}
.text-size-compact .timeline tbody td {{ font-size: 2.08mm; }}
.text-size-compact .module {{ font-size: 2.02mm; }}
.theme-art {{ position: absolute; z-index: 0; right: 0; top: 0; width: 58mm; height: 32mm; object-fit: contain; object-position: right top; opacity: .72; }}
.has-theme-art .title-block {{ padding-right: 42mm; }}
.layout-feature .main-grid {{ grid-template-columns: minmax(0,.72fr) minmax(48mm,.28fr); }}
.layout-feature .timeline-panel {{ grid-column: 1; grid-row: 1; }}
.layout-feature .left-rail {{ grid-column: 2; grid-row: 1; }}
.layout-feature.no-support .main-grid {{ grid-template-columns: minmax(0,1fr); }}
.layout-feature.no-support .timeline-panel {{ grid-column: 1; }}
.layout-feature .timeline .type-special td {{ padding-top: 2.7mm; padding-bottom: 2.7mm; background: #772432; color: #fff; border-bottom-color: #772432; }}
.layout-feature .timeline .type-special .activity {{ color: #fff; font-size: 3.5mm; letter-spacing: .05mm; }}
.layout-feature .timeline .type-special .owner,
.layout-feature .timeline .type-special .duration,
.layout-feature .timeline .type-special .detail {{ color: #f2df74; }}
.layout-feature .feature-highlight td {{ min-height: 24mm; padding: 3.5mm 1.2mm; background: #772432; color: #fff; border-top: .7mm solid #d6a329; border-bottom: .7mm solid #d6a329; }}
.layout-feature .feature-highlight .feature-copy {{ background-image: linear-gradient(128deg,transparent 0 72%,rgba(242,223,116,.1) 72% 74%,transparent 74%); }}
.feature-time {{ color: #f2df74 !important; font-size: 3.2mm; font-weight: 900; font-variant-numeric: tabular-nums; }}
.feature-copy {{ min-width: 0; }}
.feature-copy > strong {{ display: block; color: #fff; font-size: 4.5mm; line-height: 1.08; letter-spacing: .08mm; }}
.feature-beats {{ margin-top: 2.2mm; display: grid; grid-template-columns: repeat(auto-fit,minmax(25mm,1fr)); gap: 1.5mm; }}
.feature-beats span {{ padding-top: .9mm; border-top: .28mm solid rgba(242,223,116,.72); color: #fff6dc; font-size: 2mm; font-weight: 650; line-height: 1.28; text-wrap: balance; }}
.feature-owner {{ color: #f2df74 !important; text-align: left; }}
.owner-align-center .feature-owner {{ text-align: center; }}
.feature-owner strong {{ font-size: 2.7mm; font-weight: 850; }}
.feature-duration {{ color: #f2df74 !important; text-align: right; white-space: nowrap; }}
.feature-duration strong {{ font-size: 6mm; line-height: 1; font-weight: 900; }}
.feature-duration span {{ margin-left: .8mm; font-size: 2.1mm; font-weight: 800; }}
.feature-emphasis-compact .feature-highlight td {{ min-height: 20mm; padding-block: 2mm; }}
.feature-emphasis-compact .feature-copy > strong {{ font-size: 3.7mm; }}
.feature-emphasis-compact .feature-beats {{ margin-top: 1.3mm; gap: 1.1mm; }}
.feature-emphasis-compact .feature-beats span {{ padding-top: .65mm; font-size: 1.85mm; }}
.feature-emphasis-compact .feature-owner strong {{ font-size: 2.35mm; }}
.feature-emphasis-compact .feature-duration strong {{ font-size: 5mm; }}
.feature-emphasis-strong .feature-highlight td {{ min-height: 27mm; padding-block: 4.2mm; }}
.feature-emphasis-strong .feature-copy > strong {{ font-size: 5.1mm; }}
.feature-emphasis-strong .feature-duration strong {{ font-size: 6.8mm; }}
.page.with-support:not(.layout-marathon) .left-rail {{ gap: 0; border: .3mm solid #174f7f; border-radius: 1.2mm; overflow: hidden; background: color-mix(in srgb,var(--theme-soft) 32%,#fff); }}
.page.with-support:not(.layout-marathon) .left-rail .module {{ --rail-grow: 3; flex: var(--rail-grow) 1 0; min-height: min-content; display: flex; flex-direction: column; border: 0; border-bottom: .22mm solid #aebfcb; border-radius: 0; background: rgba(255,255,255,.88); }}
.page.with-support:not(.layout-marathon) .left-rail .module:last-child {{ border-bottom: 0; }}
.page.with-support:not(.layout-marathon) .left-rail .module > :not(h2) {{ margin-top: auto; margin-bottom: auto; }}
.page.with-support:not(.layout-marathon) .left-rail .backstage-module {{ --rail-grow: 3; }}
.page.with-support:not(.layout-marathon) .left-rail .component-timer_rules {{ --rail-grow: 6; }}
.page.with-support:not(.layout-marathon) .left-rail .component-officers {{ --rail-grow: 5; }}
.page.with-support:not(.layout-marathon) .left-rail .component-toastmasters_intro {{ --rail-grow: 3; }}
.page.with-support:not(.layout-marathon) .left-rail .component-meeting_boundaries {{ --rail-grow: 4; }}
.layout-marathon .backstage-strip {{ display: flex; }}
.layout-marathon .main-grid {{ grid-template-columns: minmax(0,1fr); }}
.layout-marathon .left-rail {{ display: none; }}
.layout-marathon .timeline {{ display: flex; padding: 1.2mm; }}
.marathon-flow {{ flex: 1; display: flex; flex-direction: column; gap: .55mm; }}
.marathon-section {{ display: flex; flex-direction: column; border: .22mm solid #c8d5df; background: #fff; }}
.marathon-section > header {{ min-height: 4.5mm; display: flex; justify-content: space-between; align-items: center; padding: .5mm 1.1mm; background: var(--theme-soft); color: #073e70; }}
.marathon-section > header strong {{ font-size: 2.4mm; }}
.marathon-section > header span {{ font-size: 1.9mm; font-weight: 700; font-variant-numeric: tabular-nums; }}
.marathon-cards {{ flex: 1; display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); grid-auto-rows: 1fr; gap: .4mm; padding: .5mm; }}
.marathon-item {{ min-width: 0; min-height: 6.5mm; display: grid; grid-template-columns: 11mm minmax(0,1fr) 19mm 11mm; gap: .6mm; align-items: center; padding: .45mm .8mm; border: .2mm solid #d5dfe6; border-radius: 1mm; background: #fff; }}
.marathon-item time {{ color: var(--theme-accent); font-size: 2.1mm; font-weight: 900; font-variant-numeric: tabular-nums; }}
.marathon-copy {{ min-width: 0; }}
.marathon-copy strong {{ display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #073e70; font-size: 2.15mm; }}
.marathon-copy small {{ display: block; margin-top: .25mm; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #63717d; font-size: 1.6mm; }}
.marathon-owner {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #004165; font-size: 1.9mm; font-weight: 700; }}
.marathon-duration {{ color: #5a6670; font-size: 1.8mm; text-align: right; white-space: nowrap; }}
.marathon-item.type-prepared_speech {{ border-left: 1.1mm solid #004165; }}
.marathon-item.type-prepared_evaluation {{ border-left: 1.1mm solid #772432; background: #fffafb; }}
.marathon-section.section-opening .marathon-item,
.marathon-section.section-closing .marathon-item {{ min-height: 5.8mm; }}
.paired-section {{ flex: 1; min-height: 0; }}
.speech-pair-grid {{ flex: 1; display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); grid-auto-rows: 1fr; gap: .55mm; padding: .6mm; }}
.speech-pair {{ min-width: 0; display: grid; grid-template-columns: 7mm minmax(0,1.35fr) minmax(0,.9fr); gap: .7mm; align-items: stretch; padding: .7mm; border: .22mm solid #cbd8e1; border-radius: 1.2mm; background: #fff; }}
.pair-number {{ display: grid; place-items: center; align-self: center; width: 5.5mm; height: 5.5mm; border-radius: 50%; background: #004165; color: #fff; font-size: 2.3mm; font-weight: 900; }}
.pair-speech {{ min-width: 0; display: grid; grid-template-columns: auto 1fr auto; gap: .3mm .8mm; align-content: center; }}
.pair-speech time {{ color: #004165; font-size: 1.9mm; font-weight: 900; font-variant-numeric: tabular-nums; }}
.pair-speech strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #073e70; font-size: 2.4mm; }}
.pair-speech small {{ grid-column: 1 / -1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #63717d; font-size: 1.9mm; }}
.pair-speech span {{ color: #004165; font-size: 2mm; font-weight: 700; }}
.pair-speech b {{ color: #5a6670; font-size: 1.9mm; text-align: right; }}
.pair-evaluation {{ min-width: 0; display: grid; grid-template-columns: auto 1fr; gap: .25mm .6mm; align-content: center; padding-left: .8mm; border-left: .8mm solid #772432; background: #fffafb; }}
.pair-evaluation time {{ color: #772432; font-size: 2mm; font-weight: 900; }}
.pair-evaluation span {{ color: #772432; font-size: 1.85mm; }}
.pair-evaluation strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #772432; font-size: 2mm; }}
.pair-evaluation small {{ color: #6f5a60; font-size: 1.85mm; text-align: right; }}
.pair-evaluation.missing {{ place-items: center; color: #8b949c; }}
.speech-pair:last-child:nth-child(odd) {{ grid-column: 1 / -1; }}
.layout-marathon .bottom-grid {{ gap: 0; border: .3mm solid #174f7f; background: #fff; }}
.layout-marathon .bottom-grid .module {{ min-height: 0; border: 0; border-right: .22mm solid #aebfcb; border-radius: 0; padding: 1.4mm; font-size: 2mm; }}
.layout-marathon .bottom-grid .module:last-child {{ border-right: 0; }}
.layout-marathon .bottom-grid .module h2 {{ margin: -1.4mm -1.4mm 1mm; padding: .8mm 1.4mm; background: var(--theme-soft); border-bottom: .28mm solid #d6a329; color: #004165; font-size: 2.4mm; }}
.layout-marathon.lang-zh .bottom-grid .timer-rules,
.layout-marathon.lang-en .bottom-grid .timer-rules {{ grid-template-columns: repeat(3,minmax(0,1fr)); gap: 0; }}
.layout-marathon.lang-zh .bottom-grid .timer-rule,
.layout-marathon.lang-en .bottom-grid .timer-rule {{ padding: 0 .8mm; border-right: .18mm solid #d4dde3; border-bottom: 0; }}
.layout-marathon.lang-zh .bottom-grid .timer-rule:last-child,
.layout-marathon.lang-en .bottom-grid .timer-rule:last-child {{ border-right: 0; }}
.layout-marathon .bottom-grid .officer-list {{ grid-template-columns: repeat(2,minmax(0,1fr)); gap: .3mm 1mm; }}
.layout-marathon .bottom-grid .officer-list div {{ grid-template-columns: .9fr 1fr; }}
@media print {{
  html, body {{ background: white; }}
  .page {{ margin: 0; min-height: 297mm; height: auto; overflow: visible; page-break-after: auto; break-after: auto; }}
}}
</style>
</head>
<body>{''.join(page_blocks)}{CLASSIC_VISUAL_AUDIT_SCRIPT}</body>
</html>
"""


def resolve_html_renderer(result: dict[str, Any], requested: str = "auto") -> str:
    if requested not in HTML_RENDERERS:
        raise ValueError("html renderer must be auto, classic, or editorial")
    if requested != "auto":
        return requested
    language = result.get("club", {}).get("language", "zh")
    layout = result.get("layout", "standard")
    support = set(result.get("support_components", []))
    if (
        language in {"zh", "en"}
        and layout == "standard"
        and bool(support & {"timer_rules", "officers"})
    ):
        try:
            from editorial_renderer import editorial_compatibility_errors
        except ModuleNotFoundError:
            from scripts.editorial_renderer import editorial_compatibility_errors
        if not editorial_compatibility_errors(result):
            return "editorial"
    return "classic"


def render_output_html(result: dict[str, Any], renderer: str = "auto") -> str:
    renderer = resolve_html_renderer(result, renderer)
    if renderer not in HTML_RENDERERS:
        raise ValueError("html renderer must be auto, classic, or editorial")
    if renderer == "classic":
        return render_html(result)
    try:
        from editorial_renderer import render_editorial_html
    except ModuleNotFoundError:
        from scripts.editorial_renderer import render_editorial_html
    language = result.get("club", {}).get("language", "zh")
    return render_editorial_html(
        result,
        timer_rules=TIMER_RULES,
        toastmasters_intro_text=toastmasters_intro(language),
        meeting_boundary_lines=meeting_boundaries(language),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument(
        "--club-profile",
        type=str,
        default=None,
        metavar="CLUB_NAME",
        help="load or create the stable profile for this exact club name",
    )
    parser.add_argument(
        "--update-club-profile",
        action="store_true",
        help="overwrite the stored club profile after successful validation",
    )
    parser.add_argument(
        "--profile-root",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--save-profile",
        type=Path,
        default=None,
        help="save confirmed reusable club facts for later meeting tasks",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--html-renderer",
        choices=sorted(HTML_RENDERERS),
        default="auto",
        help="choose the final HTML visual renderer without changing computed content",
    )
    args = parser.parse_args()

    if args.profile and args.club_profile:
        parser.error("use either --profile or --club-profile, not both")
    if args.update_club_profile and not args.club_profile:
        parser.error("--update-club-profile requires --club-profile")
    if args.profile_root and not args.club_profile:
        parser.error("--profile-root requires --club-profile")

    input_path = args.input_json.expanduser().resolve()
    if not input_path.is_file():
        parser.error(f"input JSON does not exist: {input_path}")
    stored_profile_path: Path | None = None
    stored_profile_existed = False
    try:
        data = load_json(input_path)
        if args.profile:
            profile_path = args.profile.expanduser().resolve()
            profile_data = resolve_profile_relative_paths(
                load_json(profile_path), profile_path
            )
            data = deep_merge(profile_data, data)
        elif args.club_profile:
            profile_root = (
                args.profile_root.expanduser().resolve()
                if args.profile_root
                else PROFILE_ROOT
            )
            stored_profile_path = stored_club_profile_path(
                args.club_profile, profile_root=profile_root
            )
            stored_profile_existed = stored_profile_path.is_file()
            if stored_profile_existed:
                profile_data = resolve_profile_relative_paths(
                    load_json(stored_profile_path), stored_profile_path
                )
                stored_name = profile_data.get("club", {}).get("name", "")
                if normalized_club_name(stored_name) != normalized_club_name(
                    args.club_profile
                ):
                    raise ValueError(
                        "stored club profile identity does not match --club-profile"
                    )
                data = deep_merge(profile_data, data)
                merged_name = data.get("club", {}).get("name", "")
                if normalized_club_name(merged_name) != normalized_club_name(
                    args.club_profile
                ):
                    raise ValueError(
                        "input club.name does not match the stored --club-profile"
                    )
            else:
                club_data = data.setdefault("club", {})
                if not isinstance(club_data, dict):
                    raise ValueError("club must be an object")
                input_name = club_data.get("name")
                if is_unresolved(input_name):
                    club_data["name"] = args.club_profile
                elif normalized_club_name(input_name) != normalized_club_name(
                    args.club_profile
                ):
                    raise ValueError(
                        "input club.name does not match --club-profile"
                    )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)

    result, errors, warnings = build_agenda(data, source_dir=input_path.parent)
    summary = {
        "ok": not errors,
        "computed": result["computed"],
        "warnings": warnings,
        "errors": errors,
    }
    if args.validate_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not errors else 2)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = output_dir / "agenda.diagnostics.json"
    diagnostics_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)

    computed_path = output_dir / "agenda.computed.json"
    markdown_path = output_dir / "agenda.md"
    html_path = output_dir / "agenda.html"
    computed_result = deepcopy(result)
    computed_result.pop("_assets", None)
    computed_path.write_text(
        json.dumps(computed_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    try:
        resolved_html_renderer = resolve_html_renderer(result, args.html_renderer)
        rendered_html = render_output_html(result, resolved_html_renderer)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {**summary, "ok": False, "errors": [*errors, str(exc)]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)
    html_path.write_text(rendered_html, encoding="utf-8")

    saved_profile_path: Path | None = None
    if args.save_profile:
        saved_profile_path = args.save_profile.expanduser().resolve()
        write_club_profile(
            data,
            saved_profile_path,
            source_dir=input_path.parent,
        )
    if stored_profile_path and (
        not stored_profile_existed or args.update_club_profile
    ):
        write_club_profile(
            data,
            stored_profile_path,
            source_dir=input_path.parent,
        )
        saved_profile_path = stored_profile_path
    elif stored_profile_path:
        saved_profile_path = stored_profile_path

    print(
        json.dumps(
            {
                **summary,
                "outputs": {
                    "computed_json": str(computed_path),
                    "markdown": str(markdown_path),
                    "html": str(html_path),
                    "diagnostics": str(diagnostics_path),
                    "html_renderer": resolved_html_renderer,
                    **(
                        {"club_profile": str(saved_profile_path)}
                        if saved_profile_path
                        else {}
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
