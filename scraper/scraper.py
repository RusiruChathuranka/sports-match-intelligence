import json, os, re, math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

OUT = Path("data/matches.json")
LOCAL_TZ = ZoneInfo("Asia/Colombo")
TARGET_MONTH = os.getenv("TARGET_MONTH", datetime.now(LOCAL_TZ).strftime("%Y-%m"))
SOFA_BASE = "https://api.sofascore.com/api/v1"
CRICINFO_BASE = "https://hs-consumer-api.espncricinfo.com/v1/pages"

SPORTS = {
    "cricket": "Cricket",
    "football": "Soccer",
    "badminton": "Badminton",
    "basketball": "Basketball",
    "boxing": "Boxing",
    "esports": "Esports",
    "rugby": "Rugby",
    "tennis": "Tennis",
    "volleyball": "Volleyball",
    "motorsport": "Formula 1",
}
SPORT_ORDER = ["Cricket","Soccer","Tennis","Basketball","Rugby","Formula 1","Esports","Boxing","Badminton","Volleyball","Horse Racing"]

SOFA_URLS = {
    "Soccer": "https://www.sofascore.com/football",
    "Cricket": "https://www.sofascore.com/cricket",
    "Badminton": "https://www.sofascore.com/badminton",
    "Basketball": "https://www.sofascore.com/basketball",
    "Boxing": "https://www.sofascore.com/boxing",
    "Esports": "https://www.sofascore.com/esports",
    "Rugby": "https://www.sofascore.com/rugby",
    "Tennis": "https://www.sofascore.com/tennis",
    "Volleyball": "https://www.sofascore.com/volleyball",
    "Formula 1": "https://www.sofascore.com/motorsport",
}
SKY_URLS = {
    "Soccer": "https://www.skysports.com/football-scores-fixtures",
    "Rugby": "https://www.skysports.com/rugby-union/fixtures",
    "Tennis": "https://www.skysports.com/tennis/scores-schedule",
    "Formula 1": "https://www.skysports.com/f1/schedule",
    "Horse Racing": "https://www.skysports.com/racing",
}
CRICKET_SOURCE = "https://www.espncricinfo.com/"

COUNTRY_CODES = {
    "sri lanka":"LK","india":"IN","pakistan":"PK","bangladesh":"BD","australia":"AU","england":"GB",
    "south africa":"ZA","new zealand":"NZ","west indies":"WI","afghanistan":"AF","ireland":"IE",
    "zimbabwe":"ZW","scotland":"GB","netherlands":"NL","nepal":"NP","oman":"OM","uae":"AE",
    "united arab emirates":"AE","usa":"US","united states":"US","canada":"CA","france":"FR",
    "germany":"DE","spain":"ES","italy":"IT","portugal":"PT","brazil":"BR","argentina":"AR",
    "mexico":"MX","colombia":"CO","chile":"CL","uruguay":"UY","paraguay":"PY","peru":"PE",
    "ecuador":"EC","japan":"JP","south korea":"KR","korea republic":"KR","china":"CN",
    "hong kong":"HK","indonesia":"ID","malaysia":"MY","thailand":"TH","vietnam":"VN",
    "philippines":"PH","singapore":"SG","qatar":"QA","saudi arabia":"SA","iran":"IR",
    "iraq":"IQ","jordan":"JO","egypt":"EG","morocco":"MA","tunisia":"TN","nigeria":"NG",
    "ghana":"GH","kenya":"KE","uganda":"UG","tanzania":"TZ","turkey":"TR","switzerland":"CH",
    "belgium":"BE","netherlands":"NL","austria":"AT","denmark":"DK","sweden":"SE","norway":"NO",
    "finland":"FI","poland":"PL","czech republic":"CZ","czechia":"CZ","croatia":"HR",
    "serbia":"RS","greece":"GR","ukraine":"UA","romania":"RO","bulgaria":"BG","hungary":"HU",
    "slovakia":"SK","slovenia":"SI","iceland":"IS","russia":"RU","belarus":"BY","georgia":"GE",
    "israel":"IL","cyprus":"CY",
}

