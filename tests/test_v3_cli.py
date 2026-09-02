from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load_module("v3_agenda_builder", ROOT / "scripts" / "build_agenda.py")
RUNNER = load_module("v3_agenda_runner", ROOT / "scripts" / "run_agenda.py")
RENDERER = load_module(
    "v3_agenda_renderer_for_cli_tests", ROOT / "scripts" / "agenda_renderer.py"
)


def example() -> dict:
    data = json.loads(
        (ROOT / "examples" / "meeting.fixture.json").read_text(encoding="utf-8")
    )
    data["impromptu"].update({"minutes": 14, "evaluation_minutes": 7})
    data["standard_overrides"] = [
        {"id": "photo_break", "minutes": 4},
        {"id": "sharing", "minutes": 6},
    ]
    return data


def simple_example() -> dict:
    canonical = example()
    meeting = deepcopy(canonical["meeting"])
    meeting.pop("approved_overtime_minutes", None)
    return {
        "simple_version": 1,
        "club": deepcopy(canonical["club"]),
        "meeting": meeting,
        "roles": [
            {"role": row["id"], "person": row["person"]}
            for row in canonical["roles"]
        ],
        "speeches": deepcopy(canonical["prepared_speeches"]),
        "impromptu": deepcopy(canonical["impromptu"]),
        "backstage": [
            {
                "role": row["id"],
                "person": row["person"],
                "label": row["label"],
            }
            for row in canonical["backstage"]
        ],
        "special": [],
    }


def overrun_simple_example() -> dict:
    data = simple_example()
    data["impromptu"].update({"minutes": 14, "evaluation_minutes": 7})
    data["agenda_overrides"] = [
        {"id": "photo_break", "minutes": 4},
        {"id": "sharing", "minutes": 6},
    ]
    data["special"] = [
        {
            "title": "额外工作坊",
            "owner": "成员K",
            "minutes": 10,
            "after": "嘉宾介绍",
        }
    ]
    return data


def approved_canonical_overrun_example() -> dict:
    data = example()
    data["impromptu"].update({"minutes": 14, "evaluation_minutes": 7})
    data["standard_overrides"] = [
        {"id": "photo_break", "minutes": 4},
        {"id": "sharing", "minutes": 6},
    ]
    data["special_segments"] = [
        {
            "title": "额外工作坊",
            "owner": "成员K",
            "minutes": 10,
            "after": "guest_introduction",
        }
    ]
    data["meeting"]["approved_overtime_minutes"] = 11
    return data


def valid_pdf() -> bytes:
    return b"%PDF-1.7\n" + (b"P" * 1100)


def valid_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + (b"N" * 1100)


def write_preview_bundle(directory: Path) -> tuple[Path, bytes, bytes]:
    directory.mkdir(parents=True, exist_ok=True)
    html_path = directory / "agenda.preview.html"
    pdf_path = directory / "agenda.preview.pdf"
    png_path = directory / "agenda.preview.png"
    html_path.write_text(
        '<html><head><meta name="agenda-workflow" content="v3-preview">'
        '<meta name="agenda-page-count" content="1"></head>'
        "<body>approved</body></html>",
        encoding="utf-8",
    )
    pdf = valid_pdf()
    png = valid_png()
    pdf_path.write_bytes(pdf)
    png_path.write_bytes(png)
    manifest = {
        "workflow_version": 3,
        "stage": "preview",
        "page_count": 1,
        "facts_sha256": "1" * 64,
        "view_sha256": "2" * 64,
        "html_sha256": RUNNER.file_sha256(html_path),
        "pdf_sha256": RUNNER.file_sha256(pdf_path),
        "png_sha256": RUNNER.file_sha256(png_path),
        "outputs": {
            "html": html_path.name,
            "pdf": pdf_path.name,
            "png": png_path.name,
        },
    }
    (directory / RUNNER.V3_PREVIEW_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return html_path, pdf, png


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(all_keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(child) for child in value))
    return set()


