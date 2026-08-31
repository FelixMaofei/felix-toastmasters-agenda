#!/usr/bin/env python3
"""Export generated agenda HTML to verified A4 PDF pages and PNG assets."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]


def find_chrome() -> str | None:
    configured = os.environ.get("AGENDA_CHROME")
    if configured and Path(configured).is_file():
        return configured
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def expected_page_count(html_path: Path) -> int:
    text = html_path.read_text(encoding="utf-8")
    match = re.search(r'<meta\s+name="agenda-page-count"\s+content="(\d+)">', text)
    if not match:
        raise ValueError("agenda HTML is missing agenda-page-count metadata")
    count = int(match.group(1))
    if count <= 0:
        raise ValueError("agenda-page-count must be positive")
    return count


def run_chrome(command: list[str], expected_file: Path, timeout: int = 25) -> int:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        return 0 if expected_file.is_file() and expected_file.stat().st_size > 1000 else 124


def page_count(pdf_path: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return None
    result = subprocess.run(
        [pdfinfo, str(pdf_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_html", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args()

    html_path = args.input_html.expanduser().resolve()
    if not html_path.is_file():
        parser.error(f"HTML does not exist: {html_path}")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "agenda.pdf"
    png_path = output_dir / "agenda.png"
    for stale in [pdf_path, png_path, *output_dir.glob("agenda-page-*.png")]:
        if stale.is_file():
            stale.unlink()
    try:
        expected_pages = expected_page_count(html_path)
    except (OSError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        raise SystemExit(2)

    chrome = find_chrome()
    if not chrome:
        print(
            json.dumps(
                {"ok": False, "errors": ["Chrome/Chromium is required to export the A4 PDF"]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    with tempfile.TemporaryDirectory(prefix="felix-agenda-chrome-") as profile:
        command = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        return_code = run_chrome(command, pdf_path)

    if return_code != 0 or not pdf_path.is_file() or pdf_path.stat().st_size <= 1000:
        print(
            json.dumps(
                {"ok": False, "errors": [f"PDF export failed with code {return_code}"]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    pages = page_count(pdf_path)
    if pages is not None and pages != expected_pages:
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": [
                        f"agenda HTML declares {expected_pages} pages but PDF contains {pages}"
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    pdftoppm = None if os.environ.get("AGENDA_DISABLE_PDFTOPPM") == "1" else shutil.which("pdftoppm")
    png_paths: list[Path] = []
    if pdftoppm:
        if expected_pages == 1:
            command = [
                pdftoppm,
                "-png",
                "-r",
                "160",
                "-singlefile",
                str(pdf_path),
                str(output_dir / "agenda"),
            ]
        else:
            command = [
                pdftoppm,
                "-png",
                "-r",
                "160",
                str(pdf_path),
                str(output_dir / "agenda-page"),
            ]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            if expected_pages == 1 and png_path.is_file():
                png_paths = [png_path]
            else:
                png_paths = sorted(output_dir.glob("agenda-page-*.png"))

    if not png_paths:
        screenshot_height = 1123 * expected_pages + 32 * max(0, expected_pages - 1)
        with tempfile.TemporaryDirectory(prefix="felix-agenda-screenshot-") as profile:
            screenshot_command = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--hide-scrollbars",
                "--no-first-run",
                "--force-device-scale-factor=2",
                f"--window-size=794,{screenshot_height}",
                f"--user-data-dir={profile}",
                f"--screenshot={png_path}",
                html_path.as_uri(),
            ]
            screenshot_code = run_chrome(screenshot_command, png_path)
        if screenshot_code == 0 and png_path.is_file() and png_path.stat().st_size > 1000:
            png_paths = [png_path]

    if not png_paths:
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": [
                        "PDF was created, but PNG export failed; install Poppler/pdftoppm "
                        "or use a Chrome/Chromium build with screenshot support"
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "ok": True,
                "pdf": str(pdf_path),
                "pages": pages if pages is not None else expected_pages,
                "png": str(png_paths[0]),
                "pngs": [str(path) for path in png_paths],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
