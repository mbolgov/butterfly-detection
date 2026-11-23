"""Скачать фотографии проекта или Контеста и проверить SHA-256."""
import argparse
import csv
import hashlib
import sys
from http.client import HTTPException
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent


def download(row, output):
    url = row["photo_url"]
    photo_id = row["photo_id"]
    if row["license_code"] != "cc0":
        raise ValueError("в списке источников не указана лицензия CC0")
    path = output / (photo_id + Path(url).suffix.lower())
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=45) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise ValueError("SHA-256 скачанного оригинала отличается от сохранённого")
    with TemporaryDirectory(dir=path.parent) as tmp:
        temp_path = Path(tmp) / path.name
        temp_path.write_bytes(content)
        temp_path.replace(path)
    return True


def selected_photos(stages, group, output):
    for stage in stages:
        folder = output or HERE / stage / "images"
        with (HERE / stage / "photos.tsv").open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file, delimiter="\t"):
                subgroup = row.get("group", "")
                if group is None or group == (subgroup or stage):
                    yield row, folder / subgroup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", choices=("pilot", "main", "test"),
                        help="набор фотографий (по умолчанию pilot и main)")
    parser.add_argument("--group", help="одна группа внутри этапа, например hidden")
    parser.add_argument("--output", type=Path, help="папка для скачанных групп")
    args = parser.parse_args()

    downloaded = skipped = errors = 0
    stages = [args.stage] if args.stage else ["pilot", "main"]
    for row, folder in selected_photos(stages, args.group, args.output):
        try:
            if download(row, folder):
                downloaded += 1
            else:
                skipped += 1
        except (OSError, HTTPException, ValueError) as exc:
            print(f"{row['photo_id']}: {exc}", file=sys.stderr)
            errors += 1
    if downloaded + skipped + errors == 0:
        parser.error(f"Группа {args.group!r} отсутствует в выбранном этапе")
    print(f"Скачано: {downloaded}. Уже на месте: {skipped}. Ошибок: {errors}.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
