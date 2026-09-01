from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_renderer", ROOT / "scripts" / "agenda_renderer.py"
)
assert SPEC and SPEC.loader
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def support_blocks(include_club_intro: bool = False) -> list[dict]:
    blocks = [
        {
            "id": "timer_rules",
            "group": "operations",
            "kind": "timing",
            "title": "时间官规则 / Timing",
            "entries": [
                {"label": "≤3分", "value": "绿余1分钟 · 黄余30秒 · 红到时"},
                {"label": "3-10分", "value": "绿余2分钟 · 黄余1分钟 · 红到时"},
                {"label": "≥10分", "value": "绿余5分钟 · 黄余2分钟 · 红到时"},
            ],
        },
        {
            "id": "officers",
            "group": "operations",
            "kind": "pairs",
            "title": "当届官员团队 / Officers",
            "entries": [
                {"label": "President", "value": "Leo 李昂"},
                {"label": "VPE", "value": "Mia 米娅"},
                {"label": "VPM", "value": "Sophie 苏菲"},
                {"label": "VPPR", "value": "Nina 宁娜"},
            ],
        },
        {
            "id": "toastmasters_intro",
            "group": "background",
            "kind": "prose",
            "title": "头马介绍 / Toastmasters",
            "lines": [
                "Toastmasters International 创立于 1924 年，通过俱乐部实践提升表达与领导力。"
            ],
        },
        {
            "id": "meeting_boundaries",
            "group": "background",
            "kind": "bullets",
            "title": "会议边界 / Meeting Boundaries",
            "lines": [
                "尊重演讲，手机静音。",
                "内容不涉及政治、宗教、色情或低俗。",
                "整洁离场。",
            ],
        },
    ]
    if include_club_intro:
        blocks.append(
            {
                "id": "club_intro",
                "group": "background",
                "kind": "prose",
                "title": "俱乐部介绍 / About the Club",
                "lines": [
                    "定位：让你练好表达、用好 AI 的实践成长平台。",
                    "愿景：让每位会员收获实实在在的自信与成长。",
                    "头马是根基，AI 是特色，Lab 是共同实践的方式。",
                ],
            }
        )
    return blocks


