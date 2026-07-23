from __future__ import annotations

import io
import re
from typing import Any

import pdfplumber

LABELS = ("Office:", "District:", "District2:", "Counties:", "Party:", "Vote For:")
LABEL_KEY = {
    "Office:": "office",
    "District:": "district",
    "District2:": "district2",
    "Counties:": "counties",
    "Party:": "party",
    "Vote For:": "vote_for",
}
ORDER_TOKENS = re.compile(r"^(Uncontested|Litigation|\d+)$")
ROW_TOL = 3.0
BAND = 13.0


def cluster_rows(words):
    rows = []
    for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        for row in rows:
            if abs(row["top"] - word["top"]) <= ROW_TOL:
                row["words"].append(word)
                row["top"] = (row["top"] + word["top"]) / 2
                break
        else:
            rows.append({"top": word["top"], "words": [word]})
    for row in rows:
        row["words"].sort(key=lambda w: w["x0"])
        row["text"] = " ".join(w["text"] for w in row["words"]).strip()
    return rows


def label_value(row):
    for label in LABELS:
        if row["text"].startswith(label):
            return LABEL_KEY[label], row["text"][len(label):].strip()
    return None, None


def _append_continuation(cur: dict, key: str | None, text: str):
    if not key or not text:
        return
    cur[key] = f"{cur.get(key, '').strip()} {text.strip()}".strip()


def build_candidates(words, name_cols):
    if not words:
        return []
    token_candidates = [word for word in words if ORDER_TOKENS.match(word["text"])]
    if not token_candidates:
        return []
    order_x = min(word["x0"] for word in token_candidates)
    orders = [word for word in token_candidates if word["x0"] <= order_x + 30]
    order_ids = {id(word) for word in orders}
    names = [word for word in words if id(word) not in order_ids]
    if not name_cols:
        name_cols = [min((word["x0"] for word in names), default=order_x + 60)]

    candidates = []
    for order in sorted(orders, key=lambda word: word["top"]):
        order_value = (
            "Uncontested"
            if order["text"] == "Uncontested"
            else "Litigation Pending"
            if order["text"] == "Litigation"
            else order["text"]
        )
        cols = []
        for col_x in name_cols:
            fragments = [
                word
                for word in names
                if abs(word["top"] - order["top"]) <= BAND
                and abs(word["x0"] - col_x) <= 90
                and word["text"] != "Pending"
            ]
            fragments.sort(key=lambda word: (round(word["top"]), word["x0"]))
            cols.append(" ".join(word["text"] for word in fragments).strip())
        entry = {"ballot_order": order_value, "name": cols[0]}
        if len(cols) > 1 and cols[1]:
            entry["running_mate"] = cols[1]
        candidates.append(entry)
    return candidates


def parse_version_history_text(text: str) -> list[dict]:
    entries = []
    current = None
    for line in (text or "").splitlines():
        line = line.strip()
        if re.match(r"^\d{2}\.\d{1,2}\.\d{4}$", line):
            current = {"date": line, "changes": []}
            entries.append(current)
        elif line.startswith("-") and current:
            current["changes"].append(line.lstrip("- ").strip())
    return entries


def parse_certification_pdf(pdf_bytes: bytes) -> dict:
    contests = []
    current = None
    pending_words = []
    name_cols = None
    last_label_key = None

    def flush():
        nonlocal current, pending_words, name_cols, last_label_key
        if current is not None:
            current["candidates"] = build_candidates(pending_words, name_cols)
            current["key"] = "|".join([current["office"], current["district"], current["district2"], current["party"]])
            contests.append(current)
        current, pending_words, name_cols, last_label_key = None, [], None, None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1, y_tolerance=3, keep_blank_chars=False)
            for row in cluster_rows(words):
                text = row["text"]
                if text.startswith("Office:"):
                    flush()
                    current = {
                        "office": text[len("Office:"):].strip(),
                        "district": "",
                        "district2": "",
                        "counties": "",
                        "party": "",
                        "vote_for": "",
                        "candidates": [],
                    }
                    last_label_key = "office"
                    continue
                if current is None:
                    continue
                key, value = label_value(row)
                if key:
                    current[key] = value
                    last_label_key = key
                    continue
                if "Candidate Name" in text and "Ballot Order" in text:
                    name_cols = [word["x0"] for word in row["words"] if word["text"] == "Candidate"]
                    last_label_key = None
                    continue
                if text in ("Governor Lt. Governor", "Governor", "Lt. Governor"):
                    continue
                if text.startswith("Certification for the"):
                    continue
                if last_label_key in {"counties", "office", "district", "district2", "party", "vote_for"}:
                    _append_continuation(current, last_label_key, text)
                    continue
                pending_words.extend(row["words"])
        version_history = parse_version_history_text(pdf.pages[1].extract_text() if len(pdf.pages) > 1 else "")
    flush()
    return {"contests": contests, "version_history": version_history}


def validate_certification_snapshot(doc: dict[str, Any]) -> list[str]:
    issues = []
    for idx, contest in enumerate(doc.get("contests") or []):
        for key in ("office", "party"):
            if not str(contest.get(key) or "").strip():
                issues.append(f"contest[{idx}] empty {key}")
        counties = str(contest.get("counties") or "").strip()
        if counties.endswith(("Part of", "&", ",")):
            issues.append(f"contest[{idx}] suspicious counties: {counties}")
        if not contest.get("candidates"):
            issues.append(f"contest[{idx}] empty candidates")
        orders = [candidate.get("ballot_order") for candidate in contest.get("candidates") or []]
        numbered = [order for order in orders if str(order or "").isdigit()]
        if len(numbered) != len(set(numbered)):
            issues.append(f"contest[{idx}] duplicated ballot order")
    return issues
