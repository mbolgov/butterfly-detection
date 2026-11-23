"""Найти новые фотографии CC0 в наблюдениях iNaturalist."""
import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


TAXA = {"butterfly": 47224, "plant": 47126, "beetle": 47208,
        "hymenopteran": 47201, "caterpillar": 47224}
FIELDS = ["photo_id", "category", "author", "license_code", "observation_url", "photo_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=TAXA)
    parser.add_argument("--pages", type=int, default=1, help="число страниц по 100 наблюдений")
    parser.add_argument("--output", type=Path, help="куда записать таблицу кандидатов")
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("--pages должно быть больше нуля")
    output = args.output or Path(f"candidates_{args.category}.tsv")
    here = Path(__file__).resolve().parent
    with (here.parent / "contest/dataset.jsonl").open(encoding="utf-8-sig") as file:
        excluded = {json.loads(line)["photo_id"] for line in file if line.strip()}
    used = set()
    for stage in ("pilot", "main"):
        with (here / stage / "photos.tsv").open(encoding="utf-8", newline="") as file:
            used.update(row["observation_url"] for row in csv.DictReader(file, delimiter="\t"))

    params = dict(taxon_id=TAXA[args.category], photos="true", photo_license="cc0",
                  quality_grade="research", per_page=100, order_by="id", order="desc")
    if args.category in ("butterfly", "caterpillar"):
        # Стадия развития в iNaturalist: 2 - взрослая особь, 6 - личинка.
        params.update(term_id=1, term_value_id=2 if args.category == "butterfly" else 6)

    candidates = []
    for page in range(1, args.pages + 1):
        if page > 1:
            time.sleep(1)
        query = urlencode(dict(params, page=page))
        with urlopen("https://api.inaturalist.org/v1/observations?" + query, timeout=45) as response:
            batch = json.load(response)["results"]
        for obs in batch:
            observation_url = f"https://www.inaturalist.org/observations/{obs['id']}"
            if observation_url in used or any(photo["id"] in excluded for photo in obs["photos"]):
                continue
            for photo in obs["photos"]:
                if photo.get("license_code") != "cc0" or photo.get("hidden"):
                    continue
                photo_id = photo["id"]
                pattern = rf"https://inaturalist-open-data\.s3\.amazonaws\.com/photos/{photo_id}/square\.(\w+)"
                if not re.fullmatch(pattern, photo.get("url") or ""):
                    continue
                author = photo.get("name") or obs["user"]["login"]
                original = photo["url"].replace("/square.", "/original.")
                candidates.append([photo_id, args.category, author, photo["license_code"],
                                   observation_url, original])
                used.add(observation_url)
                break
        if len(batch) < params["per_page"]:
            break
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter="\t", lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(candidates)
    print(f"{output}: {len(candidates)} фото")


if __name__ == "__main__":
    main()
