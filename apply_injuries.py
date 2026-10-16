#!/usr/bin/env python3
"""Copy DK Injury Status / News Flag onto players.csv and zero confirmed Outs.

Join key is Draftable ID. Questionable, Doubtful, and Probable keep their projection.
A row the sheet already marked with a manual Injury Status of OUT is also zeroed.
"""
import csv

OUT = {"OUT", "O", "IR", "OFS", "SUSP", "SUSPENDED"}
ZERO_COLS = ("Projected FP", "Combined FP", "Implied FP", "Fantasy Score", "Value")


def main():
    status_by_did = {}
    with open("drafttable.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            did = (row.get("Draftable ID") or "").strip()
            if not did:
                continue
            status_by_did[did] = {
                "Injury Status": (row.get("Injury Status") or "").strip().upper(),
                "News Flag": (row.get("News Flag") or "").strip(),
            }

    with open("players.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    for col in ("Injury Status", "News Flag"):
        if col not in fields:
            fields.append(col)

    out_n = 0
    matched = 0
    for row in rows:
        did = (row.get("Draftable ID") or "").strip()
        info = status_by_did.get(did, {})
        if info:
            matched += 1
        status = info.get("Injury Status") or (row.get("Injury Status") or "").strip().upper()
        if status == "O":
            status = "OUT"
        row["Injury Status"] = status
        if info.get("News Flag"):
            row["News Flag"] = info["News Flag"]
        elif "News Flag" not in row or row["News Flag"] is None:
            row["News Flag"] = ""
        if status in OUT:
            out_n += 1
            for col in ZERO_COLS:
                if col in row:
                    row[col] = "0"

    with open("players.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Matched {matched} draftable IDs. Zeroed {out_n} OUT rows in players.csv")


if __name__ == "__main__":
    main()
