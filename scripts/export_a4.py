#!/usr/bin/env python3
"""Export generated agenda HTML to one verified A4 portrait PDF page and PNG."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
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

CHROME_POLL_INTERVAL_SECONDS = 0.05
CHROME_FILE_STABLE_SECONDS = 0.5
CHROME_SHUTDOWN_TIMEOUT_SECONDS = 3.0
PDF_SIGNATURE = b"%PDF-"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"IEND\xaeB`\x82"


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
    if count != 1:
        raise ValueError(
            f"final agenda must declare exactly 1 A4 page; HTML declares {count}"
        )
    return count


def chrome_output_is_complete(path: Path) -> bool:
    """Return true only after Chrome has written a structurally complete file."""

    try:
        if not path.is_file() or path.stat().st_size <= 1000:
            return False
        with path.open("rb") as handle:
            signature = handle.read(len(PNG_SIGNATURE))
            handle.seek(max(0, path.stat().st_size - 2048))
            tail = handle.read()
    except OSError:
        return False

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return signature.startswith(PDF_SIGNATURE) and b"%%EOF" in tail
    if suffix == ".png":
        return signature == PNG_SIGNATURE and PNG_IEND in tail
    return True


def stop_chrome_process(process: subprocess.Popen[bytes]) -> None:
    """Stop only the Chrome process started for this export."""

    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=CHROME_SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            return
        try:
            process.wait(timeout=CHROME_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def run_chrome(command: list[str], expected_file: Path, timeout: int = 25) -> int:
    """Run Chrome until it exits or its complete output has remained stable."""

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started_at = time.monotonic()
    stable_signature: tuple[int, int] | None = None
    stable_since: float | None = None

    while True:
        now = time.monotonic()
        return_code = process.poll()
        complete = chrome_output_is_complete(expected_file)

        if complete:
            try:
                stat = expected_file.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                signature = None
                complete = False
            if complete and signature != stable_signature:
                stable_signature = signature
                stable_since = now
            elif (
                complete
                and stable_since is not None
                and now - stable_since >= CHROME_FILE_STABLE_SECONDS
            ):
                stop_chrome_process(process)
                return 0
        else:
            stable_signature = None
            stable_since = None

        if return_code is not None:
            if complete:
                return 0
            return return_code

        if now - started_at >= timeout:
            stop_chrome_process(process)
            return 0 if chrome_output_is_complete(expected_file) else 124

        remaining = timeout - (now - started_at)
        time.sleep(min(CHROME_POLL_INTERVAL_SECONDS, max(0.0, remaining)))


def page_count(pdf_path: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
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
                    break
    try:
        data = pdf_path.read_bytes()
    except OSError:
        return None
    fallback = len(re.findall(rb"/Type\s*/Page\b", data))
    return fallback or None


def page_size_points(pdf_path: Path) -> tuple[float, float] | None:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo:
        result = subprocess.run(
            [pdfinfo, str(pdf_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        for line in result.stdout.splitlines():
            match = re.match(
                r"Page size:\s*([0-9.]+)\s*x\s*([0-9.]+)\s+pts",
                line,
            )
            if match:
                return float(match.group(1)), float(match.group(2))
    try:
        data = pdf_path.read_bytes()
    except OSError:
        return None
    match = re.search(
        rb"/MediaBox\s*\[\s*[-0-9.]+\s+[-0-9.]+\s+([-0-9.]+)\s+([-0-9.]+)\s*\]",
        data,
    )
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def is_a4_portrait(size: tuple[float, float]) -> bool:
    width, height = size
    return abs(width - 595.28) <= 3 and abs(height - 841.89) <= 3


def chrome_compatibility_flags() -> list[str]:
    if os.environ.get("AGENDA_CHROME_NO_SANDBOX") == "1":
        return ["--no-sandbox", "--disable-software-rasterizer"]
    return []


def parse_visual_audit_dump(dump: str) -> dict[str, object] | None:
    match = re.search(
        r'<script id="agenda-audit-result" type="application/json">(.*?)</script>',
        dump,
        flags=re.DOTALL,
    )
    if not match:
        return None
    payload = html_lib.unescape(match.group(1)).strip()
    if not payload:
        return None
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("agenda visual audit result must be an object")
    return parsed


def visual_audit_required(source: str) -> bool:
    return bool(
        re.search(
            r'<meta\s+name="agenda-visual-audit"\s+content="required">',
            source,
        )
    )


def run_visual_audit(chrome: str, html_path: Path) -> dict[str, object] | None:
    source = html_path.read_text(encoding="utf-8")
    audit_required = visual_audit_required(source)
    if 'id="agenda-audit-result"' not in source:
        if audit_required:
            raise ValueError(
                "agenda requires visual audit but the audit result marker is missing"
            )
        return None
    command = [
        chrome,
        "--headless=new",
        *chrome_compatibility_flags(),
        "--disable-gpu",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--no-first-run",
        "--incognito",
        "--virtual-time-budget=1800",
        "--dump-dom",
        html_path.as_uri(),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=12,
    )
    if result.returncode != 0:
        raise ValueError(f"agenda visual audit failed to run with code {result.returncode}")
    report = parse_visual_audit_dump(result.stdout)
    if report is None:
        raise ValueError("agenda visual audit did not produce a result")
    if report.get("ok") is not True:
        failures = report.get("failures")
        detail = json.dumps(failures, ensure_ascii=False)
        raise ValueError(f"agenda visual audit failed: {detail}")
    return report


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

    try:
        visual_audit = run_visual_audit(chrome, html_path)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(
            json.dumps(
                {"ok": False, "errors": [str(exc)]},
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
            *chrome_compatibility_flags(),
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--no-pdf-header-footer",
            "--virtual-time-budget=1800",
            "--run-all-compositor-stages-before-draw",
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
    if pages != expected_pages:
        if pdf_path.is_file():
            pdf_path.unlink()
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": [
                        "final agenda content does not fit on one A4 page: "
                        f"PDF contains {pages} pages. Reduce agenda rows or fixed-information "
                        "components before exporting"
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)

    page_size = page_size_points(pdf_path)
    if page_size is None or not is_a4_portrait(page_size):
        if pdf_path.is_file():
            pdf_path.unlink()
        actual = "unknown" if page_size is None else f"{page_size[0]:.2f} x {page_size[1]:.2f} pt"
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": [
                        f"agenda PDF must be A4 portrait (595.28 x 841.89 pt); got {actual}"
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
                "200",
                "-singlefile",
                str(pdf_path),
                str(output_dir / "agenda"),
            ]
        else:
            command = [
                pdftoppm,
                "-png",
                "-r",
                "200",
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
                *chrome_compatibility_flags(),
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--hide-scrollbars",
                "--no-first-run",
                "--virtual-time-budget=1800",
                "--run-all-compositor-stages-before-draw",
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
                "visual_audit": "passed" if visual_audit is not None else "not_provided",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
