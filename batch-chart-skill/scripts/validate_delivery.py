#!/usr/bin/env python3
"""Validate the deterministic parts of an academic JPG delivery bundle."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import zipfile
from pathlib import Path


FILENAME_HEADERS = ("文件名", "filename", "file", "jpg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path, help="Folder containing final JPG files and figure_manifest.csv")
    parser.add_argument("--zip", dest="zip_path", type=Path, help="ZIP archive containing the same delivery folder")
    parser.add_argument("--json-out", type=Path, help="Write a machine-readable report")
    parser.add_argument("--min-count", type=int, default=10)
    parser.add_argument("--max-count", type=int, default=30)
    parser.add_argument("--min-width", type=int, default=1)
    parser.add_argument("--min-height", type=int, default=1)
    return parser.parse_args()


def load_manifest(path: Path) -> tuple[list[dict[str, str]], str | None]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return rows, None
    headers = {header.strip().lower(): header for header in rows[0] if header}
    for alias in FILENAME_HEADERS:
        if alias.lower() in headers:
            return rows, headers[alias.lower()]
    return rows, None


def main() -> int:
    args = parse_args()
    failures: list[str] = []
    warnings: list[str] = []
    folder = args.folder.resolve()
    manifest = folder / "figure_manifest.csv"

    if not folder.is_dir():
        failures.append(f"Delivery folder does not exist: {folder}")
        return finish(args, folder, [], [], failures, warnings)

    jpgs = sorted(
        (item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg"}),
        key=lambda item: item.name.lower(),
    )
    if not args.min_count <= len(jpgs) <= args.max_count:
        failures.append(f"JPG count {len(jpgs)} is outside {args.min_count}-{args.max_count}")

    image_records: list[dict[str, object]] = []
    try:
        from PIL import Image
    except ImportError:
        failures.append("Pillow is required for JPG decode checks: python -m pip install Pillow")
    else:
        for jpg in jpgs:
            record: dict[str, object] = {"file": jpg.name, "bytes": jpg.stat().st_size}
            try:
                with Image.open(jpg) as image:
                    image.verify()
                with Image.open(jpg) as image:
                    width, height = image.size
                    record.update(format=image.format, mode=image.mode, width=width, height=height)
                    if width < args.min_width or height < args.min_height:
                        failures.append(
                            f"{jpg.name} is {width}x{height}, below {args.min_width}x{args.min_height}"
                        )
            except Exception as exc:  # Pillow exposes several decode exception classes.
                record["error"] = str(exc)
                failures.append(f"Cannot decode {jpg.name}: {exc}")
            image_records.append(record)

    manifest_records: list[dict[str, str]] = []
    filename_header: str | None = None
    if not manifest.is_file():
        failures.append("figure_manifest.csv is missing")
    else:
        try:
            manifest_records, filename_header = load_manifest(manifest)
        except Exception as exc:
            failures.append(f"Cannot read figure_manifest.csv: {exc}")
        if filename_header is None:
            failures.append("Manifest lacks a filename column (文件名/filename/file/jpg)")
        else:
            listed = [row.get(filename_header, "").strip() for row in manifest_records]
            actual = [jpg.name for jpg in jpgs]
            if len(listed) != len(set(listed)):
                failures.append("Manifest contains duplicate filenames")
            if set(listed) != set(actual):
                missing = sorted(set(actual) - set(listed))
                extra = sorted(set(listed) - set(actual))
                failures.append(f"Manifest/JPG mismatch; unlisted={missing}, nonexistent={extra}")

    if args.zip_path:
        zip_path = args.zip_path.resolve()
        if not zip_path.is_file():
            failures.append(f"ZIP does not exist: {zip_path}")
        else:
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    bad = archive.testzip()
                    if bad:
                        failures.append(f"ZIP CRC failure: {bad}")
                    names = [Path(name.replace("\\", "/")).name for name in archive.namelist() if not name.endswith("/")]
                expected = {jpg.name for jpg in jpgs} | {"figure_manifest.csv"}
                delivered = {name for name in names if name}
                if expected != delivered:
                    failures.append(
                        f"ZIP entries differ from delivery folder; missing={sorted(expected-delivered)}, extra={sorted(delivered-expected)}"
                    )
            except (OSError, zipfile.BadZipFile) as exc:
                failures.append(f"Cannot open ZIP: {exc}")

    if image_records and len({(r.get("width"), r.get("height")) for r in image_records}) > 1:
        warnings.append("Final JPG dimensions are not uniform; confirm that the variation is intentional")

    return finish(args, folder, image_records, manifest_records, failures, warnings)


def finish(
    args: argparse.Namespace,
    folder: Path,
    images: list[dict[str, object]],
    manifest_rows: list[dict[str, str]],
    failures: list[str],
    warnings: list[str],
) -> int:
    report = {
        "folder": str(folder),
        "jpg_count": len(images),
        "manifest_rows": len(manifest_rows),
        "pass": not failures,
        "failures": failures,
        "warnings": warnings,
        "images": images,
        "note": "This script does not replace final-size visual and statistical review.",
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
