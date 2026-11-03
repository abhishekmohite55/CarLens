"""
Dev check (Stage 4): read all text from kept frames with local OCR (RapidOCR = PaddleOCR models on onnxruntime).
No Gemini call, no post-processing: prints every text piece found, its score and box.

Install once into the venv (not in requirements.txt until decided):
    pip install rapidocr onnxruntime

Saves to runs/_checks/ocr/<folder>_<HHMMSS>/:
    result.json         per item: file, texts (text, score, box), seconds
    <frame>.jpg         the frame with every text box drawn and numbered

Run from F:\\CarLens\\backend:
    python -m scripts.check_ocr probe_20261102_211502_9188_current L1 L8 L7
    python -m scripts.check_ocr probe_20261102_211502_9188_current          # every item
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

import cv2
import numpy as np
from rapidocr import RapidOCR

from app.config import PROJECT_ROOT
from app.plate import normalise_plate, pick_plate, plates_in_texts

CHECKS_DIR = PROJECT_ROOT / "runs" / "_checks"


def main() -> None:
    ap = argparse.ArgumentParser(description="Read all text from kept frames with RapidOCR.")
    ap.add_argument("folder", help="frames folder name inside runs/_checks, e.g. probe_20261102_211502_9188_current")
    ap.add_argument("item_ids", nargs="*", help="item ids from manifest.json, e.g. L1 L8 L7 (none = all)")
    args = ap.parse_args()

    folder = CHECKS_DIR / args.folder
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    items = [i for i in manifest["items"] if i.get("sharpest")]
    if args.item_ids:
        unknown = set(args.item_ids) - {i["item_id"] for i in items}
        if unknown:
            raise SystemExit(f"not found (or no frame): {', '.join(sorted(unknown))}. "
                             f"Items: {', '.join(i['item_id'] + '=' + str(i.get('category')) for i in items)}")
        items = [i for i in items if i["item_id"] in args.item_ids]

    out_dir = CHECKS_DIR / "ocr" / f"{args.folder}_{datetime.now():%H%M%S}"
    out_dir.mkdir(parents=True)

    t = time.perf_counter()
    engine = RapidOCR()
    load_s = round(time.perf_counter() - t, 2)
    print(f"== OCR engine loaded in {load_s} s", flush=True)

    results = []
    for item in items:
        file = item["sharpest"]["file"]
        img = cv2.imread(str(folder / file))
        t = time.perf_counter()
        out = engine(img)
        seconds = round(time.perf_counter() - t, 2)

        texts = []
        if out.txts:
            for n, (text, score, box) in enumerate(zip(out.txts, out.scores, out.boxes), start=1):
                pts = np.asarray(box, dtype=int)
                texts.append({"n": n, "text": text, "score": round(float(score), 3), "box": pts.tolist()})
                cv2.polylines(img, [pts], True, (0, 0, 255), 2)
                cv2.putText(img, str(n), tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imwrite(str(out_dir / file), img)
        results.append({"item_id": item["item_id"], "category": item.get("category"), "label": item.get("label"),
                        "file": file, "seconds": seconds, "texts": texts})

        print(f"\n  {item['item_id']} {item.get('category')}  {file}  {seconds} s  {len(texts)} text(s)")
        for x in texts:
            print(f"    {x['n']:>2}. {x['text']!r:<30} score {x['score']}")

    # Plate summary
    readings = []
    for item in results:
        item_texts = [x["text"] for x in item["texts"]]
        item_plates = plates_in_texts(item_texts)
        if item_plates:
            best_text, best_score = max(
                ((x["text"], x["score"]) for x in item["texts"]
                 if normalise_plate(x["text"]) in item_plates),
                key=lambda r: r[1],
            )
            readings.append((normalise_plate(best_text), best_score))
    plate = pick_plate(readings, len(results))
    if plate:
        print(f"\n  plate: {plate['text']} ({plate['frames_agree']}/{plate['frames_tried']} frames)")
    else:
        print("\n  plate: not found")

    (out_dir / "result.json").write_text(
        json.dumps({"folder": str(folder), "engine": "rapidocr", "engine_load_s": load_s, "items": results},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  -> {out_dir}")


if __name__ == "__main__":
    main()
