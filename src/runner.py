"""Portable, resumable inference for separate team and contest datasets."""
import csv
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import sys
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_VERSION = "butterfly-inference-2026-11-18-v2"
BOX_KEYS = {"left", "top", "width", "height"}

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"Duplicate JSON key: {k}")
        out[k] = v
    return out

def reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")

def strict_json(text):
    return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=reject_constant)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()

def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")

def write_jsonl(path, rows):
    atomic_text(path, "".join(canonical(row) + "\n" for row in rows))

def load_jsonl(path):
    rows = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Empty line {i} in {path}")
        rows.append(strict_json(line))
    return rows

def photo_sources(stage):
    folder = Path(__file__).resolve().parents[1] / "data_collection" / stage
    with (folder / "photos.tsv").open(encoding="utf-8-sig", newline="") as source:
        return [dict(row, photo_id=int(row["photo_id"])) for row in csv.DictReader(source, delimiter="\t")
                if stage == "test" or row["group"] == "main"]


def validate_manifest(rows, expected=400):
    ids = []
    for r in rows:
        if not isinstance(r, dict) or set(r) != {"photo_id", "photo_url"}:
            raise ValueError("Manifest needs exactly photo_id and photo_url.")
        pid = r["photo_id"]
        if type(pid) is not int or pid <= 0:
            raise ValueError("photo_id must be a positive integer.")
        u = urllib.parse.urlparse(r["photo_url"])
        if u.scheme != "https" or u.hostname != "inaturalist-open-data.s3.amazonaws.com":
            raise ValueError(f"Unexpected original-image URL: {r['photo_url']}")
        if not u.path.startswith(f"/photos/{pid}/original."):
            raise ValueError(f"ID and URL disagree: {pid}")
        ids.append(pid)
    if len(ids) != expected or len(set(ids)) != len(ids):
        raise ValueError(f"Expected {expected} unique images; got {len(ids)}.")
    return rows

def validate_answer(row):
    if not isinstance(row, dict) or set(row) - {"photo_id", "photo_url", "boxes", "error"}:
        raise ValueError("Unexpected output fields.")
    if type(row.get("photo_id")) is not int:
        raise ValueError("Invalid photo_id.")
    if row.get("error") is not None or not isinstance(row.get("boxes"), list):
        raise ValueError("An unfinished/failed answer cannot be exported.")
    for b in row["boxes"]:
        if not isinstance(b, dict) or set(b) != BOX_KEYS:
            raise ValueError("Invalid box keys.")
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
               for v in b.values()):
            raise ValueError("Box values must be finite numbers in [0, 1].")
        if b["width"] <= 0 or b["height"] <= 0:
            raise ValueError("Non-positive box size.")
        if b["left"] + b["width"] > 1 + 1e-9 or b["top"] + b["height"] > 1 + 1e-9:
            raise ValueError("Box outside image.")
    return row

