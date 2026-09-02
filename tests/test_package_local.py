from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_package_local", ROOT / "scripts" / "package_local.py"
)
assert SPEC and SPEC.loader
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class LocalPackageTests(unittest.TestCase):
    def test_output_directory_is_required_and_cannot_be_inside_skill(self) -> None:
        parser = PACKAGER.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([])
        with self.assertRaisesRegex(ValueError, "outside the Skill directory"):
            PACKAGER.validate_output_root(ROOT / "dist" / "local")

    def test_package_contains_only_the_portable_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            output_root = Path(temp_text)
            package_dir, zip_path = PACKAGER.build_package(output_root)

            self.assertTrue(zip_path.is_file())
            self.assertEqual(
                {path.name for path in package_dir.iterdir()},
                {"SKILL.md", "SHA256SUMS", "agents", "assets", "profiles", "scripts"},
            )
            self.assertEqual(
                {path.name for path in (package_dir / "scripts").iterdir()},
                {
                    "agenda_renderer.py",
                    "build_agenda.py",
                    "export_a4.py",
                    "run_agenda.py",
                    "simple_input.py",
                },
            )
            self.assertEqual(
                {path.name for path in (package_dir / "agents").iterdir()},
                {"openai.yaml"},
            )
            self.assertFalse((package_dir / "README.md").exists())
            self.assertFalse((package_dir / "examples").exists())
            self.assertFalse((package_dir / "references").exists())
            self.assertTrue((ROOT / "references" / "input-contract.md").is_file())
            self.assertFalse((package_dir / "tests").exists())
            self.assertFalse((package_dir / "assets" / "layouts").exists())
            self.assertFalse((package_dir / "assets" / "themes").exists())
            self.assertFalse((package_dir / "assets" / "icons").exists())
            bundled_profiles = list((package_dir / "profiles").glob("*.json"))
            self.assertEqual(len(bundled_profiles), 1)
            profile = json.loads(bundled_profiles[0].read_text(encoding="utf-8"))
            self.assertEqual(
                profile["club"]["name"], "明源云AI Lab头马俱乐部"
            )

            skill_text = (package_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("simple_version: 1", skill_text)
            self.assertNotIn("references/", skill_text)
            self.assertNotIn("input-contract.md", skill_text)
            for excluded_reference in (
                "agenda-rules.md",
                "input-schema.md",
                "local-model-workflow.md",
                "v3-architecture.md",
                "v3-view-intent.md",
                "visual-system.md",
            ):
                self.assertNotIn(excluded_reference, skill_text)

            font_root = package_dir / "assets" / "fonts" / "noto-sans-sc"
            self.assertTrue((font_root / "LICENSE").is_file())
            self.assertTrue((font_root / "NOTICE.md").is_file())
            self.assertTrue((font_root / "index.css").is_file())
            self.assertGreater(len(list((font_root / "files").glob("*.woff2"))), 1)
            self.assertFalse((font_root / "package.json").exists())

            manifest_path = package_dir / "SHA256SUMS"
            manifest_entries: dict[str, str] = {}
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                digest, relative = line.split("  ", 1)
                manifest_entries[relative] = digest
            packaged_files = {
                path.relative_to(package_dir).as_posix()
                for path in package_dir.rglob("*")
                if path.is_file() and path != manifest_path
            }
            self.assertEqual(set(manifest_entries), packaged_files)
            for relative, digest in manifest_entries.items():
                self.assertEqual(digest, file_sha256(package_dir / relative))

            with zipfile.ZipFile(zip_path) as archive:
                zipped = {name for name in archive.namelist() if not name.endswith("/")}
            expected_zipped = {
                f"{PACKAGER.PACKAGE_FOLDER}/{path.relative_to(package_dir).as_posix()}"
                for path in package_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(zipped, expected_zipped)

            meeting_path = output_root / "meeting.json"
            meeting_path.write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(package_dir / "scripts" / "run_agenda.py"),
                    "first",
                    str(meeting_path),
                    "--output-dir",
                    str(output_root / "agenda-output"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stderr)
            self.assertEqual(payload["stage"], "needs_input")
            self.assertTrue(payload["errors"])

    def test_unzipped_package_runs_simple_first_and_final_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            output_root = Path(temp_text)
            package_dir, zip_path = PACKAGER.build_package(output_root)
            shutil.rmtree(package_dir)

            extracted_root = output_root / "extracted"
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extracted_root)
            extracted_package = extracted_root / PACKAGER.PACKAGE_FOLDER

            meeting_path = output_root / "meeting.simple.json"
            meeting_path.write_text(
                json.dumps(
                    {
                        "simple_version": 1,
                        "club": {
                            "name": "示例头马演讲俱乐部",
                            "default_location": "示例会议室",
                            "language": "zh",
                        },
                        "meeting": {
                            "number": "236",
                            "date": "2026-09-02",
                            "start": "19:30",
                            "end": "21:30",
                            "location": "示例会议室",
                            "theme": "持续成长",
                            "manager": "成员甲",
                            "president": "成员乙",
                        },
                        "roles": [
                            {"role": "会议规则", "person": "成员丙"},
                            {"role": "总主持", "person": "成员丁"},
                            {"role": "时间官", "person": "成员丙"},
                            {"role": "哼哈官", "person": "成员戊"},
                            {"role": "语法官", "person": "成员己"},
                            {"role": "嘉宾介绍", "person": "成员庚"},
                            {"role": "真情分享", "person": "成员丙"},
                            {"role": "总点评", "person": "成员辛"},
                            {"role": "颁奖主持", "person": "成员庚"},
                        ],
                        "speeches": [
                            {
                                "speaker": "成员乙",
                                "title": "我的第一步",
                                "evaluator": "成员戊",
                            },
                            {
                                "speaker": "成员丙",
                                "title": "持续练习",
                                "evaluator": "成员庚",
                            },
                            {
                                "speaker": "成员辛",
                                "title": "共同成长",
                                "evaluator": "成员己",
                            },
                        ],
                        "impromptu": {
                            "host": "成员壬",
                            "minutes": 14,
                            "evaluator": "成员乙",
                            "evaluation_minutes": 7,
                        },
                        "backstage": [{"role": "摄影官", "person": "成员癸"}],
                        "special": [],
                        "agenda_overrides": [
                            {"id": "photo_break", "minutes": 4},
                            {"id": "sharing", "minutes": 6},
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            agenda_output = output_root / "agenda-output"
            confirm_result = subprocess.run(
                [
                    sys.executable,
                    str(extracted_package / "scripts" / "run_agenda.py"),
                    "confirm",
                    str(meeting_path),
                    "--output-dir",
                    str(agenda_output),
                ],
                cwd=output_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(confirm_result.returncode, 0, confirm_result.stderr)
            confirm_payload = json.loads(confirm_result.stdout)
            self.assertEqual(
                confirm_payload["stage"], "text_confirmation_ready"
            )
            self.assertFalse((agenda_output / "agenda.preview.png").exists())

            image_result = subprocess.run(
                [
                    sys.executable,
                    str(extracted_package / "scripts" / "run_agenda.py"),
                    "image",
                    str(agenda_output / "agenda.computed.json"),
                    "--confirmed-sha256",
                    confirm_payload["facts_sha256"],
                    "--output-dir",
                    str(agenda_output),
                ],
                cwd=output_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(image_result.returncode, 0, image_result.stderr)
            image_payload = json.loads(image_result.stdout)
            self.assertEqual(image_payload["stage"], "preview_ready")

            preview_html = agenda_output / "agenda.preview.html"
            preview_pdf = agenda_output / "agenda.preview.pdf"
            preview_png = agenda_output / "agenda.preview.png"
            approved_pdf = preview_pdf.read_bytes()
            approved_png = preview_png.read_bytes()

            final_result = subprocess.run(
                [
                    sys.executable,
                    str(extracted_package / "scripts" / "run_agenda.py"),
                    "final",
                    str(preview_html),
                    "--output-dir",
                    str(agenda_output),
                ],
                cwd=output_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(final_result.returncode, 0, final_result.stderr)
            final_payload = json.loads(final_result.stdout)
            self.assertEqual(final_payload["stage"], "finalized")
            self.assertEqual((agenda_output / "agenda.pdf").read_bytes(), approved_pdf)
            self.assertEqual((agenda_output / "agenda.png").read_bytes(), approved_png)

    def test_privacy_scan_rejects_private_and_machine_specific_text(self) -> None:
        samples = {
            "private path": "Use /Users/example/Documents/agenda.json",
            "email": "Contact member@example.com",
            "phone": "Call 13800138000",
            "membership": "PN-12345678",
        }
        for label, content in samples.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_text:
                target = Path(temp_text)
                (target / "sample.md").write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "privacy scan failed"):
                    PACKAGER.scan_text_files(target)

    def test_force_never_replaces_an_unrecognized_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            output_root = Path(temp_text)
            unrelated = output_root / PACKAGER.PACKAGE_FOLDER
            unrelated.mkdir()
            marker = unrelated / "keep-me.txt"
            marker.write_text("user content", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unrecognized existing target"):
                PACKAGER.build_package(output_root, force=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "user content")


if __name__ == "__main__":
    unittest.main()
