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
    return json.loads(
        (ROOT / "examples" / "meeting.example.json").read_text(encoding="utf-8")
    )


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
    def test_public_cli_exposes_only_first_and_final(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_agenda.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        usage = next(
            line for line in result.stdout.splitlines() if line.startswith("usage:")
        )
        self.assertIn("{first,final}", usage)
        for hidden in ("doctor", "draft", "preview", "prepare", "finalize"):
            self.assertNotIn(hidden, usage)

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
                "end": "23:30",
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
    def test_draft_writes_only_fact_stage_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            output_dir = Path(temp_text) / "output"
            args = argparse.Namespace(
                input_json=ROOT / "examples" / "meeting.example.json",
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
