from __future__ import annotations

import base64
import importlib.util
import json
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agenda_builder", ROOT / "scripts" / "build_agenda.py")
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def example() -> dict:
    return json.loads((ROOT / "examples" / "meeting.example.json").read_text(encoding="utf-8"))


class AgendaBuilderTests(unittest.TestCase):
    def test_standard_example_closes_exactly(self) -> None:
        result, errors, warnings = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(result["computed"]["total_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")
        durations = {row["type"]: row["duration"] for row in result["timeline"]}
        self.assertEqual(durations["table_topics_evaluation"], durations["table_topics"] / 2)
        self.assertEqual(durations["president_closing"], 2)
        auto_durations = [
            row["duration"]
            for row in result["timeline"]
            if row.get("computed_flexible")
        ]
        self.assertTrue(all(isinstance(value, int) for value in auto_durations))

    def test_role_absence_removes_triggered_sections(self) -> None:
        data = example()
        data["roles"] = [
            row for row in data["roles"] if row["id"] not in {"ah_counter", "grammarian"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        types = [row["type"] for row in result["timeline"]]
        self.assertNotIn("ah_counter_intro", types)
        self.assertNotIn("ah_counter_report", types)
        self.assertNotIn("grammarian_intro", types)
        self.assertNotIn("grammarian_report", types)

    def test_unresolved_present_role_blocks_final(self) -> None:
        data = example()
        next(row for row in data["roles"] if row["id"] == "timer")["person"] = None
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("timer" in error and "unresolved" in error for error in errors))

    def test_photographer_fills_photo_break_owner_without_creating_extra_row(self) -> None:
        result, errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        photo_rows = [row for row in result["timeline"] if row["type"] == "photo_break"]
        self.assertEqual(len(photo_rows), 1)
        self.assertEqual(photo_rows[0]["owner"], "成员J")
        self.assertFalse(any(row["type"] == "photographer" for row in result["timeline"]))

    def test_explicit_overrun_requires_confirmation(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 14
        data["impromptu"]["evaluation_minutes"] = 7
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 6},
        ]
        data["special_segments"] = [
            {"title": "额外工作坊", "owner": "成员K", "minutes": 10, "after": "guest_introduction"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(result["computed"]["delta_minutes"], 11)
        self.assertTrue(any("overruns" in error for error in errors))

    def test_special_segment_uses_requested_anchor(self) -> None:
        data = example()
        data["special_segments"] = [
            {"title": "AI领航", "owner": "成员K", "minutes": 5, "after": "prepared_speech:1"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        ids = [row["id"] for row in result["timeline"]]
        self.assertEqual(ids.index("special:1"), ids.index("prepared_speech:1") + 1)

    def test_layout_router_selects_standard_feature_and_marathon(self) -> None:
        standard, standard_errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(standard_errors, [])
        self.assertEqual(standard["layout"], "standard")
        self.assertEqual(standard["visual_theme"], "learning")

        feature_data = example()
        feature_data["meeting"]["theme"] = "AI 实战工作坊"
        feature_data["meeting"]["word_of_day"] = "创造"
        feature_data["special_segments"] = [
            {
                "title": "AI 实战工作坊",
                "owner": "成员K",
                "minutes": 15,
                "after": "guest_introduction",
                "details": ["先体验", "再拆解", "最后实作"],
            }
        ]
        feature, _, _ = BUILDER.build_agenda(feature_data)
        self.assertEqual(feature["layout"], "feature")
        self.assertEqual(feature["visual_theme"], "technology")
        feature_html = BUILDER.render_html(feature)
        self.assertIn("layout-feature", feature_html)
        self.assertIn("visual-technology", feature_html)
        self.assertIn('class="feature-beats"', feature_html)
        self.assertIn("先体验", feature_html)
        self.assertIn("最后实作", feature_html)

        marathon_data = example()
        marathon_data["meeting"]["end"] = "21:50"
        marathon_data["prepared_speeches"] = [
            {
                "speaker": f"演讲者{i}",
                "title": f"演讲题目{i}",
                "evaluator": f"点评人{i}",
            }
            for i in range(1, 6)
        ]
        marathon, marathon_errors, _ = BUILDER.build_agenda(marathon_data)
        self.assertEqual(marathon_errors, [])
        self.assertEqual(marathon["layout"], "marathon")
        marathon_html = BUILDER.render_html(marathon)
        self.assertIn("layout-marathon", marathon_html)

    def test_feature_highlights_long_prepared_speech_and_chooses_longest(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:43"
        data["prepared_speeches"][0]["minutes"] = 20
        data["prepared_speeches"][0]["title"] = "深度主题演讲"
        data["special_segments"] = [
            {
                "title": "短工作坊",
                "owner": "成员K",
                "minutes": 15,
                "after": "guest_introduction",
            }
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["layout"], "feature")
        self.assertEqual(result["feature_item"], "prepared_speech:1")
        rendered = BUILDER.render_html(result)
        feature_block = re.search(
            r'<tr class="feature-highlight">.*?</tr>', rendered, re.DOTALL
        )
        self.assertIsNotNone(feature_block)
        assert feature_block
        self.assertIn("深度主题演讲", feature_block.group(0))
        self.assertNotIn("短工作坊", feature_block.group(0))

    def test_feature_item_can_be_explicitly_selected(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:45"
        data["special_segments"] = [
            {
                "title": "第一个重点",
                "owner": "成员K",
                "minutes": 15,
                "after": "guest_introduction",
            },
            {
                "title": "第二个重点",
                "owner": "成员L",
                "minutes": 15,
                "after": "guest_introduction",
            },
        ]
        data["meeting"]["feature_item"] = "special:2"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["feature_item"], "special:2")

    def test_marathon_cards_bind_same_number_without_reordering_timeline(self) -> None:
        data = example()
        data["meeting"]["end"] = "21:42"
        data["prepared_speeches"] = []
        for index in range(1, 6):
            speech = {
                "speaker": f"SPEAKER_{index}",
                "title": f"TITLE_{index}",
                "evaluator": f"EVALUATOR_{index}",
            }
            if index == 2:
                speech.pop("evaluator")
                speech["evaluation_enabled"] = False
            data["prepared_speeches"].append(speech)
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        ids = [item["id"] for item in result["timeline"]]
        self.assertLess(ids.index("prepared_speech:5"), ids.index("prepared_evaluation:1"))
        rendered = BUILDER.render_html(result)
        cards = re.findall(
            r'<article class="speech-pair">.*?</article>', rendered, re.DOTALL
        )
        self.assertEqual(len(cards), 5)
        for index, card in enumerate(cards, start=1):
            self.assertIn(f"SPEAKER_{index}", card)
            self.assertIn(f"TITLE_{index}", card)
            if index == 2:
                self.assertIn('pair-evaluation missing', card)
                self.assertNotIn("EVALUATOR_3", card)
            else:
                self.assertIn(f"EVALUATOR_{index}", card)
        self.assertIn(".speech-pair:last-child:nth-child(odd)", rendered)

    def test_club_profile_keeps_only_reusable_club_facts(self) -> None:
        data = example()
        profile = BUILDER.club_profile_from_data(data)
        self.assertEqual(profile["club"]["name"], data["club"]["name"])
        self.assertEqual(
            profile["club"]["support_components"],
            data["club"]["support_components"],
        )
        self.assertNotIn("meeting", profile)
        self.assertNotIn("roles", profile)
        self.assertNotIn("prepared_speeches", profile)

    def test_stored_club_profile_path_is_stable_and_name_specific(self) -> None:
        first = BUILDER.stored_club_profile_path("星河头马演讲俱乐部")
        same = BUILDER.stored_club_profile_path("  星河头马演讲俱乐部  ")
        other = BUILDER.stored_club_profile_path("星河头马俱乐部")
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)
        self.assertEqual(first.parent, BUILDER.PROFILE_ROOT)

    def test_saved_profile_copies_vpm_qr_into_stable_asset_folder(self) -> None:
        data = example()
        data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "club-profile.json"
            BUILDER.write_club_profile(
                data,
                destination,
                source_dir=ROOT / "examples",
            )
            profile = json.loads(destination.read_text(encoding="utf-8"))
            stored_qr = profile["club"]["vpm_qr_image"]
            self.assertFalse(Path(stored_qr).is_absolute())
            copied = destination.parent / stored_qr
            self.assertTrue(copied.is_file())
            self.assertEqual(
                copied.read_bytes(),
                (ROOT / "assets" / "toastmasters-logo.png").read_bytes(),
            )

    def test_layout_and_visual_theme_can_be_explicitly_overridden(self) -> None:
        data = example()
        data["meeting"]["feature_item"] = None
        data["meeting"]["layout"] = "feature"
        data["meeting"]["visual_theme"] = "wellness"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["layout"], "feature")
        self.assertEqual(result["visual_theme"], "wellness")

        data["meeting"]["layout"] = "unknown"
        data["meeting"]["visual_theme"] = "unknown"
        _, invalid_errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("meeting.layout must be" in error for error in invalid_errors))
        self.assertTrue(any("meeting.visual_theme must be" in error for error in invalid_errors))

    def test_editorial_renderer_preserves_computed_timeline_and_inlines_assets(self) -> None:
        result, errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        self.assertEqual(BUILDER.resolve_html_renderer(result), "editorial")
        rendered = BUILDER.render_output_html(result, "editorial")
        self.assertIn('id="agenda-audit-result"', rendered)
        self.assertIn("data:image/png;base64,", rendered)
        self.assertIn('<svg class="ti ', rendered)
        self.assertNotIn("assets/icons/", rendered)
        self.assertNotIn("{{BODY}}", rendered)
        previous = -1
        for item in result["timeline"]:
            position = rendered.find(item["label"])
            self.assertGreater(position, previous, item["id"])
            previous = position

        pure = example()
        pure["club"]["support_components"] = []
        pure_result, pure_errors, _ = BUILDER.build_agenda(pure)
        self.assertEqual(pure_errors, [])
        self.assertEqual(BUILDER.resolve_html_renderer(pure_result), "classic")

        feature = example()
        feature["special_segments"] = [
            {
                "title": "工作坊",
                "owner": "成员K",
                "minutes": 15,
                "after": "guest_introduction",
            }
        ]
        feature_result, feature_errors, _ = BUILDER.build_agenda(feature)
        self.assertEqual(feature_errors, [])
        self.assertEqual(feature_result["layout"], "feature")
        self.assertEqual(BUILDER.resolve_html_renderer(feature_result), "classic")

    def test_editorial_renderer_rejects_bilingual_until_a_specific_layout_exists(self) -> None:
        data = example()
        data["club"]["language"] = "bilingual"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(ValueError, "supports zh or en"):
            BUILDER.render_output_html(result, "editorial")

    def test_editorial_auto_falls_back_instead_of_dropping_unsupported_content(self) -> None:
        qr_data = example()
        qr_data["club"]["support_components"].append("vpm_qr")
        qr_data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        qr_result, qr_errors, _ = BUILDER.build_agenda(
            qr_data, source_dir=ROOT / "examples"
        )
        self.assertEqual(qr_errors, [])
        self.assertEqual(BUILDER.resolve_html_renderer(qr_result), "classic")
        with self.assertRaisesRegex(ValueError, "QR components"):
            BUILDER.render_output_html(qr_result, "editorial")

        crowded = example()
        crowded["club"]["custom_support_blocks"] = [
            {"id": f"custom-{index}", "title": f"自定义{index}", "lines": ["内容"]}
            for index in range(1, 4)
        ]
        crowded_result, crowded_errors, _ = BUILDER.build_agenda(crowded)
        self.assertEqual(crowded_errors, [])
        self.assertEqual(BUILDER.resolve_html_renderer(crowded_result), "classic")
        with self.assertRaisesRegex(ValueError, "at most 4 bottom"):
            BUILDER.render_output_html(crowded_result, "editorial")

        left_block = example()
        left_block["club"]["custom_support_blocks"] = [
            {
                "id": "left-note",
                "title": "侧栏说明",
                "lines": ["不能改位置"],
                "placement": "left",
            }
        ]
        left_result, left_errors, _ = BUILDER.build_agenda(left_block)
        self.assertEqual(left_errors, [])
        self.assertEqual(BUILDER.resolve_html_renderer(left_result), "classic")
        with self.assertRaisesRegex(ValueError, "placement:left"):
            BUILDER.render_output_html(left_result, "editorial")

    def test_editorial_does_not_reinterpret_slogan_or_values_custom_blocks(self) -> None:
        data = example()
        data["club"]["custom_support_blocks"] = [
            {
                "id": "slogan",
                "title": "口号备选",
                "lines": ["第一行", "第二行"],
                "placement": "bottom",
            }
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(BUILDER.resolve_html_renderer(result), "editorial")
        rendered = BUILDER.render_output_html(result, "editorial")
        self.assertIn("口号备选", rendered)
        self.assertIn("第一行", rendered)
        self.assertIn("第二行", rendered)

    def test_editorial_uses_shared_boundaries_and_escapes_invalid_date(self) -> None:
        data = example()
        data["meeting"]["date"] = '<img src=x onerror="alert(1)">'
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        editorial = BUILDER.render_output_html(result, "editorial")
        classic = BUILDER.render_html(result)
        for expected in ("四类禁忌", "政治、宗教、色情或传销"):
            self.assertIn(expected, editorial)
            self.assertIn(expected, classic)
        self.assertNotIn('<img src=x onerror="alert(1)">', editorial)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", editorial)

    def test_editorial_keeps_noncontiguous_phase_runs_in_original_order(self) -> None:
        result, errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        result["timeline"][0]["section"] = "opening"
        result["timeline"][1]["section"] = "first_half"
        result["timeline"][2]["section"] = "opening"
        rendered = BUILDER.render_output_html(result, "editorial")
        labels = [result["timeline"][index]["label"] for index in range(3)]
        positions = [rendered.find(label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_optional_theme_image_is_embedded_without_changing_logo(self) -> None:
        data = example()
        data["meeting"]["theme_image"] = "../assets/toastmasters-logo.png"
        result, errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertEqual(errors, [])
        self.assertTrue(result["_assets"]["theme_art_data_uri"].startswith("data:image/png"))
        rendered = BUILDER.render_html(result)
        self.assertIn("has-theme-art", rendered)
        self.assertIn("class='theme-art'", rendered)
        self.assertIn("class='logo'", rendered)

        data["meeting"]["theme_image"] = "missing-theme.png"
        _, missing_errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertTrue(any("meeting.theme_image does not exist" in error for error in missing_errors))

    def test_missing_end_defaults_to_two_hours(self) -> None:
        data = example()
        del data["meeting"]["end"]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["declared_window_minutes"], 120)
        self.assertEqual(result["computed"]["final_end"], "21:30")

    def test_exact_approved_overtime_is_honored(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 14
        data["impromptu"]["evaluation_minutes"] = 7
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 6},
        ]
        data["special_segments"] = [
            {"title": "额外工作坊", "owner": "成员K", "minutes": 10, "after": "guest_introduction"}
        ]
        data["meeting"]["approved_overtime_minutes"] = 11
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["approved_overtime_minutes"], 11)
        self.assertEqual(result["computed"]["final_end"], "21:41")
        self.assertEqual(result["computed"]["status"], "exact_with_approved_overtime")

    def test_bilingual_labels_and_html_escape(self) -> None:
        data = example()
        data["club"]["language"] = "bilingual"
        data["meeting"]["theme"] = "<script>alert(1)</script>"
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertIn("规则介绍 / Meeting Rules", result["timeline"][0]["label"])
        rendered = BUILDER.render_html(result)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("会议流程 / Agenda", rendered)
        markdown = BUILDER.render_markdown(result)
        self.assertIn("主题 / Theme", markdown)

    def test_missing_evaluator_requires_explicit_decision(self) -> None:
        data = example()
        del data["prepared_speeches"][0]["evaluator"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("requires an evaluator" in error for error in errors))

    def test_explicit_evaluation_disabled_omits_evaluation(self) -> None:
        data = example()
        speech = data["prepared_speeches"][0]
        speech.pop("evaluator")
        speech["evaluation_enabled"] = False
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertFalse(any(row["id"] == "prepared_evaluation:1" for row in result["timeline"]))

    def test_sparse_meeting_does_not_inflate_break_and_sharing(self) -> None:
        data = example()
        data["prepared_speeches"] = []
        data["impromptu"] = None
        data["roles"] = [
            row
            for row in data["roles"]
            if row["id"] not in {"timer", "ah_counter", "grammarian", "general_evaluator"}
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(errors)
        flexible = {
            row["type"]: row["duration"]
            for row in result["timeline"]
            if row["type"] in {"photo_break", "sharing"}
        }
        self.assertLessEqual(flexible["photo_break"], 15)
        self.assertLessEqual(flexible["sharing"], 20)

    def test_extreme_auto_break_or_sharing_duration_warns(self) -> None:
        warnings: list[str] = []
        BUILDER.validate_auto_flexible_durations(
            [
                {"type": "photo_break", "duration": 13, "computed_flexible": True},
                {"type": "sharing", "duration": 15, "computed_flexible": True},
            ],
            warnings,
        )
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("photo_break" in warning for warning in warnings))
        self.assertTrue(any("sharing" in warning for warning in warnings))

    def test_equal_start_and_end_is_invalid(self) -> None:
        data = example()
        data["meeting"]["end"] = data["meeting"]["start"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("must differ" in error for error in errors))

    def test_stale_overtime_approval_is_rejected(self) -> None:
        data = example()
        data["meeting"]["approved_overtime_minutes"] = 10
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("no longer matches" in error for error in errors))

    def test_dense_agenda_is_blocked_instead_of_crossing_a4_pages(self) -> None:
        data = example()
        data["meeting"]["end"] = "23:30"
        data["prepared_speeches"] = [
            {
                "speaker": f"演讲者{i}",
                "title": f"演讲标题{i}",
                "evaluator": f"点评人{i}",
            }
            for i in range(1, 13)
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("single-page A4 capacity exceeded" in error for error in errors))
        self.assertEqual(result["computed"]["row_count"], 41)
        self.assertEqual(result["computed"]["page_count"], 1)

    def test_recommended_support_components_stay_on_one_page(self) -> None:
        result, errors, _ = BUILDER.build_agenda(example())
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["page_count"], 1)
        rendered = BUILDER.render_html(result)
        self.assertIn('<meta name="agenda-page-count" content="1">', rendered)
        self.assertIn("时间官规则", rendered)
        self.assertIn("当届官员团队", rendered)
        self.assertIn("四类禁忌", rendered)
        self.assertEqual(rendered.count('class="page '), 1)

    def test_empty_support_components_keep_agenda_only(self) -> None:
        data = example()
        data["club"]["support_components"] = []
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["page_count"], 1)
        rendered = BUILDER.render_html(result)
        self.assertNotIn('<main class="page support-page', rendered)
        self.assertTrue(any(row["type"] == "president_opening" for row in result["timeline"]))

    def test_meeting_support_components_fully_override_club_selection(self) -> None:
        data = example()
        data["meeting"]["support_components"] = []
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["support_components"], [])
        self.assertEqual(result["computed"]["page_count"], 1)

    def test_full_english_officer_titles_are_accepted(self) -> None:
        data = example()
        data["club"]["officers"] = [
            {"role": "President", "name": "Member A"},
            {"role": "Vice President Education", "name": "Member B"},
            {"role": "Vice President Membership", "name": "Member C"},
            {"role": "Vice President Public Relations", "name": "Member D"},
            {"role": "Secretary", "name": "Member E"},
            {"role": "Treasurer", "name": "Member F"},
            {"role": "Sergeant at Arms", "name": "Member G"},
        ]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])

    def test_support_component_selection_is_required(self) -> None:
        data = example()
        del data["club"]["support_components"]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("support_components must be an explicit array" in error for error in errors))

    def test_selected_officer_component_requires_core_team(self) -> None:
        data = example()
        data["club"]["officers"] = data["club"]["officers"][:-1]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("missing core roles" in error for error in errors))

    def test_selected_intro_components_require_text(self) -> None:
        data = example()
        data["club"]["support_components"] = ["club_intro", "join_info"]
        data["club"].pop("club_intro")
        data["club"].pop("join_info")
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("club.club_intro is empty" in error for error in errors))
        self.assertTrue(any("club.join_info is empty" in error for error in errors))

    def test_selected_qr_components_embed_user_images(self) -> None:
        data = example()
        data["club"]["support_components"] = [
            "timer_rules",
            "toastmasters_intro",
            "meeting_boundaries",
            "officers",
            "club_intro",
            "join_info",
            "vpm_qr",
            "voting_qr",
        ]
        data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        data["meeting"]["voting_qr_image"] = "../assets/toastmasters-logo.png"
        result, errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertEqual(errors, [])
        self.assertTrue(result["club"]["vpm_qr_present"])
        self.assertTrue(result["meeting"]["voting_qr_present"])
        rendered = BUILDER.render_html(result)
        self.assertIn("入会咨询", rendered)
        self.assertIn("本期投票", rendered)
        encoded = result["_assets"]["vpm_qr_data_uri"].split(",", 1)[1]
        self.assertEqual(
            base64.b64decode(encoded),
            (ROOT / "assets" / "toastmasters-logo.png").read_bytes(),
        )

    def test_selected_qr_component_rejects_missing_image(self) -> None:
        data = example()
        data["club"]["support_components"] = ["vpm_qr"]
        data["club"]["vpm_qr_image"] = "missing.png"
        _, errors, _ = BUILDER.build_agenda(data, source_dir=ROOT / "examples")
        self.assertTrue(any("does not exist" in error for error in errors))

    def test_custom_support_blocks_use_the_same_single_page_layout(self) -> None:
        data = example()
        data["club"]["support_components"] = []
        data["club"]["custom_support_blocks"] = [
            {
                "id": "pathways",
                "title": "Pathways 教育路径",
                "lines": ["DL - 动态领导", "PM - 精通演讲", "<script>bad()</script>"],
                "placement": "auto",
            }
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["custom_support_blocks"][0]["id"], "pathways")
        rendered = BUILDER.render_html(result)
        self.assertIn("Pathways 教育路径", rendered)
        self.assertIn("DL - 动态领导", rendered)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", rendered)
        self.assertNotIn("<script>bad()</script>", rendered)
        self.assertIn("with-support", rendered)
        self.assertIn('<meta name="agenda-page-count" content="1">', rendered)

    def test_custom_support_blocks_validate_identity_content_and_placement(self) -> None:
        data = example()
        data["club"]["custom_support_blocks"] = [
            {"id": "timer_rules", "title": "重复", "lines": ["内容"]},
            {"id": "new", "title": "", "lines": [], "placement": "sideways"},
        ]
        _, errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(any("reserved custom support block id" in error for error in errors))
        self.assertTrue(any("missing title" in error for error in errors))
        self.assertTrue(any("has no content" in error for error in errors))
        self.assertTrue(any("placement must be auto" in error for error in errors))

    def test_meeting_custom_support_blocks_fully_override_club_blocks(self) -> None:
        data = example()
        data["club"]["custom_support_blocks"] = [
            {"id": "usual", "title": "常用块", "lines": ["长期内容"]}
        ]
        data["meeting"]["custom_support_blocks"] = []
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["custom_support_blocks"], [])

    def test_half_minute_overtime_requires_exact_approval(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 14
        data["impromptu"]["evaluation_minutes"] = 7
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 4},
            {"id": "sharing", "minutes": 6},
        ]
        data["special_segments"] = [
            {
                "title": "额外工作坊",
                "owner": "成员K",
                "minutes": 10.5,
                "after": "guest_introduction",
            }
        ]
        data["meeting"]["approved_overtime_minutes"] = 11.5
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["delta_minutes"], 11.5)
        self.assertEqual(result["computed"]["final_end"], "21:41:30")
        self.assertEqual(result["computed"]["status"], "exact_with_approved_overtime")

        data["meeting"]["approved_overtime_minutes"] = 11
        _, mismatch_errors, _ = BUILDER.build_agenda(data)
        self.assertTrue(
            any("approve exactly 11.5 minutes" in error for error in mismatch_errors)
        )

    def test_half_minute_start_defaults_across_midnight(self) -> None:
        data = example()
        data["meeting"]["start"] = "23:30:30"
        del data["meeting"]["end"]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["declared_end"], "01:30:30")
        self.assertEqual(result["computed"]["final_end"], "01:30:30")

    def test_half_minute_transitions_accumulate_without_removing_others(self) -> None:
        data = example()
        data["standard_overrides"] = [
            {"id": "guest_introduction", "transition_after": 0.5},
            {"id": "awards", "transition_after": 0.5},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["transition_minutes"], 18)
        self.assertEqual(result["computed"]["total_minutes"], 120)
        guest_index = next(
            index
            for index, row in enumerate(result["timeline"])
            if row["type"] == "guest_introduction"
        )
        self.assertEqual(result["timeline"][guest_index]["transition_after"], 0.5)
        self.assertTrue(result["timeline"][guest_index + 1]["start"].endswith(":30"))

    def test_role_triggered_items_accept_individual_transition_overrides(self) -> None:
        data = example()
        data["transition_overrides"] = [
            {"id": "prepared_evaluation:1", "minutes": 0.5},
            {"id": "table_topics_evaluation", "minutes": 0.5},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        by_id = {row["id"]: row for row in result["timeline"]}
        self.assertEqual(by_id["prepared_evaluation:1"]["transition_after"], 0.5)
        self.assertEqual(by_id["table_topics_evaluation"]["transition_after"], 0.5)
        self.assertEqual(result["computed"]["transition_minutes"], 18)
        self.assertEqual(result["computed"]["total_minutes"], 120)

    def test_auto_evaluation_does_not_absorb_an_unrelated_time_gap(self) -> None:
        data = example()
        data["impromptu"]["minutes"] = 10
        data["standard_overrides"] = [
            {"id": "photo_break", "minutes": 5},
            {"id": "sharing", "minutes": 6},
        ]
        data["transition_overrides"] = [
            {"id": "prepared_evaluation:1", "minutes": 0.5},
            {"id": "prepared_evaluation:2", "minutes": 0.5},
            {"id": "prepared_evaluation:3", "minutes": 0.5},
            {"id": "table_topics_evaluation", "minutes": 0.5},
            {"id": "grammarian_report", "minutes": 0.5},
            {"id": "ah_counter_report", "minutes": 0.5},
            {"id": "timer_report", "minutes": 0.5},
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(result["computed"]["delta_minutes"], -8.5)
        self.assertTrue(any("8.5 unexplained minutes" in error for error in errors))
        evaluation = next(
            row
            for row in result["timeline"]
            if row["type"] == "table_topics_evaluation"
        )
        self.assertEqual(evaluation["duration"], 5)

    def test_transition_override_rejects_missing_or_duplicate_targets(self) -> None:
        missing = example()
        missing["transition_overrides"] = [
            {"id": "not-a-real-item", "minutes": 0.5}
        ]
        _, missing_errors, _ = BUILDER.build_agenda(missing)
        self.assertTrue(any("references missing item" in error for error in missing_errors))

        duplicate = example()
        duplicate["standard_overrides"] = [
            {"id": "guest_introduction", "transition_after": 0.5}
        ]
        duplicate["transition_overrides"] = [
            {"id": "guest_introduction", "minutes": 0.5}
        ]
        _, duplicate_errors, _ = BUILDER.build_agenda(duplicate)
        self.assertTrue(any("defined twice" in error for error in duplicate_errors))

    def test_all_explicit_time_fields_accept_half_minute_increments(self) -> None:
        data = example()
        data["standard_overrides"] = [
            {"id": "guest_introduction", "minutes": 4.5, "transition_after": 0.5}
        ]
        data["prepared_speeches"][0]["minutes"] = 6.5
        data["prepared_speeches"][0]["evaluation_minutes"] = 2.5
        data["impromptu"]["minutes"] = 10.5
        data["impromptu"]["evaluation_minutes"] = 5.5
        data["special_segments"] = [
            {
                "title": "30秒提醒",
                "owner": "成员K",
                "minutes": 0.5,
                "after": "guest_introduction",
                "transition_after": 0.5,
            }
        ]
        result, errors, _ = BUILDER.build_agenda(data)
        self.assertEqual(errors, [])
        self.assertEqual(result["computed"]["total_minutes"], 120)
        first_speech = next(
            row for row in result["timeline"] if row["id"] == "prepared_speech:1"
        )
        self.assertEqual(first_speech["duration"], 6.5)
        markdown = BUILDER.render_markdown(result)
        rendered = BUILDER.render_html(result)
        self.assertIn("6.5 min", markdown)
        self.assertIn("0.5 min", rendered)
        self.assertNotIn("2.0 min", rendered)

    def test_invalid_half_minute_values_are_rejected(self) -> None:
        for invalid in (0.25, True, "0.5", -0.5, float("nan"), float("inf")):
            with self.subTest(invalid=invalid):
                data = example()
                data["standard_overrides"] = [
                    {"id": "guest_introduction", "transition_after": invalid}
                ]
                _, errors, _ = BUILDER.build_agenda(data)
                self.assertTrue(
                    any("0.5-minute increments" in error for error in errors)
                )


if __name__ == "__main__":
    unittest.main()
