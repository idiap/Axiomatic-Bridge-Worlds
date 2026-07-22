# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
# SPDX-License-Identifier: MIT

"""Extract the release archive to the canonical seeded-v2 runner path."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = REPO_ROOT / "dataset" / "abw-formal-nl-core.zip"
DEFAULT_OUTPUT = REPO_ROOT / "dataset" / "abw-formal-nl-core"
ARCHIVE_ROOT = "abw-formal-nl-core/"


def extract_archive(archive_path: Path, output: Path, *, force: bool) -> int:
    if output.exists():
        if not force:
            raise FileExistsError(f"Dataset already exists: {output}. Use --force to replace it.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if not info.filename.startswith(ARCHIVE_ROOT):
                    raise ValueError(f"Unexpected archive member: {info.filename}")
                relative = Path(info.filename.removeprefix(ARCHIVE_ROOT))
                if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Unsafe archive member: {info.filename}")
                destination = output / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                count += 1
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    count = extract_archive(Path(args.archive), Path(args.output), force=args.force)
    print(f"Extracted {count} files to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
