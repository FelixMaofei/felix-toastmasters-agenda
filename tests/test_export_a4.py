from __future__ import annotations

import importlib.util
import json
import os
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_exporter", ROOT / "scripts" / "export_a4.py"
)
assert SPEC and SPEC.loader
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)

BUILDER_SPEC = importlib.util.spec_from_file_location(
    "agenda_builder_for_export_tests", ROOT / "scripts" / "build_agenda.py"
)
assert BUILDER_SPEC and BUILDER_SPEC.loader
BUILDER = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(BUILDER)


class AgendaExporterTests(unittest.TestCase):
    def test_declared_multi_page_html_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(
                '<meta name="agenda-page-count" content="2">', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "exactly 1 A4 page"):
                EXPORTER.expected_page_count(html_path)

    def test_single_page_html_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(
                '<meta name="agenda-page-count" content="1">', encoding="utf-8"
            )
            self.assertEqual(EXPORTER.expected_page_count(html_path), 1)

    def test_a4_portrait_size_tolerance(self) -> None:
        self.assertTrue(EXPORTER.is_a4_portrait((595.28, 841.89)))
        self.assertFalse(EXPORTER.is_a4_portrait((612, 792)))
        self.assertFalse(EXPORTER.is_a4_portrait((841.89, 595.28)))

    def test_visual_audit_dump_is_parsed(self) -> None:
        dump = (
            '<html data-agenda-audit="ok"><body>'
            '<script id="agenda-audit-result" type="application/json">'
            '{"ok":true,"failures":[]}'
            "</script></body></html>"
        )
        self.assertEqual(
            EXPORTER.parse_visual_audit_dump(dump),
            {"ok": True, "failures": []},
        )

    def test_missing_visual_audit_result_returns_none(self) -> None:
        self.assertIsNone(EXPORTER.parse_visual_audit_dump("<html></html>"))

    def test_visual_audit_requirement_is_explicit(self) -> None:
        self.assertTrue(
            EXPORTER.visual_audit_required(
                '<meta name="agenda-visual-audit" content="required">'
            )
        )
        self.assertFalse(EXPORTER.visual_audit_required("<html></html>"))

    def test_chrome_no_sandbox_flags_are_opt_in(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(EXPORTER.chrome_compatibility_flags(), [])
        with mock.patch.dict(
            os.environ, {"AGENDA_CHROME_NO_SANDBOX": "1"}, clear=True
        ):
            self.assertEqual(
                EXPORTER.chrome_compatibility_flags(),
                ["--no-sandbox", "--disable-software-rasterizer"],
            )


class ClassicBrowserAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chrome = EXPORTER.find_chrome()
        if not cls.chrome:
            cls.source = ""
            return
        data = json.loads(
            (ROOT / "examples" / "meeting.example.json").read_text(encoding="utf-8")
        )
        data["meeting"]["theme"] = "AI 实战工作坊"
        data["meeting"]["word_of_day"] = "创造"
        data["special_segments"] = [
            {
                "title": "AI 实战工作坊",
                "owner": "成员K",
                "minutes": 15,
                "after": "guest_introduction",
                "details": ["先体验", "再拆解", "最后实作"],
            }
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        if errors:
            raise AssertionError(errors)
        if result.get("layout") != "feature":
            raise AssertionError("feature example did not select the feature layout")
        cls.source = BUILDER.render_output_html(result, "classic")

    def setUp(self) -> None:
        if not self.chrome:
            self.skipTest("Chrome/Chromium is not available")

    def audit(self, source: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(source, encoding="utf-8")
            assert self.chrome
            return EXPORTER.run_visual_audit(self.chrome, html_path) or {}

    def assert_audit_failure(self, source: str, code: str) -> None:
        with self.assertRaisesRegex(ValueError, code):
            self.audit(source)

    def test_feature_agenda_with_four_columns_passes_visual_audit(self) -> None:
        feature_row = re.search(
            r'<tr class="feature-highlight"[^>]*>.*?</tr>',
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(feature_row)
        assert feature_row
        self.assertEqual(feature_row.group(0).count("<td"), 4)
        report = self.audit(self.source)
        self.assertIs(report.get("ok"), True)

    def test_audit_rejects_feature_row_with_missing_owner_column(self) -> None:
        mutated, replacements = re.subn(
            r'<td class="feature-owner owner">.*?</td>',
            "",
            self.source,
            count=1,
            flags=re.DOTALL,
        )
        self.assertEqual(replacements, 1)
        self.assert_audit_failure(mutated, "timeline-column-count")

    def test_audit_rejects_feature_owner_alignment_mismatch(self) -> None:
        override = "<style>.feature-owner{text-align:right!important}</style>"
        mutated = self.source.replace("</head>", override + "</head>")
        self.assert_audit_failure(mutated, "owner-alignment-mismatch")


class EditorialBrowserAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chrome = EXPORTER.find_chrome()
        if not cls.chrome:
            cls.source = ""
            return
        data = json.loads(
            (ROOT / "examples" / "meeting.example.json").read_text(encoding="utf-8")
        )
        data["club"]["custom_support_blocks"] = [
            {
                "id": "optional_sessions",
                "title": "可选环节",
                "lines": ["主题演讲", "评估环节", "语言项目演练"],
            },
            {
                "id": "club_facts",
                "title": "俱乐部信息",
                "lines": [
                    "定位：帮助会员提升表达力",
                    "愿景：帮助会员成长",
                    "特色：真实、温暖、有趣",
                    "关键词：共创",
                    "价值观：正直、尊重、服务、卓越",
                ],
            },
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        if errors:
            raise AssertionError(errors)
        cls.source = BUILDER.render_output_html(result, "editorial")

        long_zh = deepcopy(data)
        long_zh["club"]["name"] = "星河城市人工智能与领导力头马演讲俱乐部"
        long_zh["club"]["default_location"] = "未来科技中心A座18楼国际会议厅"
        long_zh["meeting"]["location"] = "未来科技中心A座18楼国际会议厅"
        long_zh["meeting"]["word_of_day"] = "长期主义"
        long_result, long_errors, _ = BUILDER.build_agenda(long_zh)
        if long_errors:
            raise AssertionError(long_errors)
        long_result["visual_theme"] = "technology"
        cls.long_zh_source = BUILDER.render_output_html(long_result, "editorial")

        english = deepcopy(data)
        english["club"]["name"] = "Starlight Leadership Advanced Toastmasters Club"
        english["club"]["language"] = "en"
        english["club"]["default_location"] = "Global Innovation Center, Conference Room 1808"
        english["meeting"]["location"] = "Global Innovation Center, Conference Room 1808"
        english["meeting"]["theme"] = "Speak with clarity and courage"
        english["meeting"]["word_of_day"] = "Stewardship"
        english["meeting"]["manager"] = "Alex Morgan"
        english["meeting"]["president"] = "Jordan Lee"
        role_names = {
            "rules_host": "Taylor Reed",
            "toastmaster": "Alex Morgan",
            "timer": "Casey Young",
            "ah_counter": "Morgan Chen",
            "grammarian": "Jamie Lin",
            "guest_host": "Riley Park",
            "sharing_host": "Avery Stone",
            "general_evaluator": "Jordan Lee",
            "awards_host": "Taylor Reed",
        }
        for role in english["roles"]:
            role["person"] = role_names[role["id"]]
        english["prepared_speeches"] = [
            {
                "speaker": f"Speaker {index}",
                "title": f"Speech {index}",
                "project": "Presentation Mastery",
                "evaluator": f"Evaluator {index}",
            }
            for index in range(1, 4)
        ]
        english["impromptu"] = {
            "host": "Table Topics Host",
            "evaluator": "Table Topics Evaluator",
        }
        officer_names = (
            "Jordan Lee",
            "Alex Morgan",
            "Taylor Reed",
            "Jamie Lin",
            "Morgan Chen",
            "Casey Young",
            "Riley Park",
        )
        for officer, name in zip(english["club"]["officers"], officer_names):
            officer["name"] = name
        english["club"]["custom_support_blocks"] = [
            {
                "id": "optional_sessions",
                "title": "Optional Sessions",
                "lines": ["Theme speech", "Evaluation", "Language practice"],
            },
            {
                "id": "club_facts",
                "title": "Club Profile",
                "lines": [
                    "Positioning: practical communication and leadership",
                    "Vision: help members grow with confidence",
                    "Character: rigorous, warm and engaging",
                    "Keyword: co-creation",
                    "Values: integrity, respect, service and excellence",
                ],
            },
        ]
        english_result, english_errors, _ = BUILDER.build_agenda(english)
        if english_errors:
            raise AssertionError(english_errors)
        cls.english_source = BUILDER.render_output_html(english_result, "editorial")

    def setUp(self) -> None:
        if not self.chrome:
            self.skipTest("Chrome/Chromium is not available")

    def audit(self, source: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "agenda.html"
            html_path.write_text(source, encoding="utf-8")
            assert self.chrome
            return EXPORTER.run_visual_audit(self.chrome, html_path) or {}

    def assert_audit_failure(self, source: str, code: str) -> None:
        with self.assertRaisesRegex(ValueError, code):
            self.audit(source)

    def test_normal_editorial_agenda_passes_visual_audit(self) -> None:
        report = self.audit(self.source)
        self.assertIs(report.get("ok"), True)

    def test_long_chinese_name_and_technology_theme_pass_visual_audit(self) -> None:
        report = self.audit(self.long_zh_source)
        self.assertIs(report.get("ok"), True)

    def test_english_name_and_location_pass_visual_audit(self) -> None:
        report = self.audit(self.english_source)
        self.assertIs(report.get("ok"), True)

    def test_audit_rejects_support_bottom_collision(self) -> None:
        override = (
            "<style>.support-body{padding-bottom:0!important;display:flex!important;"
            "flex-direction:column!important;justify-content:flex-end!important}</style>"
        )
        self.assert_audit_failure(self.source.replace("</head>", override + "</head>"), "content-clearance")

    def test_audit_rejects_ragged_last_line(self) -> None:
        replacement = (
            '<div class="support-body"><p>'
            'Toastmasters International<br>A</p></div>'
        )
        mutated = re.sub(
            r'<div class="support-body">.*?</div>',
            replacement,
            self.source,
            count=1,
            flags=re.DOTALL,
        )
        self.assert_audit_failure(mutated, "ragged-last-line")

    def test_audit_rejects_table_column_drift(self) -> None:
        override = "<style>.agenda-table tbody td:nth-child(3){position:relative;left:2px}</style>"
        self.assert_audit_failure(
            self.source.replace("</head>", override + "</head>"),
            "column-edge-misalignment",
        )

    def test_audit_rejects_footer_gap(self) -> None:
        override = "<style>.footer{gap:2mm!important}</style>"
        self.assert_audit_failure(self.source.replace("</head>", override + "</head>"), "footer-gap")

    def test_audit_rejects_missing_bundled_font(self) -> None:
        without_fonts = re.sub(
            r"@font-face\s*\{.*?\}",
            "",
            self.source,
            flags=re.DOTALL,
        )
        self.assertNotIn("@font-face", without_fonts)
        self.assert_audit_failure(without_fonts, "font-not-loaded")


if __name__ == "__main__":
    unittest.main()
