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

RUNNER_SPEC = importlib.util.spec_from_file_location(
    "agenda_runner_for_renderer_tests", ROOT / "scripts" / "run_agenda.py"
)
assert RUNNER_SPEC and RUNNER_SPEC.loader
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(RUNNER)

EXPORTER_SPEC = importlib.util.spec_from_file_location(
    "agenda_exporter_for_renderer_tests", ROOT / "scripts" / "export_a4.py"
)
assert EXPORTER_SPEC and EXPORTER_SPEC.loader
EXPORTER = importlib.util.module_from_spec(EXPORTER_SPEC)
EXPORTER_SPEC.loader.exec_module(EXPORTER)


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
    bilingual_dense: bool = False,
) -> dict:
    labels = (
        [
            ("rules", "Meeting Rules / 规则介绍", "Nina 宁娜", 2, "opening"),
            ("president", "President's Opening / 会长致辞", "Leo 李昂", 3, "opening"),
            ("speech:1", "Prepared Speech 1 / 备稿演讲 1", "Ethan 易辰", 7, "first_half"),
            ("speech:2", "Prepared Speech 2 / 备稿演讲 2", "Luna 陆娜", 7, "first_half"),
            ("speech:3", "Prepared Speech 3 / 备稿演讲 3", "Sean 沈言", 7, "first_half"),
            ("evaluation:1", "Evaluation 1 / 备稿点评 1", "Iris 艾瑞丝", 3, "second_half"),
            ("evaluation:2", "Evaluation 2 / 备稿点评 2", "Owen 欧文", 3, "second_half"),
            ("evaluation:3", "Evaluation 3 / 备稿点评 3", "Ruby 如冰", 3, "second_half"),
            ("closing", "Closing Remarks / 闭幕致辞", "Leo 李昂", 2, "closing"),
        ]
        if bilingual_dense
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

    blocks = support_blocks(include_club_intro=workshop)
    selected = [block["id"] for block in blocks]
    return {
        "schema_version": 3,
        "club": {
            "name": (
                "星桥双语头马俱乐部"
                if bilingual_dense
                else "晨光 AI Lab 头马俱乐部"
                if workshop
                else "晨曦头马演讲俱乐部"
            ),
            "default_location": "海城市创新中心 3F · 山海厅",
            "language": language,
        },
        "meeting": {
            "number": "42" if workshop else "18",
            "date": "2026-09-02",
            "location": "海城市创新中心 3F · 山海厅",
            "theme": (
                "AI Skill 深度实战"
                if workshop
                else "Speak Beyond Borders｜越过边界"
                if bilingual_dense
                else "把复杂的事，讲得简单"
            ),
            "word_of_day": "如虎添翼" if workshop else "Clarity · 澄明",
            "manager": "林夏" if workshop else "Lily 林",
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
        "backstage": [
            {"label": "拍照官", "person": "舒文"},
            {"label": "场控 / PPT", "person": "望舒"},
        ],
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
        bilingual = self.render(
            computed_case(language="bilingual", bilingual_dense=True),
            view_case(compact=True),
        )
        styles = [
            html.partition("<style>")[2].partition("</style>")[0]
            for html in (ordinary, workshop, bilingual)
        ]
        self.assertEqual(styles[0], styles[1])
        self.assertEqual(styles[1], styles[2])
        for html in (ordinary, workshop, bilingual):
            self.assertEqual(html.count('class="agenda-page"'), 1)
            self.assertIn('class="brand-header"', html)
            self.assertIn('class="agenda-panel"', html)
            self.assertIn('class="support-area"', html)
            self.assertNotRegex(
                html,
                r'class="[^"]*(?:layout-standard|layout-feature|layout-marathon)',
            )
        self.assertIn('data-language="bilingual"', bilingual)
        self.assertNotIn("marathon-flow", bilingual)

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

    def test_html_requires_and_embeds_real_visual_audit(self) -> None:
        html = self.render(computed_case(), view_case())

        self.assertIn('<meta name="agenda-visual-audit" content="required">', html)
        self.assertIn('id="agenda-audit-result"', html)
        self.assertIn("page_height", html)
        self.assertIn("outside_page", html)
        self.assertIn("font_missing", html)

    def test_only_contract_density_names_exist_in_shared_css(self) -> None:
        css = (ROOT / "assets" / "agenda.css").read_text(encoding="utf-8")
        self.assertIn('data-density="comfortable"', css)
        self.assertIn('data-density="balanced"', css)
        self.assertIn('data-density="compact"', css)
        self.assertNotIn('data-density="dense"', css)
        self.assertNotIn("file://", css)
        self.assertNotIn("/Users/", css)

    def test_five_background_cards_fit_the_existing_two_row_grid(self) -> None:
        spans = RENDERER._span_plan(
            "background",
            [
                "toastmasters_intro",
                "meeting_boundaries",
                "join_info",
                "optional_sessions",
                "club_facts",
            ],
        )
        self.assertEqual(spans, [2, 2, 1, 1, 2])
        self.assertEqual(sum(spans[:2]), 4)
        self.assertEqual(sum(spans[2:]), 4)

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


class V3AgendaBrowserRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chrome = EXPORTER.find_chrome()

    def test_bilingual_clear_feature_accepts_half_minute_duration(self) -> None:
        if not self.chrome:
            self.skipTest("Chrome/Chromium is not available")

        computed = computed_case(language="bilingual", bilingual_dense=True)
        computed["timeline"].insert(
            2,
            {
                "id": "special:1",
                "type": "special",
                "label": "Member Onboarding Demo / 新会员入门演示",
                "owner": "Grace",
                "section": "first_half",
                "details": [],
                "duration": 12.5,
                "start": "19:36",
                "end": "19:48:30",
            },
        )
        view = view_case(compact=True)
        view["content_emphasis"] = {
            "item_id": "special:1",
            "strength": "clear",
        }
        source = RENDERER.render_agenda(computed, view, skill_dir=ROOT)
        source = RUNNER.stabilize_headless_visual_audit(source)

        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(source, encoding="utf-8")
            report = EXPORTER.run_visual_audit(self.chrome, html_path)

        self.assertIsNotNone(report)
        assert report is not None
        self.assertIs(report.get("ok"), True)


if __name__ == "__main__":
    unittest.main()