POPULAR_TEAMS = {
    "india","australia","england","pakistan","sri lanka","south africa","new zealand","bangladesh",
    "real madrid","barcelona","atletico madrid","manchester united","manchester city","liverpool",
    "arsenal","chelsea","tottenham","psg","bayern munich","borussia dortmund","juventus","inter",
    "ac milan","napoli","paris basketball","lakers","warriors","celtics","bulls","knicks",
}

COMPETITION_WEIGHTS = [
    ("world cup", 22), ("champions league", 21), ("europa league", 18), ("conference league", 16),
    ("premier league", 20), ("la liga", 17), ("serie a", 16), ("bundesliga", 16), ("ligue 1", 15),
    ("t20 international", 22), ("test", 16), ("one day international", 20), ("odi", 20),
    ("asia cup", 22), ("ipl", 20), ("big bash", 17), ("icc", 20), ("world championship", 20),
    ("grand slam", 22), ("masters", 18), ("atp", 14), ("wta", 14), ("nba", 19), ("euroleague", 16),
    ("formula 1", 20), ("f1", 20), ("rugby world cup", 22), ("six nations", 19), ("heineken", 16),
    ("uefa", 18), ("ufc", 18), ("boxing", 15), ("cct", 9), ("lck", 14), ("lpl", 14), ("lec", 13),
    ("valorant", 13), ("mobile legends", 11), ("dota", 11), ("counter-strike", 12),
]

def month_dates(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    first = date(y, m, 1)
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return [(first + timedelta(days=i)).isoformat() for i in range((nxt - first).days)]

def get_json(url, timeout=30):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.sofascore.com/",
    }
    clients = []
    if curl_requests:
        clients.append(lambda: curl_requests.get(url, headers=headers, timeout=timeout, impersonate="chrome"))
    clients.append(lambda: requests.get(url, headers=headers, timeout=timeout))
    last = None
    for fn in clients:
        try:
            r = fn()
            r.raise_for_status()
            return r.json()
        except Exception as ex:
            last = ex
    raise last or RuntimeError("request failed")

def get_text(url, timeout=35):
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0 Chrome/154 Safari/537.36"}, timeout=timeout)
    r.raise_for_status()
    return r.text

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def normalize(v):
    return re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).strip()

def iso_from_epoch(value):
    if value in (None, "", 0):
        return ""
    try:
        n = float(value)
        if n > 10_000_000_000:
            n /= 1000
        return datetime.fromtimestamp(n, timezone.utc).astimezone(LOCAL_TZ).isoformat()
    except Exception:
        return ""

def status_name(raw):
    s = raw if isinstance(raw, str) else str((raw or {}).get("type","") or (raw or {}).get("description",""))
    s = s.lower().replace(" ","")
    if any(k in s for k in ["inprogress","live","running","started","playing","halftime"]): return "live"
    if any(k in s for k in ["finished","complete","final","ended"]): return "finished"
    if any(k in s for k in ["cancel","postponed","suspended"]): return "cancelled"
    return "upcoming"

def alpha2_for_name(name):
    n = normalize(name)
    if n in COUNTRY_CODES: return COUNTRY_CODES[n]
    for k, code in COUNTRY_CODES.items():
        if n == normalize(k) or n.endswith(" " + normalize(k)):
            return code
    return ""

def flag(code):
    code = clean(code).upper()
    if len(code) != 2 or not code.isalpha(): return ""
    return "".join(chr(127397 + ord(c)) for c in code)