def validate_output(rows, expected_ids):
    ids = [validate_answer(r)["photo_id"] for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise ValueError("Missing, duplicate, or foreign IDs.")
    return True

def image_info(path, expected_sha=None):
    from PIL import Image
    path = Path(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha and sha != expected_sha:
        raise ValueError(f"Image bytes differ from the frozen dataset: {path.name}")
    with Image.open(path) as im:
        im.load()
        orientation = im.getexif().get(274, 1)
        w, h = im.size
    return {"path": str(path.resolve()), "sha256": sha, "width": w, "height": h,
            "exif_orientation": orientation,
            "coordinate_frame": "raw decoded raster; EXIF orientation not applied"}

def prepare_images(rows, expected_hashes, root, local_images=None):
    """Use the exact originals; download only when no valid local file exists."""
    from tqdm.auto import tqdm
    root = Path(root)
    cache = root / "images"
    cache.mkdir(parents=True, exist_ok=True)
    folders = [Path(local_images)] if local_images is not None else []
    folders.append(cache)
    def one(row):
        pid = row["photo_id"]
        expected = expected_hashes[str(pid)]
        for folder in folders:
            for path in sorted(folder.glob(f"{pid}.*")) if folder.exists() else []:
                if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                    try:
                        return pid, image_info(path, expected), None
                    except Exception:
                        pass
        extension = Path(urllib.parse.urlparse(row["photo_url"]).path).suffix.lower()
        dest = cache / f"{pid}{extension}"
        problem = None
        for attempt in range(3):
            tmp = cache / f"{pid}.{uuid.uuid4().hex}.download"
            try:
                req = urllib.request.Request(row["photo_url"],
                    headers={"User-Agent": "ButterflyCourseProject/1.0"})
                with urllib.request.urlopen(req, timeout=60) as response, tmp.open("wb") as f:
                    shutil.copyfileobj(response, f, length=1024 * 1024)
                info = image_info(tmp, expected)
                os.replace(tmp, dest)
                info["path"] = str(dest.resolve())
                return pid, info, None
            except Exception as exc:
                problem = f"{type(exc).__name__}: {exc}"
                if attempt < 2:
                    time.sleep(1 + attempt)
            finally:
                if tmp.exists():
                    tmp.unlink()
        return pid, None, problem
    found, failures = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, r) for r in rows]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Фотографии"):
            pid, info, err = future.result()
            if err:
                failures.append({"photo_id": pid, "error": err})
            else:
                found[pid] = info
    write_json(root / "image_audit.json", {"images": found, "errors": failures})
    if failures:
        raise RuntimeError(f"Не готовы {len(failures)} фото. См. image_audit.json. "
                           "Повторите ячейку; недоступные источники сообщите преподавателю.")
    assert set(found) == {r["photo_id"] for r in rows}
    return found

def normalize_xyxy(values, width, height, strict_bounds=False):
    if len(values) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Expected four finite coordinates.")
    x1, y1, x2, y2 = map(float, values)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Reversed or degenerate box.")
    if strict_bounds and not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Generated coordinates are outside the declared coordinate system.")
    x1, x2 = max(0.0, min(width, x1)), max(0.0, min(width, x2))
    y1, y2 = max(0.0, min(height, y1)), max(0.0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1 / width, y1 / height, x2 / width, y2 / height]

def xyxy_iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area
    return area / union if union > 0 else 0.0

def select_boxes(candidates, score_threshold, nms_iou):
    ordered = []
    for i, c in enumerate(candidates):
        score, box = c["score"], c["xyxy"]
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError("Invalid confidence score.")
        normalize_xyxy(box, 1, 1, strict_bounds=True)
        if score_threshold is None or score >= score_threshold:
            ordered.append((i, c))
    ordered.sort(key=lambda item: (-item[1]["score"], item[0]))
    kept = []
    for _, c in ordered:
        if nms_iou is None or all(xyxy_iou(c["xyxy"], other["xyxy"]) <= nms_iou for other in kept):
            kept.append(c)
    boxes = []
    for c in kept:
        x1, y1, x2, y2 = c["xyxy"]
        boxes.append({"left": x1, "top": y1, "width": x2-x1, "height": y2-y1})
    return boxes

def parse_qwen(text):
    """Strict JSON; only an explicit [] is a negative prediction."""
    text = text.strip()
    match = re.fullmatch(r"(?:\x60){3}(?:json)?\s*(.*?)\s*(?:\x60){3}", text, flags=re.S | re.I)
    if match:
        text = match.group(1)
    data = strict_json(text)
    if not isinstance(data, list):
        raise ValueError("Qwen must return a JSON list.")
    candidates = []
    for item in data:
        if not isinstance(item, dict) or not {"bbox_2d"} <= set(item) or set(item) - {"bbox_2d", "label"}:
            raise ValueError("Expected bbox_2d and optional label.")
        if "label" in item and not isinstance(item["label"], str):
            raise ValueError("Qwen label must be text.")
        box = normalize_xyxy(item["bbox_2d"], 1000, 1000, strict_bounds=True)
        candidates.append({"xyxy": box, "score": 1.0})
    return candidates

