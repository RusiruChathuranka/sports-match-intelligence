import json, os, re, math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

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

# Flashscore public feed sport IDs. The feed provides match-level rows rather than
# tournament/series totals, which is exactly what the dashboard needs.
FLASHSCORE_SPORTS = {
    1: "Soccer",
    2: "Tennis",
    3: "Basketball",
    8: "Rugby",
    12: "Volleyball",
    13: "Cricket",
    16: "Boxing",
    21: "Badminton",
    31: "Formula 1",
    32: "Formula 1",
    33: "Formula 1",
    35: "Horse Racing",
    36: "Esports",
}
FLASH_HOST = "https://local-global.flashscore.ninja"
FLASH_PROJECT = "2"
FLASH_LOCALE = "en"
FLASH_SIGNATURE = "SW9D1eZo"

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
    "hong kong":"HK","chinese taipei":"TW","taiwan":"TW","indonesia":"ID","malaysia":"MY","thailand":"TH","vietnam":"VN",
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
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().isdigit()):
        code = int(float(raw))
        return {1:"upcoming",2:"live",3:"finished",4:"cancelled"}.get(code, "upcoming")
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
        nk = normalize(k)
        if n == nk or n.endswith(" " + nk) or n.startswith(nk + " "):
            return code
    return ""

def flag(code):
    code = clean(code).upper()
    if len(code) != 2 or not code.isalpha(): return ""
    return "".join(chr(127397 + ord(c)) for c in code)

def participant_meta(obj, fallback_country_code=""):
    obj = obj or {}
    country = obj.get("country") or obj.get("nationality") or {}
    code = clean(country.get("alpha2") if isinstance(country, dict) else country)
    name = clean(country.get("name") if isinstance(country, dict) else "")
    team_name = clean(obj.get("name") or obj.get("shortName") or obj.get("displayName"))
    code = code.upper() if len(code) == 2 else alpha2_for_name(name or team_name)
    if not code and fallback_country_code and len(fallback_country_code) == 2:
        code = fallback_country_code.upper()
    national = bool(obj.get("national") or obj.get("isNational") or obj.get("nationalTeam"))
    if not national and normalize(team_name) in COUNTRY_CODES:
        national = True
    return {"name": team_name, "country_code": code, "is_national": national}


ESPORTS_GAMES = [
    ("league of legends", "League of Legends"),
    ("valorant", "Valorant"),
    ("counter strike", "Counter-Strike"),
    ("counter-strike", "Counter-Strike"),
    ("cs2", "Counter-Strike 2"),
    ("dota 2", "Dota 2"),
    ("dota2", "Dota 2"),
    ("mobile legends", "Mobile Legends"),
    ("pubg", "PUBG"),
    ("free fire", "Free Fire"),
    ("call of duty", "Call of Duty"),
    ("rainbow six", "Rainbow Six"),
    ("overwatch", "Overwatch"),
    ("starcraft", "StarCraft"),
    ("rocket league", "Rocket League"),
]

def esports_game_name(competition, event_name):
    hay = normalize(f"{competition} {event_name}")
    for key, label in ESPORTS_GAMES:
        if normalize(key) in hay:
            return label
    return "Esports"

def flashscore_status(raw):
    try:
        code = int(str(raw or "").split(":")[0])
    except Exception:
        code = 1
    return {1:"upcoming",2:"live",3:"finished",4:"cancelled"}.get(code, "upcoming")

