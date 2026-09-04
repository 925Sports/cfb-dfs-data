#!/usr/bin/env python3
"""Download CFB game odds and write consensus CFBGameOdds.csv."""

from __future__ import annotations

import csv
import io
import os
import statistics
import sys
from collections import defaultdict

import requests

ODDS_CSV_URL = os.environ.get("ODDS_CSV_URL", "").strip() or ""
OUT_FILE = "CFBGameOdds.csv"
TIMEOUT = 60


def to_num(v):
    try:
        return float(str(v).replace("+", "").strip())
    except Exception:
        return None


def mean(xs):
    return round(statistics.mean(xs), 2) if xs else ""


def download(url: str) -> str:
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def rows_from_text(text: str):
    sample = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(sample))
    rows = list(reader)
    start = 0
    for i, row in enumerate(rows):
        joined = ",".join(row).lower()
        if row and (row[0] == "id" or "home_team" in joined or "commence_time" in joined):
            start = i
            break
    if start >= len(rows):
        return [], []
    header = [h.strip() for h in rows[start]]
    return header, rows[start + 1 :]


def consensus_from_raw(header, data):
    idx = {name: i for i, name in enumerate(header)}

    def col(row, name, default=""):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else default

    games = defaultdict(lambda: {
        "id": "", "commence": "", "home": "", "away": "",
        "sh": [], "sa": [], "tot": [], "mh": [], "ma": [], "books": set(),
    })
    for row in data:
        if not row:
            continue
        gid = col(row, "id") or "|".join([col(row, "home_team"), col(row, "away_team"), col(row, "commence_time")])
        home = col(row, "home_team") or col(row, "home")
        away = col(row, "away_team") or col(row, "away")
        if not home or not away:
            continue
        g = games[gid]
        g["id"] = gid
        g["commence"] = col(row, "commence_time") or col(row, "commence") or g["commence"]
        g["home"] = home
        g["away"] = away
        book = col(row, "bookmaker")
        if book:
            g["books"].add(book)
        market = col(row, "market").lower()
        label = col(row, "label")
        price = to_num(col(row, "price"))
        point = to_num(col(row, "point"))
        if market == "spreads" and point is not None:
            if label == home:
                g["sh"].append(point)
            elif label == away:
                g["sa"].append(point)
        elif market == "totals" and point is not None and label.lower() == "over":
            g["tot"].append(point)
        elif market in ("h2h", "ml") and price is not None:
            if label == home:
                g["mh"].append(price)
            elif label == away:
                g["ma"].append(price)

    out = []
    for g in games.values():
        out.append({
            "event_id": g["id"],
            "commence_time": g["commence"],
            "home_team": g["home"],
            "away_team": g["away"],
            "spread_home": mean(g["sh"]),
            "spread_away": mean(g["sa"]),
            "total": mean(g["tot"]),
            "ml_home": mean(g["mh"]),
            "ml_away": mean(g["ma"]),
            "n_books": len(g["books"]),
        })
    out.sort(key=lambda r: r["commence_time"] or "")
    return out


def consensus_from_ready(header, data):
    idx = {name: i for i, name in enumerate(header)}

    def col(row, name, default=""):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else default

    rows = []
    for row in data:
        home = col(row, "home_team") or col(row, "home")
        away = col(row, "away_team") or col(row, "away")
        if not home or not away:
            continue
        rows.append({
            "event_id": col(row, "event_id") or col(row, "id"),
            "commence_time": col(row, "commence_time") or col(row, "commence"),
            "home_team": home,
            "away_team": away,
            "spread_home": col(row, "spread_home"),
            "spread_away": col(row, "spread_away"),
            "total": col(row, "total"),
            "ml_home": col(row, "ml_home"),
            "ml_away": col(row, "ml_away"),
            "n_books": col(row, "n_books") or "",
        })
    return rows


def write_out(rows):
    fields = [
        "event_id", "commence_time", "home_team", "away_team",
        "spread_home", "spread_away", "total", "ml_home", "ml_away", "n_books",
    ]
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    url = (sys.argv[1].strip() if len(sys.argv) > 1 else "") or ODDS_CSV_URL
    if not url:
        print("No odds URL — leaving existing CFBGameOdds.csv alone.")
        return 0
    print(f"Fetching odds from {url[:80]}...")
    text = download(url)
    header, data = rows_from_text(text)
    if not header:
        print("Could not find a header row in the downloaded CSV.", file=sys.stderr)
        return 1
    raw = "market" in header and "bookmaker" in header
    rows = consensus_from_raw(header, data) if raw else consensus_from_ready(header, data)
    if not rows:
        print("Downloaded CSV had no game rows — keeping previous file.", file=sys.stderr)
        return 0
    write_out(rows)
    print(f"Wrote {len(rows)} games to {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
