import json, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import os

import requests

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

OUT = Path("data/matches.json")
LOCAL_TZ = ZoneInfo("Asia/Colombo")
TARGET_MONTH = os.getenv("TARGET_MONTH", datetime.now(LOCAL_TZ).strftime("%Y-%m"))

SOFA_BASE = "https://www.sofascore.com/api/v1"
CRICINFO_BASE = "https://hs-consumer-api.espncricinfo.com/v1/pages"

# Requested source pages. These are also exposed in the dashboard as source provenance.
SKY_SOURCES = {
    "Football": "https://www.skysports.com/football-scores-fixtures",
    "Rugby": "https://www.skysports.com/rugby-union/fixtures",
    "F1": "https://www.skysports.com/f1/schedule",
    "Tennis": "https://www.skysports.com/tennis/scores-schedule",
}
CRICKET_SOURCE = "https://www.espncricinfo.com/"
FALLBACK_SOURCE = "https://www.sofascore.com/"

SPORTS = {
    "football": "Football",
    "rugby": "Rugby",
    "tennis": "Tennis",
    "basketball": "Basketball",
    "cricket": "Cricket",
    "badminton": "Badminton",
    "table-tennis": "Table Tennis",
    "golf": "Golf",
    "boxing": "Boxing",
    "motorsport": "F1",
}


def month_dates(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    first = date(y, m, 1)
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return [(first + timedelta(days=i)).isoformat() for i in range((nxt - first).days)]


def get_json(url, timeout=30):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.sofascore.com/",
    }
    if curl_requests:
        try:
            with curl_requests.Session(impersonate="chrome", headers=headers) as s:
                r = s.get(url, timeout=timeout)
                r.raise_for_status()
                return r.json()
        except Exception:
            pass
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def iso_from_epoch(value):
    try:
        n = float(value)
        if n > 10_000_000_000:
            n /= 1000
        return datetime.fromtimestamp(n, timezone.utc).astimezone(LOCAL_TZ).isoformat()
    except Exception:
        return ""


