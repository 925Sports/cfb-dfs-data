#!/usr/bin/env python3
"""Fetch DraftKings College Football draftables into drafttable.csv.

Mirrors 925Sports-nfl-dfs-data/fetch_draftkings.py but targets CFB slates.
Classic CFB uses QB / RB / RB / WR / WR / WR / FLEX / SFLEX (no TE, no DST).
Showdown remains CPT + 5 FLEX and may include kickers.
"""
import csv
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.draftkings.com/lobby#/CFB",
    "Origin": "https://www.draftkings.com",
}

# DK has used both codes historically; try them in order.
SPORT_CODES = ("CFB", "CF", "COLLEGEFOOTBALL")


def format_datetime(iso_str):
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        return dt.strftime("%m/%d/%Y %I:%M %p")
    except Exception:
        return iso_str


def format_date_only(iso_str):
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        return dt.strftime("%-m/%-d")
    except Exception:
        return ""


def classify_slate(name, num_games=None):
    n = (name or "").lower()
    if "showdown" in n or "captain" in n:
        return "Showdown Captain Mode"
    if "turbo" in n:
        return "Turbo"
    if "late" in n:
        return "Late"
    if "early" in n:
        return "Early"
    if "night" in n:
        return "Night"
    if "thursday" in n or "thu" in n:
        return "Thursday"
    if "friday" in n:
        return "Friday"
    if "saturday" in n:
        return "Saturday"
    if num_games == 1:
        return "Showdown Captain Mode"
    return "Classic"


def fetch_contests():
    last_err = None
    for sport in SPORT_CODES:
        url = f"https://www.draftkings.com/lobby/getcontests?sport={sport}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
            contests = data.get("Contests", [])
            if contests:
                print(f"Found {len(contests)} contests using sport={sport}")
                return contests, sport
            print(f"No contests for sport={sport}")
        except Exception as e:
            last_err = e
            print(f"sport={sport} failed: {e}")
    raise RuntimeError(f"Failed to fetch CFB contests: {last_err}")