def parse_flashscore_feed(text_body, sport):
    # Flashscore feed blocks are separated by "~", fields by "¬" and key/value
    # pairs by "÷". Tournament metadata is carried forward to subsequent match rows.
    current_comp = "Scheduled"
    rows = []
    for block in (text_body or "").split("~"):
        fields = {}
        for item in block.split("¬"):
            if "÷" not in item:
                continue
            key, value = item.split("÷", 1)
            if key:
                fields[key] = value
        if fields.get("ZA"):
            current_comp = clean(fields.get("ZA"))
        if "AA" not in fields or "AD" not in fields:
            continue

        start = iso_from_epoch(fields.get("AD"))
        if not start:
            continue
        comp = clean(fields.get("ZA") or current_comp or "Scheduled")
        p1 = clean(fields.get("CX") or fields.get("AE"))
        p2 = clean(fields.get("AF"))
        raw_name = clean(fields.get("AN") or fields.get("AC") or comp)
        if p1 and p2:
            event_name = f"{p1} vs {p2}"
        else:
            event_name = raw_name or p1 or p2 or comp

        # Formula 1: count races/sprints only, not practice or qualifying sessions.
        if sport == "Formula 1":
            hay = f"{comp} {event_name}".lower()
            if "formula 1" not in hay and not re.search(r"\bf1\b", hay):
                continue
            if any(k in hay for k in ["practice", "qualifying", "free practice", "fp1", "fp2", "fp3"]):
                continue
            event_type = "sprint" if "sprint" in hay else "race"

        # Horse racing is already represented at race level in this feed.
        elif sport == "Horse Racing":
            event_type = "race"
        else:
            event_type = "match"

        competition_country = alpha2_for_name(clean(fields.get("ZY")))
        p1_code = alpha2_for_name(p1) or competition_country
        p2_code = alpha2_for_name(p2) or competition_country
        p1_meta = {"name": p1, "country_code": p1_code, "is_national": bool(alpha2_for_name(p1))}
        p2_meta = {"name": p2, "country_code": p2_code, "is_national": bool(alpha2_for_name(p2))}
        importance = 7
        if sport == "Cricket":
            importance = 9
        elif sport == "Soccer":
            importance = 8
        elif sport == "Tennis":
            importance = 7

        x = make_event(
            sport, comp, event_name, start, flashscore_status(fields.get("AB")),
            event_type, "Flashscore", f"https://www.flashscore.com/match/{fields.get('AA')}/",
            p1, p2, p1_meta, p2_meta, importance
        )
        if x:
            x["provider_event_id"] = fields.get("AA")
            x["home_score"] = clean(fields.get("AG"))
            x["away_score"] = clean(fields.get("AH"))
            x["sport_detail"] = esports_game_name(comp, event_name) if sport == "Esports" else ""
            x["game"] = (x["sport_detail"] if sport == "Esports" else cricket_format(comp, event_name)) if sport in ("Esports","Cricket") else ""
            if sport == "Cricket":
                x["format"] = x["game"]
            x["tournament_name"] = comp
            x["competition_country_code"] = competition_country or None
            x["is_country_match"] = bool(x.get("international"))
            rows.append(x)
    return rows

def flashscore_events(sport_id, day_offset, target_month):
    sport = FLASHSCORE_SPORTS[sport_id]
    url = f"{FLASH_HOST}/{FLASH_PROJECT}/x/feed/f_{sport_id}_{day_offset}_3_{FLASH_LOCALE}_1"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en",
        "Referer": "https://www.flashscore.com/",
        "Origin": "https://www.flashscore.com",
        "x-fsign": FLASH_SIGNATURE,
    }
    try:
        if curl_requests:
            with curl_requests.Session(impersonate="chrome", headers=headers) as s:
                r = s.get(url, timeout=30)
        else:
            r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        rows = parse_flashscore_feed(r.text, sport)
    except Exception as ex:
        return sport, [], f"{type(ex).__name__}: {ex}"
    rows = [x for x in rows if x["start_time"][:7] == target_month]
    return sport, rows, None

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
        "tournament_name": competition,
        "game": "",
        "event_name": event_name or (f"{p1} vs {p2}" if p1 and p2 else competition),
        "participant_1": p1 or None,
        "participant_2": p2 or None,
        "participant_1_country_code": p1_meta.get("country_code","") or None,
        "participant_2_country_code": p2_meta.get("country_code","") or None,
        "international": international,
        "is_country_match": international,
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
                x["game"] = esports_game_name(comp, name) if SPORTS[slug] == "Esports" else ""
                x["tournament_name"] = comp
                x["is_country_match"] = bool(x.get("international"))
                out.append(x)
    return out