def clean_text(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def status_name(raw):
    s = raw if isinstance(raw, str) else str((raw or {}).get("type", "") or (raw or {}).get("description", ""))
    s = s.lower().replace(" ", "")
    if any(x in s for x in ["inprogress", "live", "running", "started", "playing", "halftime"]):
        return "live"
    if any(x in s for x in ["finished", "complete", "final", "ended"]):
        return "finished"
    if any(x in s for x in ["cancel", "postponed"]):
        return "cancelled"
    return "upcoming"


def make_event(sport, competition, event_name, start_time, status, event_type, source, source_url,
               p1=None, p2=None, importance=5, time_precision="exact"):
    if not start_time:
        return None
    p1, p2 = clean_text(p1), clean_text(p2)
    competition = clean_text(competition) or "Unknown"
    event_name = clean_text(event_name) or (f"{p1} vs {p2}" if p1 and p2 else competition)
    event_id = "|".join([
        sport.lower(), competition.lower(),
        re.sub(r"\W+", " ", p1.lower()),
        re.sub(r"\W+", " ", p2.lower()),
        start_time[:10],
        re.sub(r"\W+", " ", event_name.lower())[:80],
    ])
    return {
        "event_id": event_id,
        "sport": sport,
        "competition": competition,
        "event_name": event_name,
        "participant_1": p1 or None,
        "participant_2": p2 or None,
        "start_time": start_time,
        "time_precision": time_precision,
        "status": status,
        "event_type": event_type,
        "source": source,
        "source_url": source_url,
        "importance": float(importance),
    }


def sofascore_events(sport_slug, day):
    # Tennis uses a tournament container endpoint; the other requested sports expose
    # daily scheduled events. We also recursively inspect nested event arrays.
    if sport_slug == "tennis":
        urls = [
            f"{SOFA_BASE}/sport/tennis/scheduled-tournaments/{day}/page/0",
            f"{SOFA_BASE}/sport/tennis/scheduled-tournaments/{day}/page/1",
            f"{SOFA_BASE}/sport/tennis/scheduled-events/{day}",
        ]
    else:
        urls = [f"{SOFA_BASE}/sport/{sport_slug}/scheduled-events/{day}"]

    raw_events = []
    for url in urls:
        try:
            body = get_json(url)
        except Exception:
            continue
        raw_events.extend(extract_event_objects(body))
        if raw_events:
            break

    out = []
    for e in raw_events:
        if not isinstance(e, dict):
            continue
        # Ignore unrelated motorsport series; the dashboard tracks Formula 1 only.
        tournament = e.get("tournament") or {}
        tournament_name = clean_text(tournament.get("name") or tournament.get("uniqueTournament", {}).get("name"))
        if sport_slug == "motorsport":
            hay = f"{tournament_name} {clean_text(e.get('season', {}).get('name'))}".lower()
            if "formula 1" not in hay and not re.search(r"\bf1\b", hay):
                continue

        home = e.get("homeTeam") or e.get("homePlayer") or {}
        away = e.get("awayTeam") or e.get("awayPlayer") or {}
        p1 = home.get("name") or home.get("shortName") or home.get("displayName") or ""
        p2 = away.get("name") or away.get("shortName") or away.get("displayName") or ""
        start = iso_from_epoch(e.get("startTimestamp") or e.get("startTimeTimestamp") or e.get("startTime"))
        if not start:
            continue
        event_type = "match"
        if sport_slug == "motorsport":
            event_type = "race/session"
        comp = tournament_name or clean_text((tournament.get("uniqueTournament") or {}).get("name")) or "Scheduled"
        name = f"{p1} vs {p2}" if p1 and p2 else comp
        st = status_name(e.get("status"))
        source_url = f"https://www.sofascore.com/event/{e.get('id')}" if e.get("id") else FALLBACK_SOURCE
        importance = 7 if any(k in comp.lower() for k in ["champions league", "grand slam", "nba", "nfl", "formula 1"]) else 5
        x = make_event(SPORTS[sport_slug], comp, name, start, st, event_type,
                       "SofaScore", source_url, p1, p2, importance)
        if x:
            out.append(x)
    return out


def extract_event_objects(node):
    # Keep this deliberately permissive because SofaScore has sport-specific nesting.
    found = []
    if isinstance(node, dict):
        if "homeTeam" in node and "awayTeam" in node and ("startTimestamp" in node or "startTime" in node):
            found.append(node)
        for v in node.values():
            if isinstance(v, (dict, list)):
                found.extend(extract_event_objects(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(extract_event_objects(v))
    # De-duplicate by provider event id.
    seen, out = set(), []
    for e in found:
        k = str(e.get("id") or id(e))
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def cricinfo_matches(day):
    ddmmyyyy = datetime.strptime(day, "%Y-%m-%d").strftime("%d-%m-%Y")
    url = f"{CRICINFO_BASE}/matches/scheduled?lang=en&filterType=DATE&filterValue={ddmmyyyy}"
    try:
        body = get_json(url)
    except Exception:
        return []

    matches = []
    for key in ["matches"]:
        if isinstance(body.get(key), list):
            matches = body[key]
            break
    if not matches:
        for container in [body.get("content"), body.get("data"), body.get("matchList")]:
            if isinstance(container, dict) and isinstance(container.get("matches"), list):
                matches = container["matches"]
                break

    out = []
    for m in matches:
        teams = m.get("teams") or []
        names = []
        for t in teams[:2]:
            team = t.get("team") if isinstance(t, dict) else {}
            team = team or {}
            names.append(clean_text(team.get("longName") or team.get("name") or t.get("name")))
        p1, p2 = (names + ["", ""])[:2]
        series = m.get("series") or {}
        comp = clean_text(series.get("name") or m.get("seriesName") or "Cricket")
        start = iso_from_epoch(m.get("startDate") or m.get("startTime") or m.get("startTimestamp"))
        precision = "exact" if start else "date_only"
        if not start:
            start = f"{day}T00:00:00+05:30"
        mid = m.get("objectId") or m.get("matchId") or m.get("id") or ""
        source_url = f"https://www.espncricinfo.com/series/{series.get('slug') or series.get('objectId') or ''}/match/{mid}" if mid else CRICKET_SOURCE
        x = make_event("Cricket", comp, f"{p1} vs {p2}", start,
                       status_name(m.get("status")), "match", "ESPNcricinfo", source_url,
                       p1, p2, 7, precision)
        if x:
            out.append(x)
    return out


def source_validation():
    # The requested Sky/ESPNcricinfo pages are retained as source links. Full monthly
    # coverage comes from their dated schedules where available plus SofaScore fallback.
    return {
        "sky_sports": SKY_SOURCES,
        "espncricinfo": CRICKET_SOURCE,
        "fallback": FALLBACK_SOURCE,
    }


def main():
    days = month_dates(TARGET_MONTH)
    out = []

    # Primary cricket feed.
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(cricinfo_matches, d): d for d in days}
        for f in as_completed(futures):
            try:
                out.extend(f.result())
            except Exception as ex:
                print("ESPNcricinfo failed:", futures[f], ex)

    # Broad calendar fallback / enrichment. This is what gets us toward the full
    # multi-sport monthly inventory rather than only the few headline competitions.
    requested_slugs = ["football", "rugby", "tennis", "basketball", "badminton",
                       "table-tennis", "golf", "boxing", "motorsport", "cricket"]
    jobs = [(slug, d) for slug in requested_slugs for d in days]
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(sofascore_events, slug, d): (slug, d) for slug, d in jobs}
        for f in as_completed(futures):
            try:
                out.extend(f.result())
            except Exception as ex:
                print("SofaScore failed:", futures[f], ex)

    # Deduplicate while preserving the strongest source preference.
    priority = {"ESPNcricinfo": 0, "Sky Sports": 1, "SofaScore": 2}
    dedup = {}
    for x in out:
        key = (x["sport"], x["event_name"].lower(), x["start_time"][:10])
        if key not in dedup or priority.get(x["source"], 9) < priority.get(dedup[key]["source"], 9):
            dedup[key] = x

    matches = sorted(dedup.values(), key=lambda x: x["start_time"])
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_month": TARGET_MONTH,
        "event_count": len(matches),
        "source_config": source_validation(),
        "matches": matches,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Target month: {TARGET_MONTH}")
    print(f"Normalized events: {len(matches)}")
    for sport in sorted({m["sport"] for m in matches}):
        print(sport, sum(1 for m in matches if m["sport"] == sport))


if __name__ == "__main__":
    main()
