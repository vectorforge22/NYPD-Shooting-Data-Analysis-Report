"""Download and pin the official NYC Open Data snapshots used by the revamp."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "official"
USER_AGENT = "NYPD-shooting-analysis-revamp/1.0 (reproducible research download)"

DATASETS = {
    "shootings": {
        "id": "5ucz-vwe8",
        "title": "Shootings (2006-Present)",
        "filename": "shootings_2006_present.csv",
        "download": True,
    },
    "victims": {
        "id": "pztn-9bne",
        "title": "Shooting Victims (2006-Present)",
        "filename": "shooting_victims_2006_present.csv",
        "download": True,
    },
    "offenders": {
        "id": "gdk4-mbsv",
        "title": "Shooting Offenders (2006-Present)",
        "filename": "shooting_offenders_2006_present.csv",
        "download": True,
    },
    "archived_combined": {
        "id": "833y-fsy8",
        "title": "ARCHIVED_NYPD Shooting Incident Data (Historic)",
        "filename": None,
        "download": False,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    os.replace(temporary, destination)


def verify_snapshot(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: list[tuple[str, str]] = []
    for record in manifest["datasets"].values():
        checks.append((record["metadata_file"], record["metadata_sha256"]))
        if "csv_file" in record:
            checks.append((record["csv_file"], record["csv_sha256"]))
    legacy = manifest["legacy_project_snapshot"]
    checks.append((legacy["file"], legacy["sha256"]))

    for relative_path, expected_hash in checks:
        path = ROOT / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Pinned snapshot file is missing: {relative_path}")
        actual_hash = sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(f"Pinned snapshot checksum mismatch: {relative_path}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace an existing pinned snapshot.")
    args = parser.parse_args()

    manifest_path = RAW_DIR / "manifest.json"
    if manifest_path.exists() and not args.force:
        manifest = verify_snapshot(manifest_path)
        print(f"Verified existing snapshot retrieved at {manifest['retrieved_at_utc']}")
        return
    if not args.force and RAW_DIR.exists() and any(RAW_DIR.iterdir()):
        raise FileExistsError(
            "Official snapshot files exist without a manifest; inspect them, then use --force to replace them."
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest: dict[str, object] = {
        "retrieved_at_utc": retrieved_at,
        "python": platform.python_version(),
        "source": "NYC Open Data / NYPD Shootings collection",
        "license_and_terms": "https://opendata.cityofnewyork.us/overview/#termsofuse",
        "datasets": {},
    }

    for name, config in DATASETS.items():
        dataset_id = config["id"]
        metadata_url = f"https://data.cityofnewyork.us/api/views/{dataset_id}.json"
        landing_url = f"https://data.cityofnewyork.us/d/{dataset_id}"
        csv_url = f"https://data.cityofnewyork.us/api/views/{dataset_id}/rows.csv?accessType=DOWNLOAD"
        metadata_path = RAW_DIR / f"{name}_{dataset_id}_metadata.json"

        download(metadata_url, metadata_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        record: dict[str, object] = {
            "id": dataset_id,
            "title": config["title"],
            "landing_url": landing_url,
            "metadata_url": metadata_url,
            "metadata_file": metadata_path.relative_to(ROOT).as_posix(),
            "metadata_sha256": sha256(metadata_path),
            "metadata_rows_updated_at": metadata.get("rowsUpdatedAt"),
            "metadata_rows_updated_by": metadata.get("rowsUpdatedBy"),
            "metadata_view_last_modified": metadata.get("viewLastModified"),
        }

        if config["download"]:
            csv_path = RAW_DIR / str(config["filename"])
            download(csv_url, csv_path)
            record.update(
                {
                    "csv_url": csv_url,
                    "csv_file": csv_path.relative_to(ROOT).as_posix(),
                    "csv_bytes": csv_path.stat().st_size,
                    "csv_sha256": sha256(csv_path),
                }
            )

        manifest["datasets"][name] = record
        print(f"Pinned {config['title']} ({dataset_id})")

    legacy_path = ROOT / "data" / "raw" / "NYPD_Shooting_Incident_Data__Historic_.csv"
    manifest["legacy_project_snapshot"] = {
        "file": legacy_path.relative_to(ROOT).as_posix(),
        "bytes": legacy_path.stat().st_size,
        "sha256": sha256(legacy_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Acquisition failed: {exc}", file=sys.stderr)
        raise