def computed_case(
    *,
    language: str = "zh",
    workshop: bool = False,
    english_dense: bool = False,
) -> dict:
    labels = (
        [
            ("rules", "Meeting Rules", "Nina Chen", 2, "opening"),
            ("president", "President's Opening", "Leo Li", 3, "opening"),
            ("speech:1", "Prepared Speech 1", "Ethan Yi", 7, "first_half"),
            ("speech:2", "Prepared Speech 2", "Luna Lu", 7, "first_half"),
            ("speech:3", "Prepared Speech 3", "Sean Shen", 7, "first_half"),
            ("evaluation:1", "Evaluation 1", "Iris Ai", 3, "second_half"),
            ("evaluation:2", "Evaluation 2", "Owen Ou", 3, "second_half"),
            ("evaluation:3", "Evaluation 3", "Ruby Ru", 3, "second_half"),
            ("closing", "Closing Remarks", "Leo Li", 2, "closing"),
        ]
        if english_dense
        else [
            ("rules", "规则介绍", "Nina 宁娜", 2, "opening"),
            ("president", "会长致辞", "Leo 李昂", 3, "opening"),
            ("speech:1", "备稿演讲 1", "Ethan 易辰", 7, "first_half"),
            ("topics", "即兴演讲", "Ava 安然", 15, "first_half"),
            ("evaluation:1", "备稿点评 1", "Iris 艾瑞丝", 3, "second_half"),
            ("closing", "闭幕致辞", "Leo 李昂", 2, "closing"),
        ]
    )
    minute = 0
    timeline = []
    for index, (item_id, label, owner, duration, section) in enumerate(labels):
        start_total = 19 * 60 + 30 + minute
        end_total = start_total + duration
        item = {
            "id": item_id,
            "type": "prepared_speech" if item_id.startswith("speech") else item_id,
            "label": label,
            "owner": owner,
            "section": section,
            "details": [f"Detail {index + 1}"] if item_id.startswith("speech") else [],
            "duration": duration,
            "start": f"{start_total // 60:02d}:{start_total % 60:02d}",
            "end": f"{end_total // 60:02d}:{end_total % 60:02d}",
        }
        if workshop:
            item["pathways"] = ["PM L4", "DL L2", "IP L3"][index % 3]
        timeline.append(item)
        minute += duration + 1

    if workshop:
        timeline.insert(
            2,
            {
                "id": "special:1",
                "type": "special",
                "label": "AI Skill 深度实战——从角色接龙到专业会单",
                "owner": "林舟",
                "section": "first_half",
                "details": ["识别事实", "闭合时间", "生成一页 A4 会单"],
                "duration": 60,
                "start": "19:36",
                "end": "20:36",
                "pathways": "PM L4",
            },
        )

    blocks = (
        [
            {
                "id": "timer_rules",
                "group": "operations",
                "kind": "timing",
                "title": "Timer Rules",
                "entries": [
                    {"label": "≤3 min", "value": "Green 1 min left · Yellow 30 sec left · Red at time"},
                    {"label": "3-10 min", "value": "Green 2 min left · Yellow 1 min left · Red at time"},
                    {"label": "≥10 min", "value": "Green 5 min left · Yellow 2 min left · Red at time"},
                ],
            },
            {
                "id": "officers",
                "group": "operations",
                "kind": "pairs",
                "title": "Officer Team",
                "entries": [
                    {"label": "President", "value": "Leo Li"},
                    {"label": "VPE", "value": "Mia Wang"},
                    {"label": "VPM", "value": "Sophie Su"},
                    {"label": "VPPR", "value": "Nina Chen"},
                ],
            },
            {
                "id": "toastmasters_intro",
                "group": "background",
                "kind": "prose",
                "title": "Toastmasters International",
                "lines": [
                    "Founded in 1924, Toastmasters helps people grow through communication and leadership practice."
                ],
            },
            {
                "id": "meeting_boundaries",
                "group": "background",
                "kind": "bullets",
                "title": "Meeting Boundaries",
                "lines": [
                    "Respect every speaker and keep phones silent.",
                    "Avoid politics, religion, pornography and pyramid selling.",
                    "Leave the room clean and orderly.",
                ],
            },
        ]
        if english_dense
        else support_blocks(include_club_intro=workshop)
    )
    selected = [block["id"] for block in blocks]
    return {
        "schema_version": 3,
        "club": {
            "name": (
                "Starbridge Toastmasters Club"
                if english_dense
                else "晨光 AI Lab 头马俱乐部"
                if workshop
                else "晨曦头马演讲俱乐部"
            ),
            "default_location": (
                "Harbor Innovation Center, Room 301"
                if english_dense
                else "海城市创新中心 3F · 山海厅"
            ),
            "language": language,
        },
        "meeting": {
            "number": "42" if workshop else "18",
            "date": "2026-09-02",
            "location": (
                "Harbor Innovation Center, Room 301"
                if english_dense
                else "海城市创新中心 3F · 山海厅"
            ),
            "theme": (
                "AI Skill 深度实战"
                if workshop
                else "Speak Beyond Borders"
                if english_dense
                else "把复杂的事，讲得简单"
            ),
            "word_of_day": (
                "如虎添翼"
                if workshop
                else "Clarity"
                if english_dense
                else "Clarity · 澄明"
            ),
            "manager": (
                "林夏" if workshop else "Lily Lin" if english_dense else "Lily 林"
            ),
        },
        "computed": {
            "status": "exact",
            "start": "19:30",
            "final_end": "21:30",
            "item_minutes": 105,
            "transition_minutes": 15,
            "total_minutes": 120,
        },
        "timeline": timeline,
        "backstage": (
            [
                {"label": "Photographer", "person": "Shuwen Zheng"},
                {"label": "Stage and Slides", "person": "Maggie Zhao"},
            ]
            if english_dense
            else [
                {"label": "拍照官", "person": "舒文"},
                {"label": "场控 / PPT", "person": "望舒"},
            ]
        ),
        "support_components": selected,
        "support_blocks": blocks,
        "custom_support_blocks": [],
    }