CRICKET_PROMO_COUNTRIES = [
    "Sri Lanka","India","Pakistan","England","Australia","South Africa",
    "New Zealand","Bangladesh","West Indies","Afghanistan"
]

def infer_cricket_tournament(p1, p2, start_time, fmt):
    names = normalize(f"{p1} {p2}")
    day = start_time[:10]
    d = int(day[8:10]) if len(day) >= 10 else 0

    def has(*vals):
        return all(normalize(v) in names for v in vals)

    if has("pakistan","sri lanka") and fmt == "T20" and d in (9,11,13):
        return "Sri Lanka tour of Pakistan 2026"
    if ("pakistan" in names and "england" in names or
        "pakistan" in names and "sri lanka" in names or
        "england" in names and "sri lanka" in names) and fmt == "ODI" and 18 <= d <= 31:
        return "Pakistan ODI Tri-Series 2026"
    if has("india","west indies") and fmt in ("ODI","T20"):
        return "West Indies tour of India 2026"
    if has("south africa","australia") and fmt == "Test":
        return "Australia tour of South Africa 2026"
    if has("new zealand","india") and fmt == "T20":
        return "New Zealand tour of India 2026-27"
    if has("namibia","ireland") and fmt == "ODI":
        return "Ireland tour of Namibia 2026"
    if has("afghanistan","zimbabwe") and fmt == "T20":
        return "Afghanistan tour of Zimbabwe 2026"
    if has("bangladesh","west indies") and fmt == "Test":
        return "West Indies tour of Bangladesh 2026"
    return ""

def cricket_format(competition, event_name="", raw=None):
    hay = normalize(f"{competition} {event_name} {raw or ''}")
    if "test" in hay or "first class" in hay or "four day" in hay:
        return "Test"
    if "odi" in hay or "one day" in hay or "one-day" in hay or "50 over" in hay:
        return "ODI"
    if "t20" in hay or "twenty20" in hay or "twenty 20" in hay or "t20i" in hay:
        return "T20"
    return ""

def preferred_cricket_country(name):
    n = normalize(name)
    return any(normalize(c) in n for c in CRICKET_PROMO_COUNTRIES)

