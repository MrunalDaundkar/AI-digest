#!/usr/bin/env python3
"""Daily AI digest: fetch -> dedupe -> rank -> summarize -> docs/data/*.json"""
import os, re, json, html, time, difflib, datetime as dt
from pathlib import Path
import requests, feedparser, yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
NOW = dt.datetime.now(dt.timezone.utc)
HDR = {"User-Agent": "ai-digest/1.0 (personal news digest)"}

def clean(t, n=600):
    t = re.sub(r"<[^>]+>", " ", html.unescape(t or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]

# ---------- 1. collect ----------
def fetch_feeds():
    items = []
    for s in CFG["sources"]:
        try:
            r = requests.get(s["url"], headers=HDR, timeout=20)
            r.raise_for_status()
            n = 0
            for e in feedparser.parse(r.content).entries[: s.get("max", 25)]:
                ts = e.get("published_parsed") or e.get("updated_parsed")
                when = dt.datetime(*ts[:6], tzinfo=dt.timezone.utc) if ts else NOW
                age = (NOW - when).total_seconds() / 3600
                if age > CFG["max_age_hours"] or not e.get("link"):
                    continue
                items.append(dict(title=clean(e.get("title"), 200), url=e["link"], source=s["name"],
                                  track=s["track"], weight=s.get("weight", 1.0), age=max(age, 0),
                                  text=clean(e.get("summary") or e.get("description"), 700)))
                n += 1
            print(f"ok   {s['name']}: {n} recent items")
        except Exception as ex:
            print(f"FAIL {s['name']}: {ex}")
    return items

def hf_get(path, **params):
    h = dict(HDR)
    if os.getenv("HF_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["HF_TOKEN"]
    r = requests.get("https://huggingface.co" + path, params=params, headers=h, timeout=20)
    r.raise_for_status()
    return r

def hf_papers():
    try:
        out = []
        for p in hf_get("/api/daily_papers", limit=12).json():
            pp = p.get("paper", {})
            out.append(dict(title=clean(pp.get("title"), 200), url=f"https://huggingface.co/papers/{pp.get('id')}",
                            source="HF Daily Papers", track="technical", weight=1.4, age=12,
                            text=clean(pp.get("summary"), 700)))
        print(f"ok   HF Daily Papers: {len(out)}")
        return out
    except Exception as ex:
        print("FAIL HF Daily Papers:", ex)
        return []

def hf_models():
    try:
        models = hf_get("/api/models", sort="trendingScore", limit=CFG["counts"]["models"]).json()
    except Exception as ex:
        print("FAIL HF models:", ex)
        return []
    out = []
    for m in models:
        mid = m["id"]
        try:
            card = hf_get(f"/{mid}/raw/main/README.md").text
            card = re.sub(r"^---.*?---", "", card, count=1, flags=re.S)
        except Exception:
            card = ""
        out.append(dict(title=mid, url=f"https://huggingface.co/{mid}", source="Hugging Face",
                        text=clean(card, 1500) or "No model card text available.",
                        meta=dict(task=m.get("pipeline_tag") or "unspecified", likes=m.get("likes", 0),
                                  downloads=m.get("downloads", 0))))
    print(f"ok   HF trending models: {len(out)}")
    return out

# ---------- 2. dedupe and rank (no LLM) ----------
def score(it):
    hay = (it["title"] + " " + it["text"]).lower()
    hits = sum(k in hay for k in CFG["keywords"][it["track"]])
    fresh = max(0, 1 - it["age"] / CFG["max_age_hours"])
    return it["weight"] * 2 + fresh * 2 + min(hits, 4) + 1.5 * (it.get("covered", 1) - 1)

def dedupe(items):
    kept, seen = [], set()
    for it in sorted(items, key=score, reverse=True):
        key = it["url"].split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        dup = next((k for k in kept if k["track"] == it["track"] and difflib.SequenceMatcher(
            None, k["title"].lower(), it["title"].lower()).ratio() > 0.75), None)
        if dup:
            dup["covered"] = dup.get("covered", 1) + 1  # same story in several places = more important
        else:
            kept.append(it)
    return kept

def pick(items, track, n):
    out, per = [], {}
    for it in sorted((i for i in items if i["track"] == track), key=score, reverse=True):
        if per.get(it["source"], 0) >= CFG["max_per_source"]:
            continue
        per[it["source"]] = per.get(it["source"], 0) + 1
        out.append(it)
        if len(out) == n:
            break
    return out

# ---------- 3. LLM (swappable: gemini | claude | none) ----------
def post(url, headers, body):
    for attempt in range(3):
        r = requests.post(url, headers=headers, json=body, timeout=120)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited")

def llm(prompt):
    p = (os.getenv("LLM_PROVIDER") or "gemini").lower()
    model = os.getenv("LLM_MODEL") or None
    try:
        if p == "gemini":
            model = model or "gemini-2.5-flash-lite"
            j = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     {"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                     {"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}})
            return j["candidates"][0]["content"]["parts"][0]["text"]
        if p == "claude":
            j = post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                     {"model": model or "claude-haiku-5-5", "max_tokens": 4000,
                      "messages": [{"role": "user", "content": prompt}]})
            return j["content"][0]["text"]
    except Exception as ex:
        print("LLM failed, using plain snippets:", ex)
    return None

