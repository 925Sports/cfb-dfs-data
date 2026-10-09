#!/usr/bin/env python3
"""Fetch DraftKings College Football draftables into drafttable.csv.

Mirrors 925Sports-nfl-dfs-data/fetch_draftkings.py but targets CFB slates.
Classic CFB uses QB / RB / RB / WR / WR / WR / FLEX / SFLEX (no TE, no DST).
Showdown remains CPT + 5 FLEX and may include kickers.

Injury Status and News Flag come from the draftables JSON (status / newsStatus).
The salaries CSV does not include them, so they are overlaid after the CSV parse.
OUT rows are still written; apply_injuries.py zeros projections in players.csv.
"""
import csv
import io
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


def clean_status(value):
    s = str(value or "").strip().upper()
    if s in ("", "NONE", "NULL", "NAN"):
        return ""
    if s == "O":
        return "OUT"
    return s


def clean_news(value):
    s = str(value or "").strip()
    if s.lower() in ("", "none", "null", "nan"):
        return ""
    if s == "2":
        return "Breaking"
    if s == "1":
        return "Recent"
    if s == "0":
        return ""
    return s


def fetch_lobby():
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
                return data, sport
            print(f"No contests for sport={sport}")
        except Exception as e:
            last_err = e
            print(f"sport={sport} failed: {e}")
    raise RuntimeError(f"Failed to fetch CFB contests: {last_err}")


# Classic salary (94) and Showdown captain (95). Skip snake / TD-only / other formats.
KEEP_CONTEST_TYPES = {94, 95}


def _salary_csv_rows(dg_id):
    csv_url = f"https://www.draftkings.com/lineup/getavailableplayerscsv?draftGroupId={dg_id}"
    try:
        r = requests.get(csv_url, headers=HEADERS, timeout=30)
        if r.status_code != 200 or "Name" not in r.text or "ID" not in r.text:
            print(f"    salaries CSV {r.status_code}")
            return []
        text = r.text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text))
        converted = []
        for p in reader:
            name = (p.get("Name") or "").strip()
            draftable_id = (p.get("ID") or "").strip()
            if not name or not draftable_id:
                continue
            roster = (p.get("Roster Position") or "").strip()
            pos = (p.get("Position") or roster or "").split("/")[0].strip()
            if roster == "CPT":
                pos = "CPT"
            game = p.get("Game Info") or ""
            parts = game.split()
            matchup = parts[0] if parts else ""
            away, home = (matchup.split("@") + ["", ""])[:2]
            start = ""
            if len(parts) >= 3:
                raw_start = " ".join(parts[1:3]).replace("ET", "").strip()
                try:
                    start = datetime.strptime(raw_start, "%m/%d/%Y %I:%M%p").replace(
                        tzinfo=ZoneInfo("America/New_York")
                    ).isoformat()
                except Exception:
                    start = ""
            first, _, last = name.partition(" ")
            converted.append({
                "draftableId": draftable_id,
                "playerId": draftable_id,
                "displayName": name,
                "firstName": first,
                "lastName": last,
                "salary": p.get("Salary") or 0,
                "position": pos,
                "teamAbbreviation": p.get("TeamAbbrev") or "",
                "playerImage50": "",
                "injuryStatus": "",
                "newsStatus": "",
                "competition": {
                    "competitionId": matchup,
                    "startTime": start,
                    "name": f"{away} @ {home}" if away and home else game,
                    "homeTeam": {"abbreviation": home},
                    "awayTeam": {"abbreviation": away},
                },
            })
        if converted:
            print(f"    ok {len(converted)} from salaries CSV")
        return converted
    except Exception as e:
        print(f"    salaries CSV error: {e}")
        return []


def _json_draftables(dg_id):
    urls = [
        f"https://api.draftkings.com/sites/US-DK/draftgroups/v1/draftgroups/{dg_id}/draftables",
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg_id}/draftables?format=json",
    ]
    last = None
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            last = r.status_code
            if r.status_code != 200:
                print(f"    {r.status_code} {url.split('/')[2]}")
                continue
            data = r.json()
            rows = data.get("draftables") or []
            if rows:
                print(f"    ok {len(rows)} from {url.split('/')[2]}")
                return rows
        except Exception as e:
            print(f"    error {url.split('/')[2]}: {e}")
            last = e
    print(f"    draftables JSON unavailable ({last})")
    return []


def _available_players(dg_id):
    """Backup status source. Field `i` is P/Q/D/OUT. `news` is 0/1/2."""
    url = f"https://www.draftkings.com/lineup/getavailableplayers?draftGroupId={dg_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"    available players {r.status_code}")
            return []
        data = r.json()
        out = []
        for p in data.get("playerList") or []:
            name = f"{p.get('fn') or ''} {p.get('ln') or ''}".strip()
            pos = (p.get("pn") or "").strip()
            out.append({
                "displayName": name,
                "position": pos,
                "teamAbbreviation": p.get("htabbr") or "",
                "status": p.get("i") or "",
                "newsStatus": p.get("news"),
                "playerId": p.get("pid") or "",
            })
        if out:
            print(f"    ok {len(out)} from getavailableplayers")
        return out
    except Exception as e:
        print(f"    available players error: {e}")
        return []