def participant_meta(obj):
    obj = obj or {}
    country = obj.get("country") or obj.get("nationality") or {}
    code = clean(country.get("alpha2") if isinstance(country, dict) else country)
    name = clean(country.get("name") if isinstance(country, dict) else "")
    team_name = clean(obj.get("name") or obj.get("shortName") or obj.get("displayName"))
    code = code.upper() if len(code) == 2 else alpha2_for_name(name or team_name)
    national = bool(obj.get("national") or obj.get("isNational") or obj.get("nationalTeam"))
    if not national and normalize(team_name) in COUNTRY_CODES:
        national = True
    return {"name": team_name, "country_code": code if national else "", "is_national": national}

def competition_weight(comp):
    n = normalize(comp)
    best = 0
    for key, val in COMPETITION_WEIGHTS:
        if normalize(key) in n:
            best = max(best, val)
    return best

def is_key_name(event):
    n = normalize(event)
    return any(normalize(x) in n for x in POPULAR_TEAMS)

def match_key(sport, p1, p2, day, name):
    a, b = normalize(p1), normalize(p2)
    if a and b:
        return "|".join([sport.lower(), *sorted([a,b]), day])
    return "|".join([sport.lower(), normalize(name), day])

def make_event(sport, competition, event_name, start_time, status, event_type, source, source_url,
               p1="", p2="", p1_meta=None, p2_meta=None, importance=5, time_precision="exact"):
    if not start_time: return None
    p1, p2 = clean(p1), clean(p2)
    competition, event_name = clean(competition) or "Unknown", clean(event_name)
    p1_meta, p2_meta = p1_meta or {}, p2_meta or {}
    day = start_time[:10]
    event_id = match_key(sport, p1, p2, day, event_name)
    international = bool(p1_meta.get("is_national") and p2_meta.get("is_national"))
    if international:
        importance += 3
    return {
        "event_id": event_id,
        "sport": sport,
        "competition": competition,
        "event_name": event_name or (f"{p1} vs {p2}" if p1 and p2 else competition),
        "participant_1": p1 or None,
        "participant_2": p2 or None,
        "participant_1_country_code": p1_meta.get("country_code","") or None,
        "participant_2_country_code": p2_meta.get("country_code","") or None,
        "international": international,
        "start_time": start_time,
        "time_precision": time_precision,
        "status": status,
        "event_type": event_type,
        "source": source,
        "source_url": source_url,
        "importance": round(float(importance), 2),
        "promotion_score": 0,
        "promotion_signal": "Monitor",
        "promotion_reasons": [],
    }

def extract_event_objects(node):
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
    seen, out = set(), []
    for e in found:
        k = str(e.get("id") or id(e))
        if k not in seen:
            seen.add(k); out.append(e)
    return out

def sofascore_events(slug, day):
    urls = [f"{SOFA_BASE}/sport/{slug}/scheduled-events/{day}"]
    if slug == "tennis":
        urls += [
            f"{SOFA_BASE}/sport/tennis/scheduled-tournaments/{day}/page/0",
            f"{SOFA_BASE}/sport/tennis/scheduled-tournaments/{day}/page/1",
        ]
    if slug == "motorsport":
        urls += [f"{SOFA_BASE}/sport/motorsport/scheduled-events/{day}/inverse"]
    out = []
    seen_provider = set()
    for url in urls:
        try:
            body = get_json(url)
        except Exception:
            continue
        for e in extract_event_objects(body):
            provider_id = e.get("id")
            if provider_id and provider_id in seen_provider: continue
            if provider_id: seen_provider.add(provider_id)
            tournament = e.get("tournament") or {}
            unique = tournament.get("uniqueTournament") or {}
            comp = clean(tournament.get("name") or unique.get("name") or "Scheduled")
            season = clean((e.get("season") or {}).get("name"))
            if season and comp == "Scheduled": comp = season

            if slug == "motorsport":
                hay = f"{comp} {clean((e.get('competition') or {}).get('name'))} {clean((e.get('roundInfo') or {}).get('name'))}".lower()
                if "formula 1" not in hay and not re.search(r"\bf1\b", hay):
                    continue

            home = e.get("homeTeam") or e.get("homePlayer") or {}
            away = e.get("awayTeam") or e.get("awayPlayer") or {}
            p1m, p2m = participant_meta(home), participant_meta(away)
            p1, p2 = p1m["name"], p2m["name"]
            start = iso_from_epoch(e.get("startTimestamp") or e.get("startTimeTimestamp") or e.get("startTime"))
            if not start: continue
            if slug == "motorsport":
                label = clean(e.get("name") or comp)
                # Treat an F1 Grand Prix/sprint as the countable event; ignore practice/quali.
                if any(k in label.lower() for k in ["practice", "qualifying"]):
                    continue
                event_type = "race" if "sprint" not in label.lower() else "sprint"
                name = label
            else:
                event_type, name = "match", (f"{p1} vs {p2}" if p1 and p2 else clean(e.get("name")) or comp)

            x = make_event(
                SPORTS[slug], comp, name, start, status_name(e.get("status")), event_type,
                "SofaScore", f"https://www.sofascore.com/event/{e.get('id')}" if e.get("id") else SOFA_URLS[SPORTS[slug]],
                p1, p2, p1m, p2m, 6 if competition_weight(comp) == 0 else 7
            )
            if x:
                x["home_score"] = (e.get("homeScore") or {}).get("display") or (e.get("homeScore") or {}).get("current")
                x["away_score"] = (e.get("awayScore") or {}).get("display") or (e.get("awayScore") or {}).get("current")
                x["sport_detail"] = clean((e.get("category") or {}).get("name") or (e.get("tournament") or {}).get("name"))
                out.append(x)
    return out