class V3FactsTests(unittest.TestCase):
    def test_public_cli_exposes_text_image_and_final_workflow(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_agenda.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        usage = next(
            line for line in result.stdout.splitlines() if line.startswith("usage:")
        )
        self.assertIn("{first,confirm,image,final}", usage)
        for hidden in ("doctor", "draft", "preview", "prepare", "finalize"):
            self.assertNotIn(hidden, usage)

        first_help = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_agenda.py"),
                "first",
                "--help",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--confirm-overtime-minutes N", first_help.stdout)
        self.assertIn(
            "after the user explicitly approves",
            " ".join(first_help.stdout.split()),
        )

    def test_capacity_visual_audit_failures_trigger_compact_retry(self) -> None:
        for code in ("page_height", "page_overflow", "outside_page", "vertical_clip"):
            with self.subTest(code=code):
                payload = {
                    "errors": [
                        'agenda visual audit failed: [{"code": "'
                        + code
                        + '", "detail": "too tall"}]'
                    ]
                }
                self.assertTrue(RUNNER.is_only_single_page_overflow(payload))

        self.assertFalse(
            RUNNER.is_only_single_page_overflow(
                {"errors": ['agenda visual audit failed: [{"code": "font_missing"}]']}
            )
        )

    def test_fact_engine_supports_chinese_english_and_bilingual(self) -> None:
        for language in ("zh", "en", "bilingual"):
            with self.subTest(language=language):
                data = example()
                data["club"]["language"] = language
                result, errors, _ = BUILDER.build_agenda(data, facts_only=True)
                self.assertEqual(errors, [])
                self.assertEqual(result["club"]["language"], language)

    def test_facts_ignore_v2_visual_input_and_row_limit(self) -> None:
        data = example()
        data["meeting"].update(
            {
                "layout": "not-a-layout",
                "feature_item": "missing-item",
                "visual_theme": "not-a-theme",
                "visual_preferences": {"unknown": "value"},
                "theme_image": "missing-image.png",
                "end": "23:18",
            }
        )
        data["prepared_speeches"] = [
            {
                "speaker": f"Speaker {index}",
                "title": f"Speech {index}",
                "evaluator": f"Evaluator {index}",
            }
            for index in range(1, 13)
        ]

        result, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertEqual(errors, [])
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["computed"]["row_count"], 41)
        forbidden = {
            "layout",
            "feature_item",
            "visual_theme",
            "visual_preferences",
            "page_count",
            "theme_image",
        }
        self.assertTrue(forbidden.isdisjoint(all_keys(result)))

    def test_support_blocks_are_materialized_and_qr_is_self_contained(self) -> None:
        data = example()
        data["club"]["support_components"].extend(["vpm_qr", "voting_qr"])
        data["club"]["vpm_qr_image"] = "../assets/toastmasters-logo.png"
        data["meeting"]["voting_qr_image"] = "../assets/toastmasters-logo.png"

        result, errors, _ = BUILDER.build_agenda(
            data,
            source_dir=ROOT / "examples",
            facts_only=True,
        )

        self.assertEqual(errors, [])
        blocks = {block["id"]: block for block in result["support_blocks"]}
        self.assertEqual(blocks["timer_rules"]["kind"], "timing")
        self.assertTrue(blocks["timer_rules"]["entries"])
        self.assertEqual(blocks["officers"]["kind"], "pairs")
        self.assertTrue(blocks["toastmasters_intro"]["lines"])
        self.assertTrue(blocks["meeting_boundaries"]["lines"])
        for component in ("vpm_qr", "voting_qr"):
            self.assertEqual(blocks[component]["kind"], "image")
            self.assertTrue(blocks[component]["data_uri"].startswith("data:image/png"))

    def test_pathways_are_attached_by_exact_owner_name_only(self) -> None:
        data = example()
        data["participant_pathways"] = {
            "成员B": "PM L1",
            "不存在的人": "DL L5",
        }

        result, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertEqual(errors, [])
        owned = [row for row in result["timeline"] if row["owner"] == "成员B"]
        self.assertTrue(owned)
        self.assertTrue(all(row["pathways"] == "PM L1" for row in owned))
        self.assertTrue(
            all(
                row["pathways"] == ""
                for row in result["timeline"]
                if row["owner"] != "成员B"
            )
        )
        markdown = BUILDER.render_markdown(result)
        self.assertIn("Pathways 进展", markdown)
        self.assertIn("PM L1", markdown)

    def test_invalid_pathways_and_custom_backstage_are_explicit_errors(self) -> None:
        data = example()
        data["participant_pathways"] = {"成员A": ""}
        data["club"]["custom_support_blocks"] = [
            {"id": "backstage", "title": "幕后", "lines": ["不应覆盖"]}
        ]

        _, errors, _ = BUILDER.build_agenda(data, facts_only=True)

        self.assertTrue(any("non-empty string" in error for error in errors))
        self.assertTrue(any("conflicts with" in error for error in errors))

    def test_custom_support_block_can_be_classified_in_either_view_group(self) -> None:
        data = example()
        data["club"]["support_components"] = []
        data["club"]["custom_support_blocks"] = [
            {"id": "room_notes", "title": "现场提醒", "lines": ["记得签到"]}
        ]
        result, errors, _ = BUILDER.build_agenda(data, facts_only=True)
        self.assertEqual(errors, [])
        custom = next(
            block for block in result["support_blocks"] if block["id"] == "room_notes"
        )
        self.assertNotIn("group", custom)

        base_view = {
            "view_version": 1,
            "content_emphasis": None,
            "display_columns": ["time", "activity", "owner", "duration"],
            "density": "balanced",
            "design": {"text_scale": "standard", "contrast": "clear"},
        }
        for group in ("operations", "background"):
            view = {
                **base_view,
                "component_flow": {
                    "operations": ["backstage"],
                    "background": [],
                },
            }
            view["component_flow"][group].append("room_notes")
            RENDERER.validate_view(result, view)

    def test_pathways_column_requires_materialized_timeline_data(self) -> None:
        def view_for(result: dict) -> dict:
            operations = ["backstage"] if result["backstage"] else []
            background: list[str] = []
            for block in result["support_blocks"]:
                target = operations if block.get("group") == "operations" else background
                target.append(block["id"])
            return {
                "view_version": 1,
                "content_emphasis": None,
                "display_columns": [
                    "time",
                    "activity",
                    "owner",
                    "pathways",
                    "duration",
                ],
                "component_flow": {
                    "operations": operations,
                    "background": background,
                },
                "density": "balanced",
                "design": {"text_scale": "standard", "contrast": "clear"},
            }

        without_pathways, errors, _ = BUILDER.build_agenda(
            example(), facts_only=True
        )
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(RENDERER.AgendaRenderError, "no real data"):
            RENDERER.validate_view(without_pathways, view_for(without_pathways))

        data = example()
        data["participant_pathways"] = {"成员B": "PM L1"}
        with_pathways, errors, _ = BUILDER.build_agenda(data, facts_only=True)
        self.assertEqual(errors, [])
        RENDERER.validate_view(with_pathways, view_for(with_pathways))