def _overlay_status(converted, status_rows):
    by_id = {}
    by_name = {}
    for p in status_rows:
        status = clean_status(p.get("status") or p.get("injuryStatus") or p.get("i"))
        news = clean_news(p.get("newsStatus") if p.get("newsStatus") is not None else p.get("news"))
        did = str(p.get("draftableId") or "").strip()
        pid = str(p.get("playerId") or "").strip()
        if did and did != "0":
            by_id[did] = (status, news, pid)
        name = str(p.get("displayName") or "").strip().lower()
        team = str(p.get("teamAbbreviation") or "").strip().upper()
        pos = str(p.get("position") or "").strip().upper()
        if name and (status or news):
            by_name[(name, team, pos)] = (status, news, pid)
            by_name[(name, team, "")] = by_name.get((name, team, "")) or (status, news, pid)
    tagged = 0
    for row in converted:
        status, news, pid = "", "", ""
        hit = by_id.get(str(row.get("draftableId") or "").strip())
        if not hit:
            name = str(row.get("displayName") or "").strip().lower()
            team = str(row.get("teamAbbreviation") or "").strip().upper()
            pos = str(row.get("position") or "").strip().upper()
            hit = by_name.get((name, team, pos)) or by_name.get((name, team, ""))
        if hit:
            status, news, pid = hit
        if status or news:
            tagged += 1
        row["injuryStatus"] = status
        row["newsStatus"] = news
        if pid and pid not in ("", "0") and str(row.get("playerId") or "") == str(row.get("draftableId") or ""):
            row["playerId"] = pid
    print(f"    injury overlay tagged {tagged}/{len(converted)}")
    return converted


def fetch_draftables(dg_id):
    """CSV keeps the upload IDs the optimizer exports. JSON supplies injury status."""
    converted = _salary_csv_rows(dg_id)
    json_rows = _json_draftables(dg_id)
    if converted:
        if json_rows:
            return {"draftables": _overlay_status(converted, json_rows)}
        avail = _available_players(dg_id)
        if avail:
            return {"draftables": _overlay_status(converted, avail)}
        return {"draftables": converted}
    if json_rows:
        for p in json_rows:
            p["injuryStatus"] = clean_status(p.get("status") or p.get("injuryStatus"))
            p["newsStatus"] = clean_news(p.get("newsStatus"))
        return {"draftables": json_rows}
    print("    all endpoints failed")
    return None