def parse_cricschedule_month(month):
    y, m = map(int, month.split("-"))
    month_name = datetime(y, m, 1).strftime("%B").lower()
    url = f"https://www.cricschedule.com/month/{month_name}-{y}.php"
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0 Chrome/154 Safari/537.36"}, timeout=35)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return []

    rows = []
    for tr in soup.select("tr"):
        cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all(["td","th"])]
        if len(cells) < 2:
            continue
        row = " | ".join(cells)
        dm = re.search(r"(Oct\s+\d{1,2},?\s+2026|2026-10-(\d{2}))", row, re.I)
        if not dm:
            continue
        date_text = dm.group(1)
        day_num = int(date_text[-2:]) if date_text.startswith("2026-10-") else int(re.search(r"(\d{1,2})", date_text).group(1))
        day = f"{y:04d}-{m:02d}-{day_num:02d}"

        mm = re.search(r"([A-Za-z][^|,]+?)\s+vs\s+([A-Za-z][^|,]+?)\s*,\s*[^|]*?\b(\d+|Final|Semi[- ]?final|Qualifier)?\s*(T20I?|ODI|Test|T20|Twenty20|One[- ]?Day)\b", row, re.I)
        if not mm:
            continue
        p1, p2 = clean(mm.group(1)), clean(mm.group(2))
        fmt = cricket_format(row, "", mm.group(3))
        if not fmt:
            continue

        tm = re.search(r"(\d{1,2}):(\d{2})\s+GMT", row, re.I)
        if tm:
            hh, mi = int(tm.group(1)), int(tm.group(2))
            start = datetime(y,m,day_num,hh,mi,tzinfo=timezone.utc).astimezone(LOCAL_TZ).isoformat()
        else:
            start = f"{day}T12:00:00+05:30"

        comp = ""
        for a in tr.find_all("a"):
            txt = clean(a.get_text(" ", strip=True))
            if txt and "vs" not in txt.lower() and len(txt) > 6 and any(k in normalize(txt) for k in ["tour","series","tri series","cup","league","world","test"]):
                comp = txt
                break
        if not comp:
            comp = "International Cricket"

        x = make_event(
            "Cricket", comp, f"{p1} vs {p2}", start, "upcoming", "match",
            "CricSchedule", url,
            p1, p2,
            {"name":p1,"country_code":alpha2_for_name(p1),"is_national":preferred_cricket_country(p1)},
            {"name":p2,"country_code":alpha2_for_name(p2),"is_national":preferred_cricket_country(p2)},
            11
        )
        if x:
            x["format"] = fmt
            x["game"] = fmt
            x["tournament_name"] = comp
            x["is_country_match"] = preferred_cricket_country(p1) and preferred_cricket_country(p2)
            rows.append(x)
    return rows

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
                       "match", "ESPNcricinfo", url, p1, p2, meta[0], meta[1], 11, precision)
        if x:
            x["format"] = cricket_format(comp, f"{p1} vs {p2}", m.get("format") or m.get("matchType") or m.get("type"))
            x["game"] = x["format"]
            x["tournament_name"] = comp
            x["is_country_match"] = bool(x.get("international"))
            out.append(x)
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
    # Retained for compatibility with older imports. Horse racing is now collected
    # directly from the Flashscore public feed (sport ID 35).
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
    if score >= 48: x["promotion_signal"] = "Promote"
    elif score >= 34: x["promotion_signal"] = "Consider"
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
        "today_match_count": len([x for x in matches if x.get("status") not in ("finished","cancelled") and x["start_time"][:10] == today]),
        "sport_month_counts": by_sport,
        "sport_today_counts": today_sports,
        "daily_counts": daily,
        "top_today": sorted([x for x in matches if x["start_time"][:10] == today], key=lambda z:z["promotion_score"], reverse=True)[:12],
    }

