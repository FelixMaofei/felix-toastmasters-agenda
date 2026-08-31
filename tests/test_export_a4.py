from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agenda_exporter", ROOT / "scripts" / "export_a4.py"
)
assert SPEC and SPEC.loader
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


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


if __name__ == "__main__":
    unittest.main()
