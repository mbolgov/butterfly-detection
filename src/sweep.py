"""Recompute all confidence thresholds from the saved detector outputs on CPU."""
import argparse
import json
from pathlib import Path

from evaluate import ROOT, write_csv
from runner import load_jsonl, maximum_matches, select_boxes


def metrics(tp, fp, fn):
    denominator = 2 * tp + fp + fn
    return dict(tp=tp, fp=fp, fn=fn, precision=tp/(tp+fp) if tp+fp else 0,
                recall=tp/(tp+fn) if tp+fn else 0, f1=2*tp/denominator if denominator else 0)


def sweep(name, config, records, plan, gold, dev):
    if len(records) != len(gold) or {r["photo_id"] for r in records} != gold.keys():
        raise ValueError(f"Incomplete records for {name}")
    thresholds = plan["thresholds"][config["model"]]
    totals = {(cut, split, iou): [0, 0, 0] for cut in thresholds
              for split in ("dev", "holdout", "all") for iou in plan["iou"]}
    for record in records:
        pid = record["photo_id"]
        truth = gold[pid]
        candidates = record["candidates"]
        split = "dev" if pid in dev else "holdout"
        previous_count = None
        # Thresholds only remove candidates. Recompute NMS when that set changes.
        for cut in thresholds:
            count = len(candidates) if cut is None else sum(c["score"] >= cut for c in candidates)
            if count != previous_count:
                boxes = select_boxes(candidates, cut, config["settings"]["nms_iou"])
                matches = [(iou, maximum_matches(truth, boxes, iou)) for iou in plan["iou"]]
                previous_count = count
            for iou, tp in matches:
                for sample in (split, "all"):
                    row = totals[cut, sample, iou]
                    row[0] += tp
                    row[1] += len(boxes) - tp
                    row[2] += len(truth) - tp
    return [dict(variant=name, model=config["model"], threshold=cut, split=split, iou=iou, **metrics(*values))
            for (cut, split, iou), values in totals.items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=ROOT/"runs_local/candidates")
    parser.add_argument("--output", type=Path, default=ROOT/"recomputed/threshold_sweep.csv")
    args = parser.parse_args()
    plan = json.loads((ROOT/"experiments/plan.json").read_text(encoding="utf-8"))
    gold = {r["photo_id"]: r["boxes"] for r in load_jsonl(ROOT/"data/annotations.jsonl")}
    dev = set(plan["dev_ids"])
    results = []
    for name, config in plan["configs"].items():
        if config["model"] == "qwen":
            continue
        rows = load_jsonl(args.records/f"{name}.jsonl")
        grid = sweep(name, config, rows, plan, gold, dev)
        results.extend(grid)
        dev_f1 = {(r["threshold"], r["iou"]): r["f1"] for r in grid if r["split"] == "dev"}
        best = max(plan["thresholds"][config["model"]], key=lambda t: (dev_f1[t, 0.5], dev_f1[t, 0.75]))
        print(f"{name}: {best:.2f}")
    write_csv(args.output, results)
    print(f"Saved {len(results)} rows to {args.output}")


if __name__ == "__main__":
    main()