def main():
    current_day = datetime.now(LOCAL_TZ).date()
    days = month_dates(TARGET_MONTH)
    day_to_date = {i - 7: current_day + timedelta(days=i - 7) for i in range(15)}
    out = []
    health = {s: {"provider":"Flashscore","status":"pending","count":0,"error":None} for s in SPORT_ORDER}
    health["Cricket"]["provider"] = "Flashscore + ESPNcricinfo"

    # Flashscore exposes a rolling -7..+7 day window. We still iterate across the
    # full target month so the inventory expands automatically as each date enters
    # the provider's available window.
    futures_spec = []
    for offset, d in day_to_date.items():
        if d.isoformat()[:7] != TARGET_MONTH:
            continue
        for sport_id in FLASHSCORE_SPORTS:
            futures_spec.append((sport_id, offset))

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(flashscore_events, sport_id, offset, TARGET_MONTH):(sport_id,offset) for sport_id,offset in futures_spec}
        for f in as_completed(futures):
            sport_id, offset = futures[f]
            sport, rows, err = f.result()
            if err:
                health[sport]["error"] = err[:200]
                if health[sport]["status"] == "pending":
                    health[sport]["status"] = "warning"
            else:
                out.extend(rows)
                health[sport]["count"] += len(rows)

    # Keep ESPNcricinfo as a second source for cricket. It often exposes longer
    # international schedules than a rolling daily feed.
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(cricinfo_matches, d): d for d in days}
        for f in as_completed(futures):
            try:
                rows = f.result()
                out.extend(rows)
                health["Cricket"]["count"] += len(rows)
            except Exception as ex:
                health["Cricket"]["error"] = str(ex)[:200]

    # Supplement the rolling feeds with a published current-month international
    # cricket schedule so future series/tournaments are visible before they enter
    # the rolling provider window.
    try:
        out.extend(parse_cricschedule_month(TARGET_MONTH))
    except Exception as ex:
        health["Cricket"]["error"] = str(ex)[:200]

    # De-duplicate cross-provider copies. Prefer ESPNcricinfo for cricket and
    # Flashscore for other sports.
    priority = {"ESPNcricinfo":0, "Flashscore":1, "SofaScore":2}
    dedup = {}
    for x in out:
        key = x["event_id"]
        if key not in dedup or priority.get(x["source"],9) < priority.get(dedup[key]["source"],9):
            dedup[key] = x

    for x in dedup.values():
        if x["sport"] == "Cricket":
            x["format"] = x.get("format") or cricket_format(x.get("tournament_name") or x.get("competition",""), x.get("event_name",""))
            inferred = infer_cricket_tournament(x.get("participant_1") or "", x.get("participant_2") or "", x.get("start_time",""), x["format"])
            if inferred:
                x["tournament_name"] = inferred
                x["competition"] = inferred
            x["game"] = x["format"]
            p1, p2 = x.get("participant_1") or "", x.get("participant_2") or ""
            x["is_country_match"] = preferred_cricket_country(p1) and preferred_cricket_country(p2)
            if not x.get("participant_1_country_code"):
                x["participant_1_country_code"] = alpha2_for_name(p1)
            if not x.get("participant_2_country_code"):
                x["participant_2_country_code"] = alpha2_for_name(p2)
    matches = [promotion_score(x) for x in dedup.values()]
    matches = sorted(matches, key=lambda z:z["start_time"])
    if not matches:
        raise RuntimeError("No sports events collected. Check Flashscore source availability.")

    # Mark sports with no events separately so gaps in the source are visible in the UI.
    for sport in SPORT_ORDER:
        if health[sport]["count"] > 0:
            health[sport]["status"] = "ok"
        elif health[sport]["error"]:
            health[sport]["status"] = "warning"
        else:
            health[sport]["status"] = "empty"

    analytics = build_analytics(matches, TARGET_MONTH)
    today_offset_window_start = max(days[0], (current_day - timedelta(days=7)).isoformat())
    today_offset_window_end = min(days[-1], (current_day + timedelta(days=7)).isoformat())
    analytics["coverage_note"] = (
        f"Flashscore daily feeds currently expose a rolling ~15-day window "
        f"({today_offset_window_start} to {today_offset_window_end}). "
        f"The current-month inventory therefore grows as future dates enter that window."
    )
    analytics["provider_window_start"] = today_offset_window_start
    analytics["provider_window_end"] = today_offset_window_end

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_local": datetime.now(LOCAL_TZ).isoformat(),
        "timezone": "Asia/Colombo",
        "timezone_label": "Sri Lanka Time / IST-style UTC+5:30",
        "target_month": TARGET_MONTH,
        "event_count": len(matches),
        "count_definition": "One row = one scheduled match/race. Series and tournaments are never counted as matches.",
        "sports": SPORT_ORDER,
        "provider_health": health,
        "analytics": analytics,
        "matches": matches,
        "sources": {
            "Flashscore": "https://www.flashscore.com/live-scores/",
            "ESPNcricinfo": CRICKET_SOURCE,
            "Sky Sports Racing": "https://www.skysports.com/racing",
        },
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Target month:", TARGET_MONTH)
    print("Normalized events:", len(matches))
    print("Today:", analytics["today_match_count"])
    for sport in SPORT_ORDER:
        print(sport, analytics["sport_month_counts"].get(sport,0))


if __name__ == "__main__":
    main()
