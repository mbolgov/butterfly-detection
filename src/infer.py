"""Run the saved model configurations on the team or Contest images (NVIDIA CUDA)."""
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import runner

ROOT = Path(__file__).resolve().parents[1]


def infer_records(spec, rows, images, output, engine_hash, retry_policy):
    key, cfg = spec["model"], spec["settings"]
    try:
        run_dir = runner.run_model(key, cfg, rows, images, output, engine_hash)
    except RuntimeError:
        if key != "qwen":
            raise
        identity = runner.run_identity(key, cfg, rows, images, runner.runtime_info(), engine_hash)
        run_dir = output/"runs"/f"{key}_{runner.digest(identity)[:12]}"
        if not (run_dir/"run_config.json").is_file():
            raise
        successful, missing = runner.records_for(run_dir, rows, images)
        retry_ids = set(missing)
        if not retry_ids:
            raise
        for pid in retry_ids:
            path = run_dir/"records"/f"{pid}.json"
            if not path.is_file():
                raise
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") != "error" or "reached max_new_tokens" not in record.get("error", ""):
                raise
        retry_rows = [r for r in rows if r["photo_id"] in retry_ids]
        retry_cfg = dict(cfg, repetition_penalty=retry_policy["repetition_penalty"])
        retry_images = {pid: images[pid] for pid in retry_ids}
        retry_dir = runner.run_model(key, retry_cfg, retry_rows, retry_images, output, engine_hash)
        retried, failed = runner.records_for(retry_dir, retry_rows, retry_images)
        if failed:
            raise RuntimeError(f"Incomplete retry: {failed}")
        records = successful + retried
    else:
        records, missing = runner.records_for(run_dir, rows, images)
        if missing:
            raise RuntimeError(f"Incomplete run: {missing}")
    return records


def save_predictions(path, rows, records, threshold, nms_iou):
    indexed = {r["photo_id"]: r for r in records}
    predictions = [dict(photo_id=r["photo_id"], boxes=runner.select_boxes(
        indexed[r["photo_id"]]["candidates"], threshold, nms_iou), error=None) for r in rows]
    runner.validate_output(predictions, [r["photo_id"] for r in rows])
    runner.write_jsonl(path, predictions)


def infer(name, spec, rows, images, output, cut, engine_hash, retry_policy):
    records = infer_records(spec, rows, images, output, engine_hash, retry_policy)
    save_predictions(output/"predictions"/f"{name}.jsonl", rows, records, cut, spec["settings"]["nms_iou"])
    if spec["model"] != "qwen":
        runner.write_jsonl(output/"candidates"/f"{name}.jsonl",
                           ({"photo_id": r["photo_id"], "candidates": r["candidates"]} for r in records))


def main():
    plan = json.loads((ROOT/"experiments/plan.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["all", *plan["configs"]])
    parser.add_argument("--contest", action="store_true", help="use the Contest photos and submission thresholds")
    parser.add_argument("--output", type=Path, help="directory for model records and predictions")
    parser.add_argument("--images", type=Path, help="local directory with the original photos")
    args = parser.parse_args()

    stage = "test" if args.contest else "main"
    sources = runner.photo_sources(stage)
    rows = [{"photo_id": r["photo_id"], "photo_url": r["photo_url"]} for r in sources]
    hashes = {str(r["photo_id"]): r["sha256"] for r in sources}
    if args.contest:
        cuts = {"qwen_old": None, "owlv2_old": 0.45, "dino_old": 0.55}
        variant = args.variant or "qwen_old"
        output = args.output or ROOT/"runs_local/contest"
        local_images = args.images or ROOT/"data_collection/test/images"
    else:
        cuts = {name: cfg["selected_threshold"] for name, cfg in plan["configs"].items()}
        variant = args.variant or "qwen_simple"
        output = args.output or ROOT/"runs_local"
        local_images = args.images or ROOT/"data/images"

    if variant != "all" and variant not in cuts:
        parser.error(f"Available configurations for this dataset: {', '.join(cuts)}")
    runner.validate_manifest(rows)
    engine_hash = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()
    images = runner.prepare_images(rows, hashes, output, local_images)
    for name in (cuts if variant == "all" else [variant]):
        infer(name, plan["configs"][name], rows, images, output, cuts[name],
              engine_hash, plan["qwen_retry_policy"])


if __name__ == "__main__":
    main()
