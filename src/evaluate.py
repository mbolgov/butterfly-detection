"""Recompute the 20 configurations on the frozen team labels with standard Python."""
import argparse
import csv
import json
import statistics
from pathlib import Path

from runner import load_jsonl, maximum_matches, photo_sources, validate_output

ROOT = Path(__file__).resolve().parents[1]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def score(ids, gold, predictions):
    true_boxes = sum(len(gold[i]) for i in ids)
    predicted_boxes = sum(len(predictions[i]) for i in ids)
    negatives = [i for i in ids if not gold[i]]
    denom = true_boxes + predicted_boxes
    matches = {}
    for threshold in (0.5, 0.75):
        matches[threshold] = sum(maximum_matches(gold[i], predictions[i], threshold) for i in ids)
    tp = matches[0.5]
    return dict(photos=len(ids), tp=tp, fp=predicted_boxes-tp, fn=true_boxes-tp,
                precision=tp/predicted_boxes if predicted_boxes else 0,
                recall=tp/true_boxes if true_boxes else 0, f1=2*tp/denom if denom else 0,
                f1_all_iou75=2*matches[0.75]/denom if denom else 0,
                empty_photos=len(negatives), fp_on_empty=sum(len(predictions[i]) for i in negatives),
                empty_with_fp=sum(bool(predictions[i]) for i in negatives))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write leaderboard.csv and by_group.csv")
    args = parser.parse_args()
    plan = json.loads((ROOT/"experiments/plan.json").read_text(encoding="utf-8"))
    data = photo_sources("main")
    ids = [r["photo_id"] for r in data]
    dev = set(plan["dev_ids"])
    holdout = [pid for pid in ids if pid not in dev]
    if len(ids) != 400 or len(dev) != 300 or len(holdout) != 100:
        raise ValueError("Invalid team dataset or threshold selection split")
    gold_rows = load_jsonl(ROOT/"data/annotations.jsonl")
    validate_output(gold_rows, ids)
    gold = {r["photo_id"]: r["boxes"] for r in gold_rows}
    groups = {group: [r["photo_id"] for r in data if r["category"] == group]
              for group in sorted({r["category"] for r in data})}
    with (ROOT/"experiments/timings.csv").open(encoding="utf-8", newline="") as file:
        timings = list(csv.DictReader(file))
    if len(timings) != len(ids) or {int(r["photo_id"]) for r in timings} != set(ids):
        raise ValueError("Incomplete inference timings")
    scores, by_group = [], []
    for name, cfg in plan["configs"].items():
        threshold = cfg["selected_threshold"]
        rows = load_jsonl(ROOT/f"experiments/predictions/{name}.jsonl")
        validate_output(rows, ids)
        predictions = {r["photo_id"]: r["boxes"] for r in rows}
        metrics = score(ids, gold, predictions)
        metrics["f1_dev"] = score(dev, gold, predictions)["f1"]
        metrics["f1_holdout"] = score(holdout, gold, predictions)["f1"]
        scores.append(dict(variant=name, model=cfg["model"], threshold=threshold, **metrics,
                           seconds_per_photo=statistics.mean(float(r[name]) for r in timings)))
        for group, members in groups.items():
            by_group.append(dict(variant=name, group=group, **score(members, gold, predictions)))
    scores.sort(key=lambda r: -r["f1"])
    for row in scores:
        print(f"{row['variant']:22s}  F1@.50 {row['f1']:.4f}  F1@.75 {row['f1_all_iou75']:.4f}"
              f"   TP {row['tp']:3}   FP {row['fp']:3}   FN {row['fn']:3}")
    if args.output:
        write_csv(args.output/"leaderboard.csv", scores)
        write_csv(args.output/"by_group.csv", by_group)


if __name__ == "__main__":
    main()
