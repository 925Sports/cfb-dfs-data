#!/usr/bin/env python3
"""Join drafttable.csv Injury Status onto players.csv and zero confirmed Outs.

Only OUT / IR / OFS / suspended are zeroed. Q, D, and P keep their projections.
Join key is Draftable ID. CPT and FLEX are separate IDs and are handled on their own rows.
"""
import csv
import os

OUT = {"OUT", "O", "IR", "OFS", "SUSP", "SUSPENDED", "OUT FOR SEASON"}
ZERO_COLS = ("Projected FP", "Combined FP", "Implied FP", "Fantasy Score", "Value")


def load_status(path):
    status_by_did = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            did = (row.get("Draftable ID") or "").strip()
            if not did:
                continue
            status_by_did[did] = {
                "Injury Status": (row.get("Injury Status") or "").strip().upper(),
                "News Flag": (row.get("News Flag") or "").strip(),
            }
    return status_by_did


def apply(path, status_by_did):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        print(f"Skip {path}: missing or empty")
        return 0

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    if "Draftable ID" not in fields:
        print(f"Skip {path}: no Draftable ID column")
        return 0

    for col in ("Injury Status", "News Flag"):
        if col not in fields:
            fields.append(col)

    out_n = 0
    matched = 0
    for row in rows:
        info = status_by_did.get((row.get("Draftable ID") or "").strip())
        if not info:
            row.setdefault("Injury Status", "")
            row.setdefault("News Flag", "")
            continue
        matched += 1
        status = info["Injury Status"]
        row["Injury Status"] = status
        row["News Flag"] = info["News Flag"]
        if status in OUT:
            out_n += 1
            for col in ZERO_COLS:
                if col in row:
                    row[col] = "0"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"{path}: matched {matched}, zeroed {out_n} OUT rows")
    return out_n


def main():
    if not os.path.exists("drafttable.csv"):
        raise SystemExit("drafttable.csv not found. Run fetch_draftkings.py first.")
    status_by_did = load_status("drafttable.csv")
    tagged = sum(1 for v in status_by_did.values() if v["Injury Status"])
    print(f"Loaded {len(status_by_did)} draftables, {tagged} with a status")
    apply("players.csv", status_by_did)


if __name__ == "__main__":
    main()