def runtime_info(require_cuda=True):
    import torch
    packages = {}
    for name in ("torch", "torchvision", "transformers", "accelerate", "huggingface-hub",
                 "safetensors", "Pillow", "numpy", "tqdm", "scipy"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    if require_cuda and not torch.cuda.is_available():
        raise RuntimeError("CUDA не найдена. Выберите kernel с CUDA PyTorch и проверьте драйвер NVIDIA.")
    info = {"python": sys.version, "platform": platform.platform(), "packages": packages,
            "cuda_runtime": torch.version.cuda, "cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        prop = torch.cuda.get_device_properties(0)
        info.update(gpu=prop.name, vram_gib=prop.total_memory / 1024**3,
                    cudnn=torch.backends.cudnn.version())
    return info

def configure_torch():
    import numpy as np
    import torch
    random.seed(20261118)
    np.random.seed(20261118)
    torch.manual_seed(20261118)
    torch.cuda.manual_seed_all(20261118)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True, warn_only=True)

def device_inputs(inputs, dtype):
    import torch
    return {k: v.to(device="cuda:0", dtype=dtype if v.is_floating_point() else v.dtype)
            if torch.is_tensor(v) else v for k, v in inputs.items()}

class ModelAdapter:
    def __init__(self, key, cfg):
        import torch
        from transformers import (AutoProcessor, GroundingDinoConfig,
                                  GroundingDinoForObjectDetection, Owlv2ForObjectDetection,
                                  Qwen3VLForConditionalGeneration)
        self.key, self.cfg = key, cfg
        self.dtype = getattr(torch, cfg["dtype"])
        common = {"revision": cfg["revision"], "trust_remote_code": False}
        modern = int(importlib.metadata.version("transformers").split(".")[0]) >= 5
        processor_options = ({"backend": "torchvision" if key == "qwen" else "pil"}
                             if modern else {"use_fast": key == "qwen"})
        if key == "qwen":
            self.processor = AutoProcessor.from_pretrained(
                cfg["model_id"], **processor_options, **common)
            self.model = Qwen3VLForConditionalGeneration.from_pretrained(
                cfg["model_id"], dtype=self.dtype, attn_implementation=cfg["attention"],
                use_safetensors=True, **common).to("cuda:0").eval()
        else:
            self.processor = AutoProcessor.from_pretrained(cfg["model_id"], **processor_options, **common)
            if key == "dino":
                config = GroundingDinoConfig.from_pretrained(cfg["model_id"], **common)
                config.disable_custom_kernels = cfg["disable_custom_kernels"]
                self.model = GroundingDinoForObjectDetection.from_pretrained(
                    cfg["model_id"], config=config, dtype=self.dtype, use_safetensors=True,
                    **common).to("cuda:0").eval()
            else:
                self.model = Owlv2ForObjectDetection.from_pretrained(
                    cfg["model_id"], dtype=self.dtype, use_safetensors=True,
                    **common).to("cuda:0").eval()
        self.model.requires_grad_(False)

    def predict(self, image):
        import torch
        cfg = self.cfg
        with torch.inference_mode():
            if self.key == "qwen":
                messages = [{"role": "user", "content": [
                    {"type": "image"}, {"type": "text", "text": cfg["prompt"]}]}]
                text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = self.processor(text=[text], images=[image], return_tensors="pt",
                                        images_kwargs={"size": {"shortest_edge": cfg["min_pixels"],
                                                                "longest_edge": cfg["max_pixels"]}})
                inputs.pop("token_type_ids", None)
                grid = inputs["image_grid_thw"].tolist()
                inputs = device_inputs(inputs, self.dtype)
                result = self.model.generate(
                    **inputs, do_sample=cfg["do_sample"], num_beams=cfg["num_beams"],
                    max_new_tokens=cfg["max_new_tokens"], use_cache=True,
                    repetition_penalty=cfg["repetition_penalty"])
                generated = result[0, inputs["input_ids"].shape[1]:]
                raw_text = self.processor.decode(generated, skip_special_tokens=True,
                                                 clean_up_tokenization_spaces=False)
                eos = self.model.generation_config.eos_token_id
                eos = eos if isinstance(eos, list) else [eos]
                truncated = len(generated) >= cfg["max_new_tokens"] and int(generated[-1]) not in eos
                return {"raw_text": raw_text, "generated_tokens": len(generated),
                        "image_grid_thw": grid, "truncated": truncated}
            text = cfg["prompt"] if self.key == "dino" else [cfg["queries"]]
            inputs = self.processor(images=image, text=text, return_tensors="pt")
            inputs = device_inputs(inputs, self.dtype)
            result = self.model(**inputs)
            logits = result.logits
            if self.key == "dino":
                # DINO extends the text dimension with -inf before applying sigmoid.
                active = inputs["attention_mask"].bool()
                active = torch.nn.functional.pad(active, (0, logits.shape[-1] - active.shape[-1]))
                valid_logits = torch.isfinite(logits) | (~active[:, None, :] & torch.isneginf(logits))
            else:
                valid_logits = torch.isfinite(logits)
            if not valid_logits.all():
                raise ValueError(f"{self.key}: invalid detection logits.")
            if not torch.isfinite(result.pred_boxes).all():
                raise ValueError(f"{self.key}: non-finite box coordinates.")
            if self.key == "dino":
                processed = self.processor.post_process_grounded_object_detection(
                    result, inputs["input_ids"], threshold=cfg["candidate_floor"],
                    text_threshold=cfg["text_threshold"], target_sizes=[(image.height, image.width)])[0]
            else:
                processed = self.processor.post_process_grounded_object_detection(
                    result, threshold=cfg["candidate_floor"],
                    target_sizes=[(image.height, image.width)])[0]
            raw_boxes = processed["boxes"].float().cpu().tolist()
            scores = processed["scores"].float().cpu().tolist()
            candidates, clipped_out = [], 0
            for box, score in zip(raw_boxes, scores):
                normalized = normalize_xyxy(box, image.width, image.height)
                if normalized is None:
                    clipped_out += 1
                else:
                    candidates.append({"xyxy": normalized, "score": score})
            return {"candidates": candidates, "raw_boxes_xyxy_pixels": raw_boxes,
                    "raw_scores": scores, "clipped_outside_image": clipped_out}

    def close(self):
        self.model = None
        self.processor = None
        gc.collect()
        import torch
        torch.cuda.empty_cache()

def run_identity(key, cfg, rows, images, environment, engine_sha):
    return {"pipeline_version": PIPELINE_VERSION, "engine_sha256": engine_sha,
            "model_key": key, "settings": cfg, "dataset_sha256": digest(rows),
            "image_hashes": {str(r["photo_id"]): images[r["photo_id"]]["sha256"] for r in rows},
            "environment": environment,
            "coordinate_policy": "original RGB raster; no EXIF rotation; normalized xyxy",
            "seed": 20261118, "batch_size": 1, "tf32": False}

def cached_record(path, run_hash, image_sha):
    if not path.exists():
        return None
    record = strict_json(path.read_text(encoding="utf-8"))
    if record.get("run_hash") != run_hash or record.get("image_sha256") != image_sha:
        raise ValueError(f"Cache provenance mismatch: {path}")
    if record.get("status") == "ok":
        validate_answer({"photo_id": record["photo_id"],
                         "boxes": select_boxes(record["candidates"], None, None), "error": None})
    return record

def records_for(run_dir, rows, images):
    meta = strict_json((Path(run_dir)/"run_config.json").read_text(encoding="utf-8"))
    found, missing = [], []
    for row in rows:
        pid = row["photo_id"]
        rec = cached_record(Path(run_dir)/"records"/f"{pid}.json", meta["run_hash"], images[pid]["sha256"])
        if rec is None or rec.get("status") != "ok":
            missing.append(pid)
        else:
            found.append(rec)
    return found, missing

def process_pending(adapter, key, cfg, run_dir, rows, images, run_hash, sync=None, max_consecutive_errors=3):
    """Saving one file per image makes interrupted writes harmless and retries explicit."""
    from PIL import Image
    from tqdm.auto import tqdm
    sync = sync or (lambda: None)
    consecutive = 0
    for row in tqdm(rows, desc=key):
        pid = row["photo_id"]
        info = images[pid]
        path = Path(run_dir)/"records"/f"{pid}.json"
        prior = cached_record(path, run_hash, info["sha256"])
        if prior and prior.get("status") == "ok":
            continue
        rec = {"photo_id": pid, "image_sha256": info["sha256"], "run_hash": run_hash,
               "attempt_utc": utc_now(), "status": "error"}
        started = time.perf_counter()
        should_stop = False
        try:
            with Image.open(info["path"]) as source:
                image = source.convert("RGB")
            sync()
            started = time.perf_counter()
            raw = adapter.predict(image)
            sync()
            rec["inference_seconds"] = time.perf_counter() - started
            rec.update(raw)
            if key == "qwen":
                if raw["truncated"]:
                    raise ValueError("Qwen output reached max_new_tokens; no partial answer is accepted.")
                rec["candidates"] = parse_qwen(raw["raw_text"])
            validate_answer({"photo_id": pid, "boxes": select_boxes(rec["candidates"], None, None), "error": None})
            rec["status"] = "ok"
            consecutive = 0
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["attempt_seconds"] = time.perf_counter() - started
            consecutive += 1
            with (Path(run_dir)/"errors.jsonl").open("a", encoding="utf-8") as f:
                f.write(canonical(rec)+"\n")
                f.flush()
            print(f"\nphoto_id={pid}: {rec['error']}")
            should_stop = consecutive >= max_consecutive_errors or "out of memory" in str(exc).lower()
        write_json(path, rec)
        if should_stop:
            raise RuntimeError("Прогон остановлен после повторных ошибок или нехватки VRAM. "
                               "Успешные фото сохранены; подробности в errors.jsonl.")

def run_model(key, cfg, rows, images, root, engine_sha, limit=None):
    import torch
    from PIL import Image
    env = runtime_info()
    configure_torch()
    identity = run_identity(key, cfg, rows, images, env, engine_sha)
    run_hash = digest(identity)
    run_dir = Path(root)/"runs"/f"{key}_{run_hash[:12]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir/"run_config.json"
    if config_path.exists():
        existing = strict_json(config_path.read_text(encoding="utf-8"))
        if existing["run_hash"] != run_hash or existing["identity"] != identity:
            raise ValueError("Configuration mismatch; refusing to mix runs.")
    else:
        write_json(config_path, {"run_hash": run_hash, "created_utc": utc_now(), "identity": identity})
    selected = rows if limit is None else random.Random(20261118).sample(rows, min(limit, len(rows)))
    pending = []
    for row in selected:
        pid = row["photo_id"]
        rec = cached_record(run_dir/"records"/f"{pid}.json", run_hash, images[pid]["sha256"])
        if not rec or rec.get("status") != "ok":
            pending.append(row)
    print(f"{key}: готовы {len(selected)-len(pending)}/{len(selected)}; папка {run_dir}")
    if not pending:
        return run_dir
    adapter = None
    try:
        adapter = ModelAdapter(key, cfg)
        # Warm-up is excluded from per-image timings and recorded separately.
        with Image.open(images[pending[0]["photo_id"]]["path"]) as source:
            warm_image = source.convert("RGB")
        adapter.predict(warm_image)
        torch.cuda.synchronize()
        process_pending(adapter, key, cfg, run_dir, pending, images, run_hash, torch.cuda.synchronize)
    finally:
        if adapter is not None:
            adapter.close()
        gc.collect()
        torch.cuda.empty_cache()
    recs, missing = records_for(run_dir, selected, images)
    times = [r["inference_seconds"] for r in recs]
    print(f"{key}: готово {len(recs)}/{len(selected)}; ошибок/пропусков {len(missing)}")
    if times:
        mean = statistics.mean(times)
        print(f"Среднее {mean:.2f} с/фото; ориентир на 400: {400*mean/60:.1f} мин без загрузки весов.")
    if missing:
        raise RuntimeError(f"Остались ошибки: {missing[:10]}. Повторите эту ячейку после разбора errors.jsonl.")
    return run_dir

def object_iou(a, b):
    return xyxy_iou([a["left"], a["top"], a["left"]+a["width"], a["top"]+a["height"]],
                    [b["left"], b["top"], b["left"]+b["width"], b["top"]+b["height"]])

def maximum_matches(gold, predicted, threshold):
    adjacency = [[j for j, target in enumerate(gold) if object_iou(box, target) >= threshold]
                 for box in predicted]
    matched = [-1]*len(gold)
    def augment(i, visited):
        for j in adjacency[i]:
            if j in visited:
                continue
            visited.add(j)
            if matched[j] == -1 or augment(matched[j], visited):
                matched[j] = i
                return True
        return False
    return sum(augment(i, set()) for i in range(len(predicted)))