def cricinfo_matches(day):
    ddmmyyyy = datetime.strptime(day, "%Y-%m-%d").strftime("%d-%m-%Y")
    url = f"{CRICINFO_BASE}/matches/scheduled?lang=en&filterType=DATE&filterValue={ddmmyyyy}"
    try:
        body = get_json(url)
    except Exception:
        return []
    matches = body.get("matches") if isinstance(body.get("matches"), list) else []
    if not matches:
        for container in [body.get("content"), body.get("data"), body.get("matchList")]:
            if isinstance(container, dict) and isinstance(container.get("matches"), list):
                matches = container["matches"]; break
    out = []
    for m in matches:
        teams = m.get("teams") or []
        meta = []
        for t in teams[:2]:
            team = (t.get("team") if isinstance(t, dict) else {}) or {}
            name = clean(team.get("longName") or team.get("name") or (t.get("name") if isinstance(t, dict) else ""))
            code = alpha2_for_name(name)
            meta.append({"name":name, "country_code":code, "is_national": bool(code)})
        while len(meta) < 2: meta.append({"name":"","country_code":"","is_national":False})
        p1, p2 = meta[0]["name"], meta[1]["name"]
        series = m.get("series") or {}
        comp = clean(series.get("name") or m.get("seriesName") or "Cricket")
        start = iso_from_epoch(m.get("startDate") or m.get("startTime") or m.get("startTimestamp"))
        precision = "exact" if start else "date_only"
        if not start: start = f"{day}T00:00:00+05:30"
        mid = m.get("objectId") or m.get("matchId") or m.get("id") or ""
        url = f"https://www.espncricinfo.com/series/{series.get('slug') or series.get('objectId') or ''}/match/{mid}" if mid else CRICKET_SOURCE
        x = make_event("Cricket", comp, f"{p1} vs {p2}", start, status_name(m.get("status")),
                       "match", "ESPNcricinfo", url, p1, p2, meta[0], meta[1], 9, precision)
        if x: out.append(x)
    return out

FIRECRAWL_SCHEMA = {
    "type":"object",
    "properties":{
        "races":{"type":"array","items":{"type":"object","properties":{
            "date":{"type":"string"},"time":{"type":"string"},"venue":{"type":"string"},
            "race_name":{"type":"string"},"status":{"type":"string"}
        },"required":["time","venue","race_name"]}}
    },"required":["races"]
}