def main():
    print("Fetching DraftKings CFB contests...")
    try:
        lobby, sport_used = fetch_lobby()
    except Exception as e:
        print(f"Failed to fetch contests: {e}")
        return

    contests = lobby.get("Contests") or []
    lobby_groups = lobby.get("DraftGroups") or []

    draft_groups = {}
    for g in lobby_groups:
        ctype = g.get("ContestTypeId")
        if ctype not in KEEP_CONTEST_TYPES:
            continue
        dg = str(g.get("DraftGroupId") or "")
        if not dg:
            continue
        game_count = int(g.get("GameCount") or 0)
        suffix = (g.get("ContestStartTimeSuffix") or "").strip()
        start_est = g.get("StartDateEst") or g.get("StartDate") or ""
        if ctype == 95 or game_count == 1:
            slate_type = "Showdown Captain Mode"
        elif "night" in suffix.lower() and "late" in suffix.lower():
            slate_type = "Late Night"
        elif "night" in suffix.lower():
            slate_type = "Night"
        elif "afternoon" in suffix.lower():
            slate_type = "Afternoon"
        elif "early" in suffix.lower():
            slate_type = "Early"
        else:
            weekday = ""
            try:
                weekday = datetime.fromisoformat(str(start_est).split(".")[0]).strftime("%A")
            except Exception:
                weekday = ""
            if game_count and game_count <= 3 and weekday:
                slate_type = f"{weekday} {game_count}-Game"
            elif weekday:
                slate_type = weekday
            else:
                slate_type = "Classic"
        draft_groups[dg] = {
            "slate_type": slate_type,
            "contest_ids": [],
            "contest_names": [],
            "game_count": game_count,
            "suffix": suffix,
            "start_est": start_est,
        }

    for c in contests:
        name = (c.get("n") or c.get("Name") or "").lower()
        if "best ball" in name or "pick6" in name or "pick 6" in name or "snake" in name:
            continue
        dg = str(c.get("dg") or c.get("DraftGroupId") or "")
        cid = str(c.get("id") or c.get("ContestId") or "")
        cname = c.get("n") or c.get("Name") or ""
        if not dg or not cid:
            continue
        if dg not in draft_groups:
            continue
        draft_groups[dg]["contest_ids"].append(cid)
        draft_groups[dg]["contest_names"].append(cname)

    print(f"Found {len(draft_groups)} CFB draft groups")
    for dg, g in draft_groups.items():
        print(f"  {dg}: {g['slate_type']} games={g.get('game_count')} suffix={g.get('suffix')!r}")

    rows = []
    headers = [
        "Player Name - Slate Type", "Contest IDs", "Player ID", "Draftable ID",
        "Player Name", "First Name", "Last Name", "Salary", "Position", "Team",
        "Game", "Game Start Time", "Player Image", "Tournament", "Slate Type",
        "Game Type", "Date", "Role", "Contest Names", "Contest IDs (Full)", "Slate Header",
        "Injury Status", "News Flag",
    ]

    for dg_id, group in draft_groups.items():
        print(f"Fetching draftables for {dg_id}...")
        salary_data = fetch_draftables(dg_id)
        if not salary_data:
            print(f"  Failed {dg_id}: no draftables")
            continue

        draftables = salary_data.get("draftables", [])
        if not draftables:
            print(f"  Empty draftables for {dg_id}")
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
                matchup = f"{away} @ {home}".strip(" @")
                comps[cid] = {"matchup": matchup, "startTime": st}
                if st:
                    try:
                        start_times.append(datetime.fromisoformat(st.replace("Z", "+00:00")))
                    except Exception:
                        pass

        num_games = len(comps) or int(group.get("game_count") or 0)
        if num_games == 1:
            group["slate_type"] = "Showdown Captain Mode"

        slate_header = group["slate_type"]
        if start_times:
            min_start = min(start_times)
            local = min_start.astimezone(ZoneInfo("America/New_York"))
            slate_date = local.strftime("%-m/%-d")
            time_part = local.strftime("%-I:%M%p")
            if num_games == 1:
                matchup = list(comps.values())[0]["matchup"]
                suffix = (group.get("suffix") or "").strip(" ()")
                if (not matchup or matchup in ("@",)) and suffix:
                    matchup = suffix
                if matchup and matchup not in ("@",):
                    slate_header = f"Showdown Captain Mode {slate_date} {time_part} ({matchup})"
                else:
                    slate_header = f"Showdown Captain Mode {slate_date} {time_part}"
            else:
                label = group.get("slate_type") or "Classic"
                slate_header = f"{label} {slate_date} {time_part}, {num_games} Games"

        player_versions = defaultdict(list)
        for p in draftables:
            player_id = str(p.get("playerId") or "")
            draftable_id = str(p.get("draftableId") or "")
            name = p.get("displayName") or "Unknown"
            first = p.get("firstName") or ""
            last = p.get("lastName") or ""
            salary = p.get("salary") or 0
            try:
                salary = int(float(str(salary).replace(",", "").replace("$", "") or 0))
            except (TypeError, ValueError):
                salary = 0
            pos = p.get("position") or ""
            if pos == "TE":
                pos = "WR"
            team = p.get("teamAbbreviation") or p.get("team") or ""
            image = p.get("playerImage50") or p.get("imageUrl") or ""
            comp = p.get("competition") or {}
            comp_id = str(comp.get("competitionId") or "")
            game = comps.get(comp_id, {}).get("matchup", "")
            start = comps.get(comp_id, {}).get("startTime", "")
            tournament = comp.get("name") or ""
            injury_status = clean_status(p.get("injuryStatus") or p.get("status"))
            news_flag = clean_news(p.get("newsStatus"))
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
                "injury_status": injury_status,
                "news_flag": news_flag,
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
                        slate_header or group["slate_type"],
                        ";".join(group["contest_names"][:10]),
                        ";".join(group["contest_ids"][:20]),
                        slate_header,
                        ver["injury_status"],
                        ver["news_flag"],
                    ])
            else:
                seen = {}
                for v in versions:
                    key = (v["salary"], v["pos"], v["team"], v["name"])
                    if key not in seen or int(v["draftable_id"]) < int(seen[key]["draftable_id"]):
                        seen[key] = v
                for v in seen.values():
                    role = slate_header or group["slate_type"]
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
                        v["injury_status"],
                        v["news_flag"],
                    ])

    if not rows:
        print("No player rows generated")
        return

    rows.sort(key=lambda x: int(x[7]) if str(x[7]).isdigit() else 0, reverse=True)
    with open("drafttable.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    out_n = sum(1 for r in rows if str(r[-2]).upper() == "OUT")
    print(f"Wrote {len(rows)} rows to drafttable.csv (sport={sport_used}, OUT={out_n})")


if __name__ == "__main__":
    main()