def view_case(*, workshop: bool = False, compact: bool = False) -> dict:
    background = ["toastmasters_intro", "meeting_boundaries"]
    if workshop:
        background.append("club_intro")
    return {
        "view_version": 1,
        "content_emphasis": (
            {"item_id": "special:1", "strength": "clear"} if workshop else None
        ),
        "display_columns": (
            ["time", "activity", "owner", "pathways", "duration"]
            if workshop
            else ["time", "activity", "owner", "duration"]
        ),
        "component_flow": {
            "operations": ["backstage", "timer_rules", "officers"],
            "background": background,
        },
        "density": "compact" if compact or workshop else "balanced",
        "design": {
            "text_scale": "large" if workshop else "standard",
            "contrast": "clear",
        },
    }


class V3AgendaRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.asset_root = Path(cls.temp_dir.name)
        (cls.asset_root / "assets" / "fonts" / "noto-sans-sc" / "files").mkdir(
            parents=True
        )
        (cls.asset_root / "assets" / "agenda.css").write_text(
            (ROOT / "assets" / "agenda.css").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (cls.asset_root / "assets" / "fonts" / "noto-sans-sc" / "index.css").write_text(
            "@font-face{font-family:'Noto Sans SC Variable';"
            "src:url(./files/test.woff2) format('woff2');}",
            encoding="utf-8",
        )
        (
            cls.asset_root
            / "assets"
            / "fonts"
            / "noto-sans-sc"
            / "files"
            / "test.woff2"
        ).write_bytes(b"test-font-data")
        (cls.asset_root / "assets" / "toastmasters-logo.png").write_bytes(
            b"\x89PNG\r\n\x1a\nvalid-enough-for-inline-test"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def render(self, computed: dict, view: dict) -> str:
        return RENDERER.render_agenda(
            computed, view, skill_dir=self.asset_root
        )

    def test_three_pressure_cases_share_one_semantic_system_and_css(self) -> None:
        ordinary = self.render(computed_case(), view_case())
        workshop = self.render(
            computed_case(workshop=True), view_case(workshop=True)
        )
        english_dense = self.render(
            computed_case(language="en", english_dense=True),
            view_case(compact=True),
        )
        styles = [
            html.partition("<style>")[2].partition("</style>")[0]
            for html in (ordinary, workshop, english_dense)
        ]
        self.assertEqual(styles[0], styles[1])
        self.assertEqual(styles[1], styles[2])
        for html in (ordinary, workshop, english_dense):
            self.assertEqual(html.count('class="agenda-page"'), 1)
            self.assertIn('class="brand-header"', html)
            self.assertIn('class="meta-strip" data-meta-count="5"', html)
            self.assertIn('class="agenda-panel"', html)
            self.assertIn('class="support-area"', html)
            self.assertNotRegex(
                html,
                r'class="[^"]*(?:layout-standard|layout-feature|layout-marathon)',
            )
        self.assertIn('data-language="en"', english_dense)
        self.assertNotRegex(english_dense, r"[\u4e00-\u9fff]")
        self.assertNotIn("marathon-flow", english_dense)

    def test_empty_optional_metadata_does_not_render_empty_items(self) -> None:
        computed = computed_case()
        computed["meeting"]["word_of_day"] = "  "
        computed["meeting"]["manager"] = None
        html = self.render(computed, view_case())

        self.assertIn('class="meta-strip" data-meta-count="3"', html)
        self.assertEqual(html.count('class="meta-item '), 3)
        self.assertIn('class="meta-item date"', html)
        self.assertIn('class="meta-item time"', html)
        self.assertIn('class="meta-item location"', html)
        self.assertIn("2026-09-02", html)
        self.assertIn("19:30-21:30", html)
        self.assertIn("海城市创新中心 3F · 山海厅", html)
        self.assertNotIn("今日一词", html)
        self.assertNotIn("会议经理", html)
        self.assertNotRegex(html, r'<span class="meta-value">\s*</span>')

    def test_metadata_strip_uses_explicit_three_four_and_five_item_layouts(self) -> None:
        three = computed_case()
        three["meeting"]["word_of_day"] = ""
        three["meeting"]["manager"] = ""
        four = computed_case()
        four["meeting"]["manager"] = ""
        five = computed_case()

        for count, computed in ((3, three), (4, four), (5, five)):
            html = self.render(computed, view_case())
            self.assertIn(f'data-meta-count="{count}"', html)
            self.assertEqual(html.count('class="meta-item '), count)

        css = (ROOT / "assets" / "agenda.css").read_text(encoding="utf-8")
        for count in (3, 4, 5):
            self.assertIn(f'.meta-strip[data-meta-count="{count}"]', css)
        self.assertRegex(
            css,
            r'data-meta-count="3"\][^{]*\{[^}]*2\.15fr',
        )
        self.assertRegex(
            css,
            r'data-meta-count="4"\][^{]*\{[^}]*2\.05fr',
        )
        self.assertRegex(
            css,
            r'data-meta-count="5"\][^{]*\{[^}]*2\.15fr',
        )

    def test_renderer_rejects_bilingual_v3_facts(self) -> None:
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError,
            "V3 agenda.computed.club.language must be zh or en",
        ):
            self.render(computed_case(language="bilingual"), view_case())

    def test_sixty_minute_feature_is_compact_emphasis_not_area_allocation(self) -> None:
        html = self.render(
            computed_case(workshop=True), view_case(workshop=True)
        )
        feature_tag = re.search(
            r'<div class="([^"]*feature-clear[^"]*)" data-item-id="special:1">',
            html,
        )
        self.assertIsNotNone(feature_tag)
        self.assertIn("60 min", html)
        self.assertNotIn("data-minutes", html)
        self.assertNotIn("duration-ratio", html)
        self.assertNotIn("fill-height", html)
        self.assertIn('data-density="compact"', html)
        self.assertIn('data-text-scale="large"', html)

    def test_verbose_timer_bands_are_visually_shortened_without_mutating_facts(self) -> None:
        computed = computed_case()
        timer = next(
            block
            for block in computed["support_blocks"]
            if block["id"] == "timer_rules"
        )
        timer["entries"][0]["label"] = "3分钟及以下"
        timer["entries"][1]["label"] = "超过3分钟至10分钟"
        timer["entries"][2]["label"] = "10分钟以上"
        before = deepcopy(computed)
        html = self.render(computed, view_case())
        self.assertIn(">≤3分</strong>", html)
        self.assertIn(">3-10分</strong>", html)
        self.assertIn(">≥10分</strong>", html)
        self.assertIn('title="超过3分钟至10分钟"', html)
        self.assertEqual(computed, before)

    def test_renderer_does_not_mutate_facts_or_view(self) -> None:
        computed = computed_case(workshop=True)
        view = view_case(workshop=True)
        before_computed = deepcopy(computed)
        before_view = deepcopy(view)
        self.render(computed, view)
        self.assertEqual(computed, before_computed)
        self.assertEqual(view, before_view)

    def test_noncontiguous_section_runs_keep_real_order_and_local_ranges(self) -> None:
        computed = computed_case()
        first = deepcopy(computed["timeline"][0])
        first.update(
            {
                "id": "rules:return",
                "label": "补充规则",
                "start": "20:04",
                "end": "20:05",
                "section": "opening",
            }
        )
        computed["timeline"].insert(-1, first)
        html = self.render(computed, view_case())
        first_rules = html.index('data-item-id="rules"')
        speech = html.index('data-item-id="speech:1"')
        returned_rules = html.index('data-item-id="rules:return"')
        closing = html.index('data-item-id="closing"')
        self.assertLess(first_rules, speech)
        self.assertLess(speech, returned_rules)
        self.assertLess(returned_rules, closing)
        self.assertIn("19:30-19:36", html)
        self.assertIn("20:04-20:05", html)
        self.assertNotIn("19:30-20:05", html)

    def test_html_is_self_contained_and_does_not_leak_machine_paths(self) -> None:
        html = self.render(computed_case(), view_case())
        self.assertIn("data:font/woff2;base64,", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertNotIn("file://", html)
        self.assertNotIn(str(self.asset_root), html)
        self.assertNotIn("/Users/", html)
        self.assertNotIn("url(./files/", html)
        self.assertNotIn('@import url("./fonts/', html)

    def test_only_contract_density_names_exist_in_shared_css(self) -> None:
        css = (ROOT / "assets" / "agenda.css").read_text(encoding="utf-8")
        self.assertIn('data-density="comfortable"', css)
        self.assertIn('data-density="balanced"', css)
        self.assertIn('data-density="compact"', css)
        self.assertNotIn('data-density="dense"', css)
        self.assertNotIn("file://", css)
        self.assertNotIn("/Users/", css)

    def test_pathways_requires_real_timeline_data(self) -> None:
        computed = computed_case()
        view = view_case()
        view["display_columns"] = [
            "time",
            "activity",
            "owner",
            "pathways",
            "duration",
        ]
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "has no real data"
        ):
            RENDERER.validate_view(computed, view)

    def test_project_is_an_independent_auxiliary_column_not_pathways(self) -> None:
        computed = computed_case()
        computed["timeline"][0]["project"] = "PM L1"
        view = view_case()
        view["display_columns"] = [
            "time",
            "activity",
            "owner",
            "project",
            "duration",
        ]
        html = self.render(computed, view)
        self.assertIn("PM L1", html)
        self.assertIn("aux-count-1", html)

        view["display_columns"][3] = "pathways"
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "has no real data"
        ):
            RENDERER.validate_view(computed, view)

    def test_component_flow_must_include_each_component_exactly_once(self) -> None:
        computed = computed_case()
        view = view_case()
        view["component_flow"]["background"].remove("meeting_boundaries")
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "missing components: meeting_boundaries"
        ):
            RENDERER.validate_view(computed, view)

        view = view_case()
        view["component_flow"]["background"].append("backstage")
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "appears more than once"
        ):
            RENDERER.validate_view(computed, view)

    def test_backstage_must_remain_an_operations_component(self) -> None:
        computed = computed_case()
        view = view_case()
        view["component_flow"]["operations"].remove("backstage")
        view["component_flow"]["background"].insert(0, "backstage")
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "belongs in operations"
        ):
            RENDERER.validate_view(computed, view)

    def test_unknown_emphasis_and_forbidden_layout_are_rejected(self) -> None:
        computed = computed_case()
        view = view_case()
        view["content_emphasis"] = {
            "item_id": "missing:1",
            "strength": "clear",
        }
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "does not exist in timeline"
        ):
            RENDERER.validate_view(computed, view)

        view = view_case()
        view["layout"] = "workshop"
        with self.assertRaisesRegex(RENDERER.AgendaRenderError, "forbidden"):
            RENDERER.validate_view(computed, view)

    def test_dense_alias_is_rejected_instead_of_silently_mapped(self) -> None:
        view = view_case()
        view["density"] = "dense"
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError,
            "comfortable, balanced, or compact",
        ):
            RENDERER.validate_view(computed_case(), view)

    def test_legacy_unmaterialized_standard_copy_is_not_invented(self) -> None:
        computed = computed_case()
        computed.pop("support_blocks")
        with self.assertRaisesRegex(
            RENDERER.AgendaRenderError, "has no materialized content"
        ):
            self.render(computed, view_case())

    def test_user_text_is_escaped_without_becoming_markup(self) -> None:
        computed = computed_case()
        computed["timeline"][0]["owner"] = "<script>alert(1)</script>"
        html = self.render(computed, view_case())
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main()