class V3RunnerTests(unittest.TestCase):
    def test_profile_feedback_reports_created_reused_and_updated_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            profile_root = temp_dir / "profiles"
            data = example()
            data["club"]["join_info"] = ["已确认的入会规则"]
            data["club"]["custom_support_blocks"] = [
                {
                    "id": "guest_participation",
                    "title": "嘉宾可参与环节",
                    "lines": ["即兴演讲"],
                }
            ]
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

            code, created, _ = RUNNER.compute_facts(
                input_path,
                output_dir,
                club_profile=data["club"]["name"],
                profile_root=profile_root,
            )
            self.assertEqual(code, 0)
            self.assertEqual(created["profile"]["status"], "created")
            self.assertIn("俱乐部简介", created["profile"]["saved_labels"])
            self.assertIn("官员名单", created["profile"]["saved_labels"])
            self.assertIn("入会方式", created["profile"]["saved_labels"])
            self.assertIn("嘉宾可参与环节", created["profile"]["saved_labels"])
            self.assertIn("下次制作会单时", created["profile"]["user_message"])

            code, reused, _ = RUNNER.compute_facts(
                input_path,
                output_dir,
                club_profile=data["club"]["name"],
                profile_root=profile_root,
            )
            self.assertEqual(code, 0)
            self.assertEqual(reused["profile"]["status"], "reused")
            self.assertIn("已沿用", reused["profile"]["user_message"])

            data["club"]["club_intro"] = ["更新后的俱乐部简介"]
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            code, updated, _ = RUNNER.compute_facts(
                input_path,
                output_dir,
                club_profile=data["club"]["name"],
                profile_root=profile_root,
                update_club_profile=True,
            )
            self.assertEqual(code, 0)
            self.assertEqual(updated["profile"]["status"], "updated")
            self.assertIn("已记住", updated["profile"]["user_message"])

    def test_bundled_public_profile_supports_fast_path_without_local_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            local_profile_root = temp_dir / "local-profiles"
            data = simple_example()
            data["club"] = {
                "name": "明源云AI Lab头马俱乐部",
                "language": "zh",
            }
            data["agenda_overrides"] = [
                {"id": "photo_break", "minutes": 4},
                {"id": "sharing", "minutes": 6},
            ]
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

            with mock.patch.object(
                RUNNER, "load_agenda_builder", return_value=BUILDER
            ), mock.patch.object(BUILDER, "PROFILE_ROOT", local_profile_root):
                code, payload, computed = RUNNER.compute_facts(
                    input_path,
                    output_dir,
                    club_profile="明源云AI Lab头马俱乐部",
                )

            self.assertEqual(code, 0)
            self.assertEqual(payload["profile"]["status"], "bundled")
            self.assertIn("Skill 内置", payload["profile"]["user_message"])
            self.assertFalse(local_profile_root.exists())
            self.assertIsNotNone(computed)
            support_ids = [block["id"] for block in computed["support_blocks"]]
            self.assertIn("club_intro", support_ids)
            self.assertIn("officers", support_ids)
            self.assertIn("join_info", support_ids)
            self.assertIn("guest_participation", support_ids)

    def test_confirm_text_stops_before_browser_and_returns_fact_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(example(), ensure_ascii=False), encoding="utf-8"
            )
            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
                confirm_overtime_minutes=None,
            )
            stdout = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stdout(stdout):
                return_code = RUNNER.confirm_text(args)

            self.assertEqual(return_code, 0)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "text_confirmation_ready")
            self.assertEqual(len(payload["facts_sha256"]), 64)
            self.assertTrue((output_dir / "agenda.md").is_file())
            self.assertTrue((output_dir / "agenda.computed.json").is_file())
            self.assertFalse((output_dir / "agenda.preview.png").exists())

    def test_image_requires_the_exact_text_confirmed_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(example(), ensure_ascii=False), encoding="utf-8"
            )
            confirm_args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
                confirm_overtime_minutes=None,
            )
            confirmed_stdout = io.StringIO()
            with contextlib.redirect_stdout(confirmed_stdout):
                self.assertEqual(RUNNER.confirm_text(confirm_args), 0)
            confirmed = json.loads(confirmed_stdout.getvalue())

            bad_stderr = io.StringIO()
            with contextlib.redirect_stderr(bad_stderr):
                self.assertEqual(
                    RUNNER.image_from_confirmed(
                        argparse.Namespace(
                            input_computed=output_dir / "agenda.computed.json",
                            confirmed_sha256="0" * 64,
                            output_dir=output_dir,
                            view_patch=None,
                        )
                    ),
                    2,
                )
            self.assertEqual(
                json.loads(bad_stderr.getvalue())["stage"],
                "text_confirmation_required",
            )

            def fake_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            image_stdout = io.StringIO()
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), mock.patch.object(
                RUNNER, "load_v3_renderer", return_value=RENDERER.render_agenda
            ), contextlib.redirect_stdout(image_stdout):
                self.assertEqual(
                    RUNNER.image_from_confirmed(
                        argparse.Namespace(
                            input_computed=output_dir / "agenda.computed.json",
                            confirmed_sha256=confirmed["facts_sha256"],
                            output_dir=output_dir,
                            view_patch=None,
                        )
                    ),
                    0,
                )
            self.assertEqual(
                json.loads(image_stdout.getvalue())["stage"], "preview_ready"
            )

    def _first_args(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        confirm_overtime_minutes: int | float | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            input_json=input_path,
            output_dir=output_dir,
            club_profile=None,
            update_club_profile=False,
            profile_root=None,
            view_patch=None,
            confirm_overtime_minutes=confirm_overtime_minutes,
        )

    def test_simple_first_returns_both_break_and_sharing_suggestions_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            data = simple_example()
            data.pop("standard_overrides", None)
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(self._first_args(input_path, output_dir))

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "needs_input")
            self.assertEqual(payload["error_type"], "duration_confirmation_required")
            self.assertEqual(
                payload["suggested_agenda_overrides"],
                [
                    {"id": "photo_break", "minutes": 10},
                    {"id": "sharing", "minutes": 10},
                ],
            )
            self.assertIn("我为你默认安排了合影＋休息 10 分钟、真情分享 10 分钟", payload["next_action"])
            self.assertNotIn("approve exactly 10 overtime minutes", payload["next_action"])

    def test_canonical_first_uses_the_same_duration_confirmation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            data = example()
            data["standard_overrides"] = []
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(self._first_args(input_path, output_dir))

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "needs_input")
            self.assertEqual(payload["error_type"], "duration_confirmation_required")
            self.assertEqual(len(payload["required_duration_confirmations"]), 2)

    def test_simple_overrun_stops_before_rendering_and_requires_user_confirmation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(overrun_simple_example(), ensure_ascii=False),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(self._first_args(input_path, output_dir))

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "needs_input")
            self.assertEqual(
                payload["error_type"], "overtime_confirmation_required"
            )
            self.assertEqual(payload["required_overtime_minutes"], 11)
            self.assertEqual(payload["provided_overtime_minutes"], None)
            self.assertEqual(payload["proposed_final_end"], "21:41")
            self.assertIn("Stop and ask the user", payload["next_action"])
            self.assertIn("Do not change meeting.end", payload["next_action"])
            self.assertIn("same turn", payload["next_action"])
            self.assertFalse((output_dir / "agenda.preview.png").exists())

    def test_first_returns_both_missing_impromptu_durations_before_rendering(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            data = simple_example()
            data["impromptu"].pop("minutes")
            data["impromptu"].pop("evaluation_minutes")
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(self._first_args(input_path, output_dir))

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "needs_input")
            self.assertEqual(payload["error_type"], "simple_input")
            self.assertEqual(
                {
                    (issue["code"], issue["path"])
                    for issue in payload["errors"]
                    if issue["path"].startswith("impromptu.")
                },
                {
                    ("missing_value", "impromptu.minutes"),
                    ("missing_value", "impromptu.evaluation_minutes"),
                },
            )
            self.assertFalse((output_dir / "agenda.preview.png").exists())

    def test_first_blocks_selected_join_info_when_profile_text_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            data = simple_example()
            data["club"]["support_components"] = ["join_info"]
            data["club"].pop("join_info", None)
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(self._first_args(input_path, output_dir))

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "needs_input")
            self.assertIn(
                "join_info component is selected but club.join_info is empty",
                payload["errors"],
            )
            self.assertFalse((output_dir / "agenda.preview.png").exists())

    def test_simple_overrun_exact_second_run_confirmation_creates_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            data = overrun_simple_example()
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

            def fake_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            stdout = io.StringIO()
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), mock.patch.object(
                RUNNER, "load_v3_renderer", return_value=RENDERER.render_agenda
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.first(
                    self._first_args(
                        input_path,
                        output_dir,
                        confirm_overtime_minutes=11,
                    )
                )

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "preview_ready")
            self.assertEqual(payload["computed"]["approved_overtime_minutes"], 11)
            self.assertEqual(payload["computed"]["status"], "exact_with_approved_overtime")
            self.assertEqual(payload["computed"]["final_end"], "21:41")
            self.assertNotIn(
                "approved_overtime_minutes",
                json.loads(input_path.read_text(encoding="utf-8"))["meeting"],
            )

    def test_simple_overrun_exact_confirmation_exports_real_single_page_a4(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(overrun_simple_example(), ensure_ascii=False),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                return_code = RUNNER.first(
                    self._first_args(
                        input_path,
                        output_dir,
                        confirm_overtime_minutes=11,
                    )
                )

            self.assertEqual(return_code, 0, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "preview_ready")
            manifest = json.loads(
                (output_dir / "agenda.preview.manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["page_count"], 1)
            self.assertTrue((output_dir / "agenda.preview.pdf").is_file())
            self.assertTrue((output_dir / "agenda.preview.png").is_file())

    def test_simple_overtime_confirmation_rejects_mismatch_and_no_overrun(self) -> None:
        cases = (
            (
                "mismatch",
                overrun_simple_example(),
                10.5,
                "overtime_confirmation_mismatch",
                11,
            ),
            (
                "no_overrun",
                {
                    **simple_example(),
                    "agenda_overrides": [
                        {"id": "photo_break", "minutes": 4},
                        {"id": "sharing", "minutes": 6},
                    ],
                },
                11,
                "overtime_confirmation_rejected",
                None,
            ),
        )
        for name, data, confirmation, error_type, required in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_text:
                temp_dir = Path(temp_text)
                input_path = temp_dir / "meeting.json"
                output_dir = temp_dir / "output"
                input_path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
                stderr = io.StringIO()
                with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                    mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                    contextlib.redirect_stderr(stderr):
                    return_code = RUNNER.first(
                        self._first_args(
                            input_path,
                            output_dir,
                            confirm_overtime_minutes=confirmation,
                        )
                    )
                self.assertEqual(return_code, 2)
                exporter.assert_not_called()
                renderer.assert_not_called()
                payload = json.loads(stderr.getvalue())
                self.assertEqual(payload["error_type"], error_type)
                self.assertEqual(payload["required_overtime_minutes"], required)
                self.assertEqual(
                    payload["provided_overtime_minutes"], confirmation
                )

    def test_simple_json_overtime_approval_is_rejected_even_with_cli_confirmation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            data = overrun_simple_example()
            data["meeting"]["approved_overtime_minutes"] = 11
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            stderr = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(
                    self._first_args(
                        input_path,
                        output_dir,
                        confirm_overtime_minutes=11,
                    )
                )

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["error_type"], "simple_input")
            self.assertTrue(
                any(
                    issue["code"] == "overtime_approval_not_allowed"
                    for issue in payload["errors"]
                )
            )
            self.assertIn("Do not change meeting.end", payload["next_action"])

    def test_canonical_embedded_overtime_approval_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(approved_canonical_overrun_example(), ensure_ascii=False),
                encoding="utf-8",
            )

            code, payload, computed = RUNNER.compute_facts(input_path, output_dir)

            self.assertEqual(code, 0)
            self.assertEqual(payload["stage"], "facts_ready")
            self.assertIsNotNone(computed)
            self.assertEqual(
                computed["computed"]["status"], "exact_with_approved_overtime"
            )
            self.assertEqual(computed["computed"]["final_end"], "21:41")

    def test_draft_writes_only_fact_stage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            output_dir = temp_dir / "output"
            input_path = temp_dir / "meeting.json"
            input_path.write_text(
                json.dumps(example(), ensure_ascii=False), encoding="utf-8"
            )
            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                return_code = RUNNER.draft(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "drafted")
            self.assertEqual(
                {path.name for path in output_dir.iterdir()},
                {
                    "agenda.computed.json",
                    "agenda.md",
                    "agenda.diagnostics.json",
                    "agenda.manifest.json",
                },
            )
            self.assertFalse((output_dir / "agenda.html").exists())

    def test_first_calls_fact_engine_directly_and_creates_complete_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            input_path.write_text(
                json.dumps(example(), ensure_ascii=False), encoding="utf-8"
            )
            commands: list[list[str]] = []

            def fake_export(command: list[str], **_kwargs: object):
                commands.append(command)
                self.assertEqual(Path(command[1]), RUNNER.EXPORT_SCRIPT)
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
                view_patch=None,
            )
            stdout = io.StringIO()
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), mock.patch.object(
                RUNNER, "load_v3_renderer", return_value=RENDERER.render_agenda
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.first(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "preview_ready")
            self.assertEqual(len(commands), 1)
            self.assertNotIn(str(RUNNER.BUILD_SCRIPT), commands[0])
            for name in (
                "agenda.computed.json",
                "agenda.md",
                "agenda.diagnostics.json",
                "agenda.manifest.json",
                RUNNER.V3_VIEW_NAME,
                "agenda.preview.html",
                "agenda.preview.pdf",
                "agenda.preview.png",
                RUNNER.V3_PREVIEW_MANIFEST_NAME,
            ):
                self.assertTrue((output_dir / name).is_file(), name)

    def test_same_first_command_handles_missing_and_existing_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            profile_root = temp_dir / "profiles"
            club_name = "星河头马演讲俱乐部"
            current_location = "星河中心 A 会议室"
            data = example()
            data["club"]["name"] = club_name
            data["meeting"]["location"] = current_location
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )

            def fake_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=club_name,
                update_club_profile=False,
                profile_root=profile_root,
                view_patch=None,
            )

            for _ in range(2):
                stdout = io.StringIO()
                with mock.patch.object(
                    RUNNER, "run_json_command", side_effect=fake_export
                ), mock.patch.object(
                    RUNNER, "load_v3_renderer", return_value=RENDERER.render_agenda
                ), contextlib.redirect_stdout(stdout):
                    self.assertEqual(RUNNER.first(args), 0)
                self.assertEqual(json.loads(stdout.getvalue())["stage"], "preview_ready")

                profile_path = BUILDER.stored_club_profile_path(
                    club_name, profile_root=profile_root
                )
                self.assertTrue(profile_path.is_file())
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                profile["club"]["default_location"] = "旧 profile 会场"
                profile_path.write_text(
                    json.dumps(profile, ensure_ascii=False), encoding="utf-8"
                )

            computed = json.loads(
                (output_dir / "agenda.computed.json").read_text(encoding="utf-8")
            )
            self.assertEqual(computed["meeting"]["location"], current_location)

    def test_first_returns_all_fact_errors_and_keeps_previous_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            old_preview = b"previous preview"
            (output_dir / "agenda.preview.png").write_bytes(old_preview)
            data = example()
            data["meeting"].pop("date")
            data["meeting"].pop("start")
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            args = argparse.Namespace(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
                view_patch=None,
            )
            stderr = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                mock.patch.object(RUNNER, "load_v3_renderer") as renderer, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.first(args)

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            renderer.assert_not_called()
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "needs_input")
            self.assertTrue(any("meeting.date" in error for error in payload["errors"]))
            self.assertTrue(any("meeting.start" in error for error in payload["errors"]))
            self.assertEqual(
                (output_dir / "agenda.preview.png").read_bytes(), old_preview
            )

    def test_partial_view_patch_is_saved_and_reused_after_content_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            input_path = temp_dir / "meeting.json"
            patch_path = temp_dir / "view.patch.json"
            output_dir = temp_dir / "output"
            data = example()
            input_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            patch_path.write_text(
                json.dumps(
                    {"density": "comfortable", "design": {"text_scale": "large"}}
                ),
                encoding="utf-8",
            )
            rendered_views: list[dict] = []

            def fake_renderer(_computed: dict, view: dict, **_kwargs: object) -> str:
                rendered_views.append(deepcopy(view))
                return (
                    '<html><head><meta name="agenda-workflow" content="v3-preview">'
                    '<meta name="agenda-page-count" content="1"></head></html>'
                )

            def fake_export(command: list[str], **_kwargs: object):
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            base_args = dict(
                input_json=input_path,
                output_dir=output_dir,
                club_profile=None,
                update_club_profile=False,
                profile_root=None,
            )
            with mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), mock.patch.object(
                RUNNER, "load_v3_renderer", return_value=fake_renderer
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    RUNNER.first(argparse.Namespace(**base_args, view_patch=patch_path)),
                    0,
                )
                data["meeting"]["theme"] = "Changed content"
                input_path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
                self.assertEqual(
                    RUNNER.first(argparse.Namespace(**base_args, view_patch=None)),
                    0,
                )

            self.assertEqual(len(rendered_views), 2)
            for view in rendered_views:
                self.assertEqual(view["density"], "comfortable")
                self.assertEqual(view["design"]["text_scale"], "large")
                self.assertEqual(view["design"]["contrast"], "clear")
            persisted = json.loads(
                (output_dir / RUNNER.V3_VIEW_PATCH_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["design"], {"text_scale": "large"})

    def test_preview_uses_renderer_and_exports_a_complete_bundle_without_rebuilding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            computed_path = temp_dir / "agenda.computed.json"
            view_path = temp_dir / "agenda.view.json"
            output_dir = temp_dir / "output"
            computed_path.write_text('{"schema_version": 3}', encoding="utf-8")
            view_path.write_text('{"view_version": 1}', encoding="utf-8")

            def fake_export(command: list[str], **_kwargs: object):
                self.assertEqual(Path(command[1]), RUNNER.EXPORT_SCRIPT)
                self.assertNotIn(str(RUNNER.BUILD_SCRIPT), command)
                staging_dir = Path(command[-1])
                (staging_dir / "agenda.pdf").write_bytes(valid_pdf())
                (staging_dir / "agenda.png").write_bytes(valid_png())
                return 0, {"ok": True, "pages": 1}

            args = argparse.Namespace(
                input_computed=computed_path,
                view=view_path,
                output_dir=output_dir,
            )
            stdout = io.StringIO()
            with mock.patch.object(
                RUNNER,
                "load_v3_renderer",
                return_value=lambda *_args, **_kwargs: "<html><body>preview</body></html>",
            ), mock.patch.object(
                RUNNER, "run_json_command", side_effect=fake_export
            ), contextlib.redirect_stdout(stdout):
                return_code = RUNNER.preview(args)

            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "preview_ready")
            self.assertTrue((output_dir / "agenda.preview.html").is_file())
            self.assertTrue((output_dir / "agenda.preview.pdf").is_file())
            self.assertTrue((output_dir / "agenda.preview.png").is_file())
            self.assertTrue(
                (output_dir / RUNNER.V3_PREVIEW_MANIFEST_NAME).is_file()
            )
            self.assertGreater((output_dir / "agenda.preview.png").stat().st_size, 1000)
            self.assertFalse((output_dir / "agenda.pdf").exists())

    def test_final_copies_approved_bytes_without_calling_exporter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            preview_dir = temp_dir / "preview"
            output_dir = temp_dir / "output"
            html_path, preview_pdf, preview_png = write_preview_bundle(preview_dir)

            args = argparse.Namespace(
                input_html=html_path,
                output_dir=output_dir,
                v3_final=True,
            )
            stdout = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                contextlib.redirect_stdout(stdout):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 0)
            exporter.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage"], "finalized")
            self.assertNotIn("deprecated", payload)
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), preview_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), preview_png)

    def test_final_rejects_tampered_preview_and_keeps_last_good(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            preview_dir = temp_dir / "preview"
            output_dir = temp_dir / "output"
            html_path, _, _ = write_preview_bundle(preview_dir)
            (preview_dir / "agenda.preview.png").write_bytes(valid_png() + b"tampered")
            output_dir.mkdir()
            old_pdf = valid_pdf() + b"old"
            old_png = valid_png() + b"old"
            (output_dir / "agenda.pdf").write_bytes(old_pdf)
            (output_dir / "agenda.png").write_bytes(old_png)
            args = argparse.Namespace(
                input_html=html_path,
                output_dir=output_dir,
                v3_final=True,
            )
            stderr = io.StringIO()
            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), old_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), old_png)
            payload = json.loads(stderr.getvalue())
            self.assertTrue(payload["last_good_preserved"])
            self.assertTrue(any("PNG" in error for error in payload["errors"]))

    def test_final_rejects_unmarked_html_and_preserves_previous_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            temp_dir = Path(temp_text)
            html_path = temp_dir / "not-a-preview.html"
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            html_path.write_text("<html><body>unapproved</body></html>", encoding="utf-8")
            old_pdf = valid_pdf()
            old_png = valid_png()
            (output_dir / "agenda.pdf").write_bytes(old_pdf)
            (output_dir / "agenda.png").write_bytes(old_png)
            args = argparse.Namespace(
                input_html=html_path,
                output_dir=output_dir,
                v3_final=True,
            )
            stderr = io.StringIO()

            with mock.patch.object(RUNNER, "run_json_command") as exporter, \
                contextlib.redirect_stderr(stderr):
                return_code = RUNNER.finalize(args)

            self.assertEqual(return_code, 2)
            exporter.assert_not_called()
            self.assertEqual((output_dir / "agenda.pdf").read_bytes(), old_pdf)
            self.assertEqual((output_dir / "agenda.png").read_bytes(), old_png)
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["stage"], "finalize_failed")
            self.assertTrue(payload["last_good_preserved"])
            self.assertIn("v3-preview marker is missing", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