def horse_racing_firecrawl(day):
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key: return []
    url = f"https://www.skysports.com/racing/racecards/{datetime.strptime(day,'%Y-%m-%d').strftime('%d-%m-%Y')}"
    prompt = (
        "Extract every individual horse race shown on this racecards page. One JSON item per race. "
        "Do not return meetings or racecards as a single item. Include the displayed local time, venue, "
        "full race name, and status when available. Preserve race time exactly; do not invent times."
    )
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v2/scrape",
            headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
            json={"url":url,"formats":[{"type":"json","schema":FIRECRAWL_SCHEMA,"prompt":prompt}],"onlyMainContent":True},
            timeout=90,
        )
        r.raise_for_status()
        payload = r.json()
        data = payload.get("data",{}).get("json") or payload.get("json") or {}
        out=[]
        for race in data.get("races",[]):
            tm = clean(race.get("time"))
            venue = clean(race.get("venue"))
            race_name = clean(race.get("race_name"))
            if not tm or not venue or not race_name: continue
            m = re.search(r"(\d{1,2}):(\d{2})", tm)
            if not m: continue
            hh, mm = int(m.group(1)), int(m.group(2))
            # Sky Sports racecards display UK/local venue time. Use a conservative timestamp
            # conversion to an absolute time for the Sri Lankan dashboard.
            dt_local = datetime.strptime(f"{day} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Europe/London"))
            start = dt_local.astimezone(LOCAL_TZ).isoformat()
            status = status_name(race.get("status"))
            out.append(make_event("Horse Racing", venue, f"{venue} — {race_name}", start, status,
                                  "race", "Sky Sports Racing", url, "", "", {}, {}, 5))
        return [x for x in out if x]
    except Exception as ex:
        print("Horse racing Firecrawl failed", day, ex)
        return []

def promotion_score(x):
    sport = x["sport"]
    score = {
        "Cricket":30,"Soccer":24,"Tennis":13,"Basketball":8,"Rugby":7,
        "Formula 1":9,"Esports":6,"Boxing":5,"Badminton":3,"Volleyball":3,"Horse Racing":4
    }.get(sport, 2)
    reasons=[]
    comp_w = competition_weight(x.get("competition",""))
    score += min(22, comp_w)
    if comp_w >= 18: reasons.append("marquee competition")
    if x.get("international"): score += 10; reasons.append("international fixture")
    names = " ".join([x.get("participant_1") or "", x.get("participant_2") or ""]).lower()
    if any(normalize(k) in normalize(names) for k in POPULAR_TEAMS):
        score += 9; reasons.append("high-interest teams")
    if "sri lanka" in names:
        score += 18; reasons.append("Sri Lanka involvement")
    # India/Pakistan/Australia/England cricket and major football clubs matter strongly for SL-facing editorial promotion.
    if sport == "Cricket" and any(k in names for k in ["india","pakistan","australia","england","south africa","new zealand"]):
        score += 7; reasons.append("strong cricket-market relevance")
    try:
        hour = datetime.fromisoformat(x["start_time"]).astimezone(LOCAL_TZ).hour
        if 18 <= hour <= 23:
            score += 7; reasons.append("SL evening slot")
        elif 0 <= hour <= 1:
            score += 4; reasons.append("late SL slot")
    except Exception:
        pass
    x["promotion_score"] = round(min(100, score),1)
    if score >= 65: x["promotion_signal"] = "Promote"
    elif score >= 48: x["promotion_signal"] = "Consider"
    else: x["promotion_signal"] = "Monitor"
    x["promotion_reasons"] = reasons[:4]
    return x