def main():
    print("Fetching DraftKings CFB contests...")
    try:
        contests, sport_used = fetch_contests()
    except Exception as e:
        print(f"Failed to fetch contests: {e}")
        return

    draft_groups = {}
    for c in contests:
        name = (c.get("n") or c.get("Name") or "").lower()
        if "best ball" in name or "pick6" in name or "pick 6" in name:
            continue
        dg = str(c.get("dg") or c.get("DraftGroupId") or "")
        cid = str(c.get("id") or c.get("ContestId") or "")
        cname = c.get("n") or c.get("Name") or ""
        if not dg or not cid:
            continue
        slate_type = classify_slate(cname)
        if dg not in draft_groups:
            draft_groups[dg] = {
                "slate_type": slate_type,
                "contest_ids": [],
                "contest_names": [],
            }
        draft_groups[dg]["contest_ids"].append(cid)
        draft_groups[dg]["contest_names"].append(cname)
        draft_groups[dg]["slate_type"] = slate_type

    print(f"Found {len(draft_groups)} CFB draft groups")

    rows = []
    headers = [
        "Player Name - Slate Type", "Contest IDs", "Player ID", "Draftable ID",
        "Player Name", "First Name", "Last Name", "Salary", "Position", "Team",
        "Game", "Game Start Time", "Player Image", "Tournament", "Slate Type",
        "Game Type", "Date", "Role", "Contest Names", "Contest IDs (Full)", "Slate Header",
    ]

    for dg_id, group in draft_groups.items():
        print(f"Fetching draftables for {dg_id}...")
        url = f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg_id}/draftables?format=json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f"  Failed {dg_id}: {r.status_code}")
                continue
            salary_data = r.json()
        except Exception as e:
            print(f"  Error {dg_id}: {e}")
            continue

        draftables = salary_data.get("draftables", [])
        if not draftables:
            continue

        comps = {}
        start_times = []
        for p in draftables:
            comp = p.get("competition") or {}
            cid = str(comp.get("competitionId") or "")
            if cid and cid not in comps:
                home = (comp.get("homeTeam") or {}).get("abbreviation") or comp.get("homeTeamAbbreviation") or ""
                away = (comp.get("awayTeam") or {}).get("abbreviation") or comp.get("awayTeamAbbreviation") or ""
                st = comp.get("startTime") or ""
                comps[cid] = {"matchup": f"{away} @ {home}", "startTime": st}
                if st:
                    try:
                        start_times.append(datetime.fromisoformat(st.replace("Z", "+00:00")))
                    except Exception:
                        pass

        num_games = len(comps)
        if num_games == 1:
            group["slate_type"] = "Showdown Captain Mode"

        slate_header = group["slate_type"]
        if start_times:
            min_start = min(start_times)
            slate_date = min_start.astimezone(ZoneInfo("America/New_York")).strftime("%-m/%-d")
            time_part = min_start.astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M%p")
            if num_games == 1:
                matchup = list(comps.values())[0]["matchup"]
                slate_header = f"{slate_date} {time_part} ({matchup})"
            else:
                slate_header = f"{slate_date} {time_part}, {num_games} Games"

        player_versions = defaultdict(list)
        for p in draftables:
            player_id = str(p.get("playerId") or "")
            draftable_id = str(p.get("draftableId") or "")
            name = p.get("displayName") or "Unknown"
            first = p.get("firstName") or ""
            last = p.get("lastName") or ""
            salary = p.get("salary") or 0
            pos = p.get("position") or ""
            # CFB lists TEs as WR on DK Classic. Keep CPT/K as-is for Showdown.
            if pos == "TE":
                pos = "WR"
            team = p.get("teamAbbreviation") or p.get("team") or ""
            image = p.get("playerImage50") or p.get("imageUrl") or ""
            comp = p.get("competition") or {}
            comp_id = str(comp.get("competitionId") or "")
            game = comps.get(comp_id, {}).get("matchup", "")
            start = comps.get(comp_id, {}).get("startTime", "")
            tournament = comp.get("name") or ""
            if salary <= 0 or not player_id or not draftable_id or name == "Unknown":
                continue
            player_versions[player_id].append({
                "draftable_id": draftable_id,
                "name": name,
                "first": first,
                "last": last,
                "salary": salary,
                "pos": pos,
                "team": team,
                "image": image,
                "game": game,
                "start": start,
                "tournament": tournament,
                "date": format_date_only(start),
            })

        is_showdown = "Showdown" in group["slate_type"]
        for player_id, versions in player_versions.items():
            versions.sort(key=lambda x: x["salary"], reverse=True)
            if is_showdown and len(versions) >= 2:
                cpt = versions[0]
                flex = versions[1]
                for ver, role_pos, role_label in (
                    (cpt, "CPT", "Captain"),
                    (flex, flex["pos"], "Flex"),
                ):
                    rows.append([
                        f"{ver['name']} - {group['slate_type']} ({role_label})",
                        ";".join(group["contest_ids"][:20]),
                        player_id,
                        ver["draftable_id"],
                        ver["name"],
                        ver["first"],
                        ver["last"],
                        ver["salary"],
                        role_pos,
                        ver["team"],
                        ver["game"],
                        format_datetime(ver["start"]),
                        ver["image"],
                        ver["tournament"],
                        group["slate_type"],
                        "CFB",
                        ver["date"],
                        role_label,
                        ";".join(group["contest_names"][:10]),
                        ";".join(group["contest_ids"][:20]),
                        slate_header,
                    ])
            else:
                seen = {}
                for v in versions:
                    key = (v["salary"], v["pos"], v["team"], v["name"])
                    if key not in seen or int(v["draftable_id"]) < int(seen[key]["draftable_id"]):
                        seen[key] = v
                for v in seen.values():
                    # Role string used by the optimizer as the slate key.
                    role = group["slate_type"]
                    if slate_header and slate_header != group["slate_type"]:
                        role = f"{group['slate_type']} {slate_header}" if group["slate_type"] not in slate_header else slate_header
                    # Prefer the richer Role style used in the cheat sheet:
                    # "Night 9/5 12:00PM, 12 Games"
                    role = slate_header if slate_header else group["slate_type"]
                    rows.append([
                        f"{v['name']} - {group['slate_type']}",
                        ";".join(group["contest_ids"][:20]),
                        player_id,
                        v["draftable_id"],
                        v["name"],
                        v["first"],
                        v["last"],
                        v["salary"],
                        v["pos"],
                        v["team"],
                        v["game"],
                        format_datetime(v["start"]),
                        v["image"],
                        v["tournament"],
                        group["slate_type"],
                        "CFB",
                        v["date"],
                        role,
                        ";".join(group["contest_names"][:10]),
                        ";".join(group["contest_ids"][:20]),
                        slate_header,
                    ])

    if not rows:
        print("No player rows generated")
        return

    rows.sort(key=lambda x: int(x[7]) if str(x[7]).isdigit() else 0, reverse=True)
    with open("drafttable.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to drafttable.csv (sport={sport_used})")


if __name__ == "__main__":
    main()
