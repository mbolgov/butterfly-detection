"""Сравнить состав теста Контеста с 400 рабочими фото команды."""
import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from urllib.request import urlopen


HERE = Path(__file__).resolve().parent

GROUPS = {"Plantae": "plant", "Coleoptera": "beetle", "Hymenoptera": "hymenopteran"}
TAXA = {47126: "Plantae", 47208: "Coleoptera", 47201: "Hymenoptera", 47224: "Papilionoidea"}
NAMES = {"butterfly": "Взрослые бабочки", "plant": "Растения", "beetle": "Жуки",
         "hymenopteran": "Перепончатокрылые", "caterpillar": "Гусеницы"}


def load_photos(stage):
    with (HERE / stage / "photos.tsv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file, delimiter="\t"))
    if stage == "main":
        rows = [r for r in rows if r["group"] == "main"]
    ids = {int(r["photo_id"]) for r in rows}
    if len(ids) != 400 or len(rows) != 400:
        raise ValueError(f"{stage}: ожидаются 400 разных фото")
    if stage == "test":
        with (HERE.parent / "contest/dataset.jsonl").open(encoding="utf-8") as file:
            if ids != {json.loads(line)["photo_id"] for line in file}:
                raise ValueError("Список тестовых фото расходится с датасетом Контеста")
    return rows


def category(group, stage, photo_id):
    if group in GROUPS:
        return GROUPS[group]
    if group == "Papilionoidea" and stage in ("Adult", "Larva"):
        return "butterfly" if stage == "Adult" else "caterpillar"
    raise ValueError(f"Фото {photo_id}: проверьте таксон {group!r} и Life Stage {stage!r}")


def api_categories(rows):
    for start in range(0, len(rows), 50):
        if start:
            time.sleep(1)
        batch = rows[start:start + 50]
        observation_ids = [row["observation_url"].rsplit("/", 1)[1] for row in batch]
        url = "https://api.inaturalist.org/v1/observations/" + ",".join(observation_ids)
        with urlopen(url + "?per_page=50", timeout=60) as reply:
            results = json.load(reply)["results"]
        by_photo = {(str(obs["id"]), p["id"]): obs for obs in results for p in obs["photos"]}
        for row, obs_id in zip(batch, observation_ids):
            photo_id = int(row["photo_id"])
            obs = by_photo[obs_id, photo_id]
            taxon = obs["taxon"]
            lineage = set(taxon["ancestor_ids"]) | {taxon["id"]}
            group, = (TAXA[t] for t in TAXA if t in lineage)
            stages = {a["controlled_value_id"] for a in obs.get("annotations", [])
                      if a["controlled_attribute_id"] == 1}
            stage = ", ".join({2: "Adult", 6: "Larva"}.get(value, str(value)) for value in sorted(stages))
            yield category(group, stage, photo_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", action="store_true", help="запросить метаданные заново в iNaturalist")
    args = parser.parse_args()
    test = load_photos("test")
    classes = (category(r["taxon_group"], r["life_stage"], r["photo_id"]) for r in test)
    test_counts = Counter(api_categories(test) if args.api else classes)
    team_counts = Counter(NAMES[row["category"]] for row in load_photos("main"))
    print(f"{'Категория':20} {'Тест':>5} {'Team':>5}")
    for key, name in NAMES.items():
        print(f"{name:20} {test_counts[key]:5} {team_counts[name]:5}")


if __name__ == "__main__":
    main()