def build_analytics(matches, target_month):
    month_total = len(matches)
    today = datetime.now(LOCAL_TZ).date().isoformat()
    by_sport = {s:0 for s in SPORT_ORDER}
    today_sports = {s:0 for s in SPORT_ORDER}
    daily = {}
    for x in matches:
        by_sport[x["sport"]] = by_sport.get(x["sport"],0) + 1
        day = x["start_time"][:10]
        daily[day] = daily.get(day,0) + 1
        if day == today:
            today_sports[x["sport"]] = today_sports.get(x["sport"],0) + 1
    return {
        "target_month": target_month,
        "today_local": today,
        "month_match_count": month_total,
        "today_match_count": sum(today_sports.values()),
        "sport_month_counts": by_sport,
        "sport_today_counts": today_sports,
        "daily_counts": daily,
        "top_today": sorted([x for x in matches if x["start_time"][:10] == today], key=lambda z:z["promotion_score"], reverse=True)[:12],
    }

def main():
    days = month_dates(TARGET_MONTH)
    out = []
    health = {s: {"provider":"SofaScore","status":"pending","count":0,"error":None} for s in SPORT_ORDER}
    health["Cricket"]["provider"] = "ESPNcricinfo + SofaScore"
    health["Horse Racing"] = {"provider":"Sky Sports Racing + Firecrawl","status":"pending","count":0,"error":None}

    with ThreadPoolExecutor(max_workers=16) as pool:
        future_map = {pool.submit(cricinfo_matches,d):("Cricket","ESPNcricinfo",d) for d in days}
        future_map.update({pool.submit(horse_racing_firecrawl,d):("Horse Racing","Sky Sports Racing",d) for d in days})
        for slug in SPORTS:
            label = SPORTS[slug]
            for d in days:
                future_map[pool.submit(sofascore_events,slug,d)] = (label,"SofaScore",d)

        for f in as_completed(future_map):
            sport, provider, day = future_map[f]
            try:
                rows = f.result()
                out.extend(rows)
                if rows:
                    health[sport]["count"] += len(rows)
                elif health[sport]["status"] == "pending":
                    health[sport]["status"] = "ok"
            except Exception as ex:
                health[sport]["error"] = str(ex)[:200]
                health[sport]["status"] = "warning"
    
    # Each fetched row contributes to coverage; zero-count sports remain visible so gaps are obvious.
    for sport in SPORT_ORDER:
        if health[sport]["count"] > 0:
            health[sport]["status"] = "ok"
        elif health[sport]["error"]:
            health[sport]["status"] = "warning"
        else:
            health[sport]["status"] = "empty"

    # Dedup providers without losing source provenance.
    dedup={}
    priority={"ESPNcricinfo":0,"Sky Sports Racing":1,"SofaScore":2}
    for x in out:
        key=x["event_id"]
        if key not in dedup:
            dedup[key]=x
        else:
            incumbent=dedup[key]
            if priority.get(x["source"],9) < priority.get(incumbent["source"],9):
                dedup[key]=x

    matches=[promotion_score(x) for x in dedup.values()]
    matches=sorted(matches,key=lambda z:z["start_time"])
    if not matches:
        raise RuntimeError("No sports events collected. Check provider availability and FIRECRAWL_API_KEY.")

    payload={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "generated_at_local":datetime.now(LOCAL_TZ).isoformat(),
        "timezone":"Asia/Colombo",
        "timezone_label":"Sri Lanka Time / IST-style UTC+5:30",
        "target_month":TARGET_MONTH,
        "event_count":len(matches),
        "count_definition":"One row = one scheduled match/race. Series/tournaments are never counted as matches.",
        "sports":SPORT_ORDER,
        "provider_health":health,
        "analytics":build_analytics(matches,TARGET_MONTH),
        "matches":matches,
        "sources":{
            "ESPNcricinfo":CRICKET_SOURCE,
            "SofaScore":"https://www.sofascore.com/",
            "Sky Sports Racing":"https://www.skysports.com/racing",
            "Sky Sports schedules":"https://www.skysports.com/",
        },
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Target month:",TARGET_MONTH)
    print("Normalized events:",len(matches))
    print("Today:",payload["analytics"]["today_match_count"])
    for sport in SPORT_ORDER:
        print(sport,payload["analytics"]["sport_month_counts"].get(sport,0))

if __name__ == "__main__":
    main()
