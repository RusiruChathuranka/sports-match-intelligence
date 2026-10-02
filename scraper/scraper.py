import json, os, re
from datetime import datetime, timezone
from pathlib import Path
import requests

API="https://api.firecrawl.dev/v2/scrape"
OUT=Path("data/matches.json")
SOURCES=[{"name":"ESPN India","url":"https://www.espn.in/"},{"name":"Sky Sports","url":"https://www.skysports.com/"},{"name":"ESPNcricinfo","url":"https://www.cricinfo.com/"},{"name":"Premier League","url":"https://www.premierleague.com/en/"},{"name":"China Open","url":"https://www.chinaopen.com/en/"}]
PROMPT="Extract upcoming and live events for cricket, badminton, tennis, football, boxing, rugby, F1, golf, table tennis and basketball. Include matches, live matches, F1 qualifying and races. Ignore generic news. Return one object per event. Use ISO 8601 for start_time where possible. Do not invent dates, times, teams or players."
SCHEMA={"type":"object","properties":{"events":{"type":"array","items":{"type":"object","properties":{"sport":{"type":"string"},"competition":{"type":"string"},"event_name":{"type":"string"},"participant_1":{"type":["string","null"]},"participant_2":{"type":["string","null"]},"start_time":{"type":"string"},"status":{"type":"string"},"event_type":{"type":"string"},"source_url":{"type":"string"},"importance":{"type":"number"}},"required":["sport","competition","event_name","start_time","status","event_type"]}}},"required":["events"]}

def scrape(src):
    r=requests.post(API,headers={"Authorization":"Bearer "+os.environ["FIRECRAWL_API_KEY"],"Content-Type":"application/json"},json={"url":src["url"],"onlyMainContent":False,"waitFor":1500,"maxAge":0,"timeout":90000,"formats":[{"type":"json","prompt":PROMPT,"schema":SCHEMA}]},timeout=120)
    r.raise_for_status()
    return r.json().get("data",{}).get("json",{}).get("events",[])

def clean(e,src):
    sport=str(e.get("sport","")).strip().lower()
    sm={"f1":"F1","table tennis":"Table Tennis","football":"Football","cricket":"Cricket","badminton":"Badminton","tennis":"Tennis","boxing":"Boxing","rugby":"Rugby","golf":"Golf","basketball":"Basketball"}
    sport=sm.get(sport,sport.title())
    start=str(e.get("start_time","")).strip()
    if not start: return None
    p1=(e.get("participant_1") or "").strip(); p2=(e.get("participant_2") or "").strip()
    comp=str(e.get("competition","")).strip() or "Unknown"
    key="|".join([sport.lower(),comp.lower(),re.sub(r"\W+"," ",p1.lower()),re.sub(r"\W+"," ",p2.lower()),start[:10]])
    return {"event_id":key,"sport":sport,"competition":comp,"event_name":str(e.get("event_name","")).strip() or "Event","participant_1":p1 or None,"participant_2":p2 or None,"start_time":start,"status":str(e.get("status","upcoming")).lower(),"event_type":str(e.get("event_type","match")).lower(),"source":src["name"],"source_url":str(e.get("source_url") or src["url"]),"importance":float(e.get("importance") or 5)}

def main():
    if not os.getenv("FIRECRAWL_API_KEY"): raise SystemExit("FIRECRAWL_API_KEY is not set")
    out=[]
    for src in SOURCES:
        try:
            events=scrape(src); print(src['name'],len(events))
            for e in events:
                x=clean(e,src)
                if x: out.append(x)
        except Exception as ex: print(src['name'],'FAILED',ex)
    dedup={x["event_id"]:x for x in out}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"matches":sorted(dedup.values(),key=lambda x:x["start_time"])},ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__": main()