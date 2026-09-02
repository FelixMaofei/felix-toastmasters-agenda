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
GENERIC_SPECIAL_OWNERS = {
    "主持人",
    "总主持",
    "负责人",
    "主讲人",
    "讲师",
    "嘉宾",
    "toastmaster",
    "host",
    "facilitator",
    "presenter",
    "speaker",
    "owner",
    "role taker",
    "person in charge",
    "tbc",
    "to be confirmed",
    "to be decided",
}
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
      document.querySelectorAll(".location-cell span").forEach((location, index) => {
        const style = getComputedStyle(location);
        if (style.whiteSpace === "nowrap" || style.textOverflow === "ellipsis") {
          fail("location-truncation", index);
        }
        if (location.scrollWidth > location.clientWidth + 1) {
          fail("location-horizontal-overflow", index);
        }
        if (location.scrollHeight > location.clientHeight + 1) {
          fail("location-vertical-overflow", index);
        }
        const cell = location.closest(".location-cell");
        if (cell) {
          const locationRect = location.getBoundingClientRect();
          const cellRect = cell.getBoundingClientRect();
          if (locationRect.top < cellRect.top - 1 || locationRect.bottom > cellRect.bottom + 1) {
            fail("location-cell-bounds", index);
          }
        }
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
CONFIRMABLE_DURATION_SUGGESTIONS = {
    "photo_break": 10,
    "sharing": 10,
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
DEFAULT_SUPPORT_COMPONENTS = [
    "timer_rules",
    "toastmasters_intro",
    "meeting_boundaries",
]

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


def is_generic_special_owner(value: Any) -> bool:
    """Reject role labels used in place of a named special-session owner.

    Matching is deliberately exact after light Unicode and whitespace normalization so
    names such as ``主持人小王`` or ``Toastmaster Jane`` remain valid.
    """
    normalized = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in GENERIC_SPECIAL_OWNERS


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


def materialize_support_blocks(
    *,
    language: str,
    support_components: list[str],
    custom_support_blocks: list[dict[str, Any]],
    officers: list[dict[str, Any]],
    club_intro: list[str],
    join_info: list[str],
    vpm_qr_data: str,
    voting_qr_data: str,
) -> list[dict[str, Any]]:
    """Turn selected support content into self-contained V3 fact blocks.

    The renderer must not recreate Toastmasters copy or reopen source images.
    Physical placement and ordering remain the responsibility of agenda.view.json.
    """

    blocks: list[dict[str, Any]] = []
    for component in support_components:
        if component == "timer_rules":
            blocks.append(
                {
                    "id": component,
                    "group": "operations",
                    "kind": "timing",
                    "title": localized("时间官规则", "Timer Rules", language),
                    "entries": [
                        {
                            "label": localized(
                                row["band_zh"], row["band_en"], language
                            ),
                            "value": " · ".join(
                                [
                                    f"{localized('绿牌', 'Green', language)}: "
                                    f"{localized(row['green_zh'], row['green_en'], language)}",
                                    f"{localized('黄牌', 'Yellow', language)}: "
                                    f"{localized(row['yellow_zh'], row['yellow_en'], language)}",
                                    f"{localized('红牌', 'Red', language)}: "
                                    f"{localized(row['red_zh'], row['red_en'], language)}",
                                    f"{localized('响铃', 'Bell', language)}: "
                                    f"{localized(row['bell_zh'], row['bell_en'], language)}",
                                ]
                            ),
                        }
                        for row in TIMER_RULES
                    ],
                }
            )
        elif component == "toastmasters_intro":
            blocks.append(
                {
                    "id": component,
                    "group": "background",
                    "kind": "prose",
                    "title": localized(
                        "头马国际演讲会", "Toastmasters International", language
                    ),
                    "lines": [toastmasters_intro(language)],
                }
            )
        elif component == "meeting_boundaries":
            blocks.append(
                {
                    "id": component,
                    "group": "background",
                    "kind": "bullets",
                    "title": localized(
                        "会议秩序与内容边界",
                        "Meeting Conduct & Content Boundaries",
                        language,
                    ),
                    "lines": meeting_boundaries(language),
                }
            )
        elif component == "officers":
            blocks.append(
                {
                    "id": component,
                    "group": "operations",
                    "kind": "pairs",
                    "title": localized("当届官员团队", "Current Officer Team", language),
                    "entries": [
                        {"label": row["role"], "value": row["name"]}
                        for row in officers
                    ],
                }
            )
        elif component == "club_intro":
            blocks.append(
                {
                    "id": component,
                    "group": "background",
                    "kind": "prose",
                    "title": localized("俱乐部介绍", "About the Club", language),
                    "lines": list(club_intro),
                }
            )
        elif component == "join_info":
            blocks.append(
                {
                    "id": component,
                    "group": "background",
                    "kind": "bullets",
                    "title": localized("如何入会", "How to Join", language),
                    "lines": list(join_info),
                }
            )
        elif component == "vpm_qr":
            blocks.append(
                {
                    "id": component,
                    "group": "background",
                    "kind": "image",
                    "title": localized("入会咨询", "Membership Contact", language),
                    "data_uri": vpm_qr_data,
                    "alt": localized("VPM 入会二维码", "VPM joining QR code", language),
                }
            )
        elif component == "voting_qr":
            blocks.append(
                {
                    "id": component,
                    "group": "operations",
                    "kind": "image",
                    "title": localized("本期投票", "Meeting Voting", language),
                    "data_uri": voting_qr_data,
                    "alt": localized("本期投票二维码", "Meeting voting QR code", language),
                }
            )

    for block in custom_support_blocks:
        blocks.append(
            {
                "id": block["id"],
                "kind": "bullets",
                "title": block["title"],
                "lines": list(block["lines"]),
            }
        )
    return blocks


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


def parse_participant_pathways(
    value: Any, errors: list[str]
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append("participant_pathways must be an object mapping person to progress")
        return {}
    result: dict[str, str] = {}
    for raw_name, raw_progress in value.items():
        name = str(raw_name).strip()
        if not name:
            errors.append("participant_pathways contains an empty person name")
            continue
        if not isinstance(raw_progress, str) or not raw_progress.strip():
            errors.append(
                f"participant_pathways[{name!r}] must be a non-empty string"
            )
            continue
        result[name] = raw_progress.strip()
    return result


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


def resolve_support_components(
    meeting: dict[str, Any],
    club: dict[str, Any],
    errors: list[str],
) -> list[str]:
    """Choose current-meeting selection, then profile selection, then safe defaults.

    An explicit empty array is meaningful and must remain agenda-only. When neither the
    meeting nor the club profile chooses components, only the universal information
    blocks are included. Joining information is never synthesized or added implicitly.
    The officer block is added only when the stored team already passes the normal
    officer validation.
    """
    if "support_components" in meeting:
        raw_components = meeting["support_components"]
    elif "support_components" in club:
        raw_components = club["support_components"]
    else:
        raw_components = list(DEFAULT_SUPPORT_COMPONENTS)
        officer_errors: list[str] = []
        parse_officers(club.get("officers"), officer_errors)
        if not officer_errors:
            raw_components.append("officers")
    return parse_support_components(raw_components, errors)


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
        "section",
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
        if "section" in row:
            section = str(row["section"]).strip()
            if section not in SECTION_LABELS:
                errors.append(
                    f"agenda override {item_id} section must be opening, first_half, "
                    "second_half, or closing"
                )
            else:
                normalized["section"] = section
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
        reordered.insert(anchor_index + 1, item)
        shared_anchor_tails[requested_anchor] = item_id
    return reordered


def validate_agenda_order(
    items: list[dict[str, Any]], errors: list[str]
) -> bool:
    """Protect relationships that remain mandatory when the agenda is reordered."""
    valid = True
    index_by_id = {
        str(item["id"]): index for index, item in enumerate(items)
    }

    for item_id, item_index in index_by_id.items():
        if not item_id.startswith("prepared_evaluation:"):
            continue
        number = item_id.split(":", 1)[1]
        speech_id = f"prepared_speech:{number}"
        speech_index = index_by_id.get(speech_id)
        if speech_index is not None and item_index <= speech_index:
            errors.append(
                f"agenda order requires {item_id} after {speech_id}"
            )
            valid = False

    table_topics_index = index_by_id.get("table_topics")
    table_topics_evaluation_index = index_by_id.get("table_topics_evaluation")
    if (
        table_topics_index is not None
        and table_topics_evaluation_index is not None
        and table_topics_evaluation_index <= table_topics_index
    ):
        errors.append(
            "agenda order requires table_topics_evaluation after table_topics"
        )
        valid = False

    president_closing_index = index_by_id.get("president_closing")
    if (
        president_closing_index is not None
        and president_closing_index != len(items) - 1
    ):
        errors.append(
            "agenda order requires president_closing to remain the final meeting item"
        )
        valid = False

    main_or_feedback_types = {
        "prepared_speech",
        "table_topics",
        "prepared_evaluation",
        "table_topics_evaluation",
        "grammarian_report",
        "ah_counter_report",
        "timer_report",
    }
    flexible_closing_ids = ("general_evaluation", "sharing")
    terminal_closing_ids = ("awards", "president_closing")
    closing_prerequisites = [
        (index, str(item["id"]))
        for index, item in enumerate(items)
        if str(item["id"]) not in flexible_closing_ids
        and (
            item["type"] in main_or_feedback_types
            or item.get("section") != "closing"
        )
    ]
    for closing_id in flexible_closing_ids:
        closing_index = index_by_id.get(closing_id)
        if closing_index is None:
            continue
        closing_item = items[closing_index]
        if closing_item.get("section") != "closing":
            errors.append(
                f"agenda order requires {closing_id} to remain in the closing section"
            )
            valid = False
        later_prerequisite = next(
            (
                prerequisite_id
                for prerequisite_index, prerequisite_id in closing_prerequisites
                if prerequisite_index > closing_index
            ),
            None,
        )
        if later_prerequisite is not None:
            errors.append(
                f"agenda order requires {closing_id} after all main and feedback items; "
                f"it currently precedes {later_prerequisite}"
            )
            valid = False
        earlier_terminal = next(
            (
                terminal_id
                for terminal_id in terminal_closing_ids
                if terminal_id in index_by_id
                and index_by_id[terminal_id] < closing_index
            ),
            None,
        )
        if earlier_terminal is not None:
            errors.append(
                f"agenda order requires {closing_id} before awards and meeting close; "
                f"it currently follows {earlier_terminal}"
            )
            valid = False

    return valid


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
        if "section" in override:
            item["section"] = override["section"]
    filtered = [item for item in items if item["id"] not in removed]
    reordered = reorder_agenda_items(filtered, moves, errors)
    if validate_agenda_order(reordered, errors):
        filtered = reordered
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
            # These are operational choices, not spare-time buckets.  Keep the
            # proposal deterministic for diagnostics, but block output until it
            # is explicitly locked by an override.
            duration = CONFIRMABLE_DURATION_SUGGESTIONS[item_type]
            locked = False
            preferred = CONFIRMABLE_DURATION_SUGGESTIONS[item_type]
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
                errors.append(
                    "impromptu.minutes needs an explicit confirmed duration"
                )
                # Keep diagnostics deterministic, but never let the flexible
                # solver infer a missing Table Topics duration from spare time.
                tt_duration = 15
                tt_locked = True
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
                    errors.append(
                        "impromptu.evaluation_minutes needs an explicit confirmed duration"
                    )
                    # This fallback is diagnostic-only: the error blocks output,
                    # and the duration is not inferred from the meeting balance.
                    eval_duration = 7
                    eval_locked = True
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
        minutes_value = segment.get("minutes")
        duration = positive_minutes(minutes_value)
        raw_anchor = segment.get("after")
        invalid_segment = False
        if is_unresolved(title):
            errors.append(f"special segment {index} has unresolved title")
            invalid_segment = True
        if is_unresolved(owner):
            errors.append(f"special segment {index} has unresolved owner")
            invalid_segment = True
        elif is_generic_special_owner(owner):
            errors.append(
                f"special segment {index} owner must name a real person, "
                f"not a generic role: {str(owner).strip()!r}"
            )
            invalid_segment = True
        if duration is None:
            errors.append(
                f"special segment {index} minutes must be positive in 0.5-minute increments"
            )
            invalid_segment = True
        if is_unresolved(raw_anchor):
            errors.append(f"special segment {index} has unresolved after anchor")
            invalid_segment = True
        if invalid_segment:
            continue
        assert duration is not None
        anchor = str(raw_anchor).strip()
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
        original_anchor = str(raw_anchor).strip()
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
    *,
    facts_only: bool = False,
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
    visual_preferences = (
        {}
        if facts_only
        else parse_visual_preferences(meeting.get("visual_preferences"), errors)
    )
    for field in ("number", "date", "start"):
        if is_unresolved(meeting.get(field)):
            errors.append(f"meeting.{field} is required")
    location = meeting.get("location", club.get("default_location"))
    if is_unresolved(location):
        errors.append("meeting location is unresolved")
    meeting["location"] = "" if location is None else str(location).strip()
    support_components = resolve_support_components(meeting, club, errors)
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
    if facts_only and any(
        block.get("id") == "backstage" for block in custom_support_blocks
    ):
        errors.append(
            "custom support block id 'backstage' conflicts with the built-in backstage component"
        )
    participant_pathways = (
        parse_participant_pathways(normalized.get("participant_pathways"), errors)
        if facts_only
        else {}
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
    if not facts_only and not is_unresolved(meeting.get("theme_image")):
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
    duration_confirmation_items = [
        {
            "id": item["id"],
            "label": item["label"],
            "suggested_minutes": CONFIRMABLE_DURATION_SUGGESTIONS[item["type"]],
        }
        for item in items
        if item["type"] in CONFIRMABLE_DURATION_SUGGESTIONS
        and not item.get("duration_locked", False)
    ]
    suggested_agenda_overrides = [
        {"id": item["id"], "minutes": item["suggested_minutes"]}
        for item in duration_confirmation_items
    ]
    if duration_confirmation_items:
        missing_ids = " and ".join(
            item["id"] for item in duration_confirmation_items
        )
        errors.append(
            f"{missing_ids} need explicit confirmed durations; use the suggested "
            f"agenda_overrides {suggested_agenda_overrides} after the user agrees"
        )
    if facts_only:
        for item in items:
            item["pathways"] = participant_pathways.get(item.get("owner", ""), "")
    attach_transition_overrides(items, transition_overrides, errors)
    layout = ""
    feature_item_id: str | None = None
    visual_theme = ""
    if not facts_only:
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
    if duration_confirmation_items:
        # The proposed 10-minute values exist only to support one clear user
        # question.  Overtime/underfill is assessed after the user confirms or
        # replaces them, never from an unconfirmed proposal.
        pass
    elif delta > 0:
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
    if not facts_only:
        page_item_limit = (
            36 if layout == "marathon" else 30 if layout == "standard" else 28
        )
        if len(items) > page_item_limit:
            errors.append(
                f"single-page A4 capacity exceeded: {len(items)} agenda rows; "
                f"reduce or combine content to {page_item_limit} rows or fewer"
            )

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
        "duration_confirmation_required": bool(duration_confirmation_items),
        "duration_confirmation_items": duration_confirmation_items,
        "suggested_agenda_overrides": suggested_agenda_overrides,
    }
    if not facts_only:
        computed.update(
            {
                "page_count": 1,
                "layout": layout,
                "feature_item": feature_item_id,
                "visual_theme": visual_theme,
            }
        )

    support_blocks = materialize_support_blocks(
        language=language,
        support_components=support_components,
        custom_support_blocks=custom_support_blocks,
        officers=officers,
        club_intro=club_intro,
        join_info=join_info,
        vpm_qr_data=vpm_qr_data,
        voting_qr_data=voting_qr_data,
    )

    result = {
        "schema_version": 3 if facts_only else 2,
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
            )
            if key in meeting
        },
        "timeline": items,
        "backstage": backstage,
        "computed": computed,
        "warnings": warnings,
        "_assets": {
            "vpm_qr_data_uri": vpm_qr_data,
            "voting_qr_data_uri": voting_qr_data,
            "theme_art_data_uri": theme_art_data,
        },
    }
    if facts_only:
        result["support_blocks"] = support_blocks
        for legacy_key in (
            "support_components",
            "officers",
            "club_intro",
            "join_info",
            "vpm_qr_present",
        ):
            result["club"].pop(legacy_key, None)
    else:
        result["agenda_overrides"] = list(agenda_overrides.values())
        result["support_components"] = support_components
        result["custom_support_blocks"] = custom_support_blocks
        if "visual_preferences" in meeting:
            result["meeting"]["visual_preferences"] = meeting.get(
                "visual_preferences"
            )
        result.update(
            {
                "layout": layout,
                "feature_item": feature_item_id,
                "visual_theme": visual_theme,
                "visual_preferences": visual_preferences,
            }
        )
        result["meeting"]["voting_qr_present"] = bool(voting_qr_data)
    return result, errors, warnings


def append_materialized_support_markdown(
    lines: list[str],
    blocks: list[dict[str, Any]],
    language: str,
) -> None:
    """Render V3 support facts without recreating copy from module constants."""

    if not blocks:
        return
    lines.extend(
        ["", f"## {localized('固定信息组件', 'Support Components', language)}"]
    )
    for block in blocks:
        title = str(block.get("title", "")).strip()
        kind = str(block.get("kind", block.get("type", ""))).strip()
        lines.extend(["", f"### {title}", ""])
        if kind in {"pairs", "timing"}:
            if kind == "timing":
                first_header = localized("时长区间", "Timing band", language)
                second_header = localized("提示规则", "Signals", language)
            elif block.get("id") == "officers":
                first_header = localized("职务", "Role", language)
                second_header = localized("姓名", "Name", language)
            else:
                first_header = localized("项目", "Item", language)
                second_header = localized("内容", "Details", language)
            lines.extend(
                [
                    f"| {first_header} | {second_header} |",
                    "|---|---|",
                ]
            )
            for entry in block.get("entries", []):
                if not isinstance(entry, dict):
                    continue
                lines.append(
                    f"| {entry.get('label', '')} | {entry.get('value', '')} |"
                )
        elif kind == "prose":
            lines.extend(str(value) for value in block.get("lines", []) if value)
        elif kind == "image":
            alt = str(block.get("alt", title)).strip()
            lines.append(f"- {alt}")
        else:
            lines.extend(
                f"- {value}" for value in block.get("lines", []) if value
            )


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
            "pathways": "Pathways",
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
            "pathways": "Pathways 进展 / Progress",
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
            "pathways": "Pathways 进展",
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
    show_pathways = any(
        str(item.get("pathways", "")).strip() for item in result["timeline"]
    )
    if show_pathways:
        lines.extend(
            [
                "",
                f"| {labels['time_col']} | {labels['agenda']} | {labels['owner']} | "
                f"{labels['pathways']} | {labels['duration']} |",
                "|---|---|---|---|---:|",
            ]
        )
    else:
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
            if show_pathways:
                lines.append(f"|  | **{current_section}** |  |  |  |")
            else:
                lines.append(f"|  | **{current_section}** |  |  |")
            last_section = current_section
        details = "<br>".join(item.get("details", []))
        activity = item["label"] + (f"<br><small>{details}</small>" if details else "")
        if show_pathways:
            lines.append(
                f"| {item['start']}-{item['end']} | {activity} | {item['owner']} | "
                f"{item.get('pathways', '')} | {format_minutes(item['duration'])} min |"
            )
        else:
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
    if "support_blocks" in result:
        append_materialized_support_markdown(
            lines,
            result.get("support_blocks", []),
            language,
        )
        return "\n".join(lines) + "\n"
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
