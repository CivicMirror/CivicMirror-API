#!/usr/bin/env python3
"""
NY State Board of Elections — Primary Certification parser.

Parses the certified primary ballot PDF (e.g. the June 23, 2026 amended cert)
into Stage 1 records: contests keyed by (office, district, district2, party)
with ordered candidates, plus the document's Version History changelog used to
detect amendments.

Word-position clustering (not line text) is required because candidate names
wrap across two visual lines with the ballot-order token vertically centered
between them.

Usage:
    python ny_cert_parser.py cert.pdf out.json
"""
import json
import re
import sys
from collections import defaultdict

import pdfplumber

LABELS = ("Office:", "District:", "District2:", "Counties:", "Party:", "Vote For:")
LABEL_KEY = {
    "Office:": "office", "District:": "district", "District2:": "district2",
    "Counties:": "counties", "Party:": "party", "Vote For:": "vote_for",
}
ORDER_TOKENS = re.compile(r"^(Uncontested|Litigation|\d+)$")
ROW_TOL = 3.0          # words within this many pts of vertical share a row
BAND = 13.0            # vertical half-window pairing a name to its order token


def cluster_rows(words):
    """Group words into visual rows by their 'top' coordinate."""
    rows = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        for r in rows:
            if abs(r["top"] - w["top"]) <= ROW_TOL:
                r["words"].append(w)
                r["top"] = (r["top"] + w["top"]) / 2
                break
        else:
            rows.append({"top": w["top"], "words": [w]})
    for r in rows:
        r["words"].sort(key=lambda w: w["x0"])
        r["text"] = " ".join(w["text"] for w in r["words"]).strip()
    return rows


def label_value(row):
    """If a row begins with a known label, return (key, value-after-label)."""
    for lab in LABELS:
        if row["text"].startswith(lab):
            return LABEL_KEY[lab], row["text"][len(lab):].strip()
    return None, None


def parse_contests(pdf):
    contests, cur, pending_words, name_cols = [], None, [], None

    def flush():
        nonlocal cur, pending_words, name_cols
        if cur is not None:
            cur["candidates"] = build_candidates(pending_words, name_cols)
            contests.append(cur)
        pending_words, name_cols, cur = [], None, None

    for page in pdf.pages:
        # x_tolerance=1: the cert's spaces are ~2.5pt; the default (3) absorbs
        # them and merges words ("KathyC.", "WorkingFamilies"). 1 keeps them split.
        words = [w for w in page.extract_words(
            x_tolerance=1, y_tolerance=3, keep_blank_chars=False)]
        for row in cluster_rows(words):
            t = row["text"]
            if t.startswith("Office:"):
                flush()
                cur = {"office": t[len("Office:"):].strip(),
                       "district": "", "district2": "", "counties": "",
                       "party": "", "vote_for": "", "candidates": []}
                continue
            if cur is None:
                continue
            key, val = label_value(row)
            if key:
                cur[key] = val
                continue
            # capture the candidate-table header to learn column x-positions
            if "Candidate Name" in t and "Ballot Order" in t:
                name_cols = [w["x0"] for w in row["words"] if w["text"] == "Candidate"]
                continue
            if t in ("Governor Lt. Governor", "Governor", "Lt. Governor"):
                continue
            pending_words.extend(row["words"])
    flush()
    return contests


def build_candidates(words, name_cols):
    """Pair ballot-order tokens with wrapped name fragments via vertical bands."""
    if not words:
        return []
    order_x = min(w["x0"] for w in words)
    orders, names = [], []
    for w in words:
        txt = w["text"]
        if ORDER_TOKENS.match(txt) and w["x0"] <= order_x + 30:
            orders.append(w)
        else:
            names.append(w)
    if not name_cols:                     # single name column
        name_cols = [min((n["x0"] for n in names), default=order_x + 60)]
    cands = []
    for o in sorted(orders, key=lambda w: w["top"]):
        yc = o["top"]
        order_val = "Uncontested" if o["text"] == "Uncontested" else \
                    "Litigation Pending" if o["text"] == "Litigation" else o["text"]
        cols = []
        for cx in name_cols:
            frags = [n for n in names
                     if abs(n["top"] - yc) <= BAND and abs(n["x0"] - cx) <= 90
                     and n["text"] != "Pending"]
            frags.sort(key=lambda n: (round(n["top"]), n["x0"]))
            cols.append(" ".join(n["text"] for n in frags).strip())
        entry = {"ballot_order": order_val, "name": cols[0]}
        if len(cols) > 1 and cols[1]:
            entry["running_mate"] = cols[1]
        cands.append(entry)
    return cands


def parse_version_history(pdf):
    text = pdf.pages[1].extract_text() if len(pdf.pages) > 1 else ""
    entries, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^\d{2}\.\d{1,2}\.\d{4}$", line):
            cur = {"date": line, "changes": []}
            entries.append(cur)
        elif line.startswith("-") and cur:
            cur["changes"].append(line.lstrip("- ").strip())
    return entries


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "cert.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "ny_cert_2026.json"
    with pdfplumber.open(src) as pdf:
        contests = parse_contests(pdf)
        history = parse_version_history(pdf)

    for c in contests:                       # build the Stage 1 contest key
        c["key"] = "|".join([c["office"], c["district"], c["district2"], c["party"]])

    doc = {"source": src, "contest_count": len(contests),
           "candidate_count": sum(len(c["candidates"]) for c in contests),
           "version_history": history, "contests": contests}
    with open(out, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    parties = defaultdict(int)
    for c in contests:
        parties[c["party"]] += 1
    print(f"contests parsed : {len(contests)}")
    print(f"candidates       : {doc['candidate_count']}")
    print(f"by party         : {dict(parties)}")
    print(f"version entries  : {len(history)} (latest {history[-1]['date'] if history else 'n/a'})")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