GUIDE = {
    "technical": "AI research and engineering news. Say what is new and why an engineer should care.",
    "business": "AI industry business news. Focus on money, investments, deals, strategy and market impact. Keep numbers exact.",
    "models": "Trending Hugging Face models. Explain what the model does, what is different about it, its size or architecture if stated, and typical uses.",
}

def summarize(items, kind):
    if not items:
        return []
    for i, it in enumerate(items):
        it["id"] = str(i)
    payload = [{"id": it["id"], "title": it["title"], "text": it["text"][:700]} for it in items]
    prompt = (f"You write a daily AI briefing for a reader with an AI and computer vision background. "
              f"Topic: {GUIDE[kind]} Use ONLY the text given and never invent facts. "
              f'Return a JSON object keyed by item id; each value is {{"s": one or two plain sentences, '
              f'"m": two or three sentences of extra detail}}.\nItems:\n{json.dumps(payload)}')
    raw, res = llm(prompt), {}
    if raw:
        try:
            res = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
        except Exception as ex:
            print("Could not parse LLM output:", ex)
    return [{"title": it["title"], "url": it["url"], "source": it["source"],
             "summary": (res.get(it["id"]) or {}).get("s") or it["text"][:220],
             "more": (res.get(it["id"]) or {}).get("m") or it["text"], "hours": round(it.get("age", 0)), "covered": it.get("covered", 1), **it.get("meta", {})} for it in items]

# ---------- 4. publish ----------
def main():
    DATA.mkdir(parents=True, exist_ok=True)
    items = dedupe(fetch_feeds() + hf_papers())
    c = CFG["counts"]
    day = NOW.strftime("%Y-%m-%d")
    digest = {"date": day, "generated": NOW.isoformat(timespec="minutes"),
              "technical": summarize(pick(items, "technical", c["technical"]), "technical"),
              "business": summarize(pick(items, "business", c["business"]), "business"),
              "models": summarize(hf_models(), "models")}
    (DATA / f"{day}.json").write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    days = sorted((p.stem for p in DATA.glob("20??-??-??.json")), reverse=True)
    for old in days[CFG["keep_days"]:]:
        (DATA / f"{old}.json").unlink()
    (DATA / "index.json").write_text(json.dumps(days[: CFG["keep_days"]]), encoding="utf-8")
    print(f"done: {len(digest['technical'])} technical, {len(digest['business'])} business, {len(digest['models'])} models")

if __name__ == "__main__":
    main()
