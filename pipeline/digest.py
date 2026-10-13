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

STORY = re.compile(r'<a [^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a [^>]*href=|$)', re.S)

def newsletter_items(e, s, age):
    """Split a newsletter issue (like TLDR) into its individual stories."""
    body = (e.get("content") or [{}])[0].get("value") or e.get("summary") or ""
    out = []
    for url, title, rest in STORY.findall(body):
        t = clean(title, 200)
        m = re.search(r"\((\d+ minute read|GitHub Repo|Website)\)\s*$", t, re.I)
        if m and "sponsor" not in t.lower():
            out.append(dict(title=t[:m.start()].strip(), url=url, source=s["name"], track=s["track"],
                            weight=s.get("weight", 1.0), age=age, text=clean(rest, 700)))
    return out

def card_text(md):
    md = re.sub(r"^---.*?---", "", md, count=1, flags=re.S)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    return clean(" ".join(l for l in md.splitlines() if l.count("|") < 3), 1500)

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
                if s.get("newsletter"):
                    got = newsletter_items(e, s, age)
                    if got:
                        items += got
                        n += len(got)
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
        models = hf_get("/api/models", sort="trendingScore", limit=CFG["counts"]["models"] * 2).json()
    except Exception as ex:
        print("FAIL HF models:", ex)
        return []
    out = []
    for m in models:
        mid = m["id"]
        try:
            card = hf_get(f"/{mid}/raw/main/README.md").text
            card = card_text(card)
        except Exception:
            card = ""
        out.append(dict(title=mid, url=f"https://huggingface.co/{mid}", source="Hugging Face",
                        text=card or "No model card text available.",
                        meta=dict(model=mid)))
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
            model = model or "gemini-3.5-flash-lite"
            j = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     {"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                     {"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json"}})
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
    "technical": "AI research and engineering news.",
    "business": "AI industry business news: money, investments, deals, strategy, market impact. Keep numbers exact.",
    "models": "Newly trending AI models on Hugging Face: say what the model does and what is new about it.",
}
DEPTH = {"skim", "read", "deep"}

def enrich(items, kind, keep):
    """LLM writes headline, summary, why-it-matters, depth and relevance; the best `keep` items are kept."""
    if not items:
        return []
    for i, it in enumerate(items):
        it["id"] = str(i)
    payload = [{"id": it["id"], "title": it["title"], "text": it["text"][:700]} for it in items]
    prompt = (f"You are the editor of a daily AI briefing for {CFG['reader']}. Topic: {GUIDE[kind]} "
              "Use ONLY the text given and never invent facts. Return a JSON object keyed by item id. Each value has: "
              '"h": a headline of at most 12 words saying what happened (never only a product or model name); '
              '"s": a summary of at most 40 words, straight to the point; '
              '"w": one short sentence on why it matters to the reader; '
              '"d": "skim", "read" or "deep" for how much time the reader should invest; '
              '"r": relevance to the reader, 1 (low) to 5 (high).\nItems:\n' + json.dumps(payload))
    raw, res = llm(prompt), {}
    if raw:
        try:
            res = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip())
        except Exception as ex:
            print("Could not parse LLM output:", ex)

    def rel(it):
        try:
            return float((res.get(it["id"]) or {}).get("r", 3))
        except (TypeError, ValueError):
            return 3.0

    out = []
    for it in sorted(items, key=lambda x: (-rel(x), int(x["id"])))[:keep]:
        r = res.get(it["id"]) or {}
        out.append({"title": r.get("h") or it["title"], "url": it["url"], "source": it["source"],
                    "summary": r.get("s") or it["text"][:220], "why": r.get("w") or "",
                    "depth": r.get("d") if r.get("d") in DEPTH else "",
                    "hours": round(it.get("age", 0)), "covered": it.get("covered", 1), **it.get("meta", {})})
    return out

# ---------- 4. publish ----------
def main():
    DATA.mkdir(parents=True, exist_ok=True)
    items = dedupe(fetch_feeds() + hf_papers())
    c = CFG["counts"]
    day = NOW.strftime("%Y-%m-%d")
    digest = {"date": day, "generated": NOW.isoformat(timespec="minutes"),
              "technical": enrich(pick(items, "technical", c["technical"] + 4), "technical", c["technical"]),
              "business": enrich(pick(items, "business", c["business"] + 4), "business", c["business"]),
              "models": enrich(hf_models(), "models", c["models"])}
    (DATA / f"{day}.json").write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    days = sorted((p.stem for p in DATA.glob("20??-??-??.json")), reverse=True)
    for old in days[CFG["keep_days"]:]:
        (DATA / f"{old}.json").unlink()
    (DATA / "index.json").write_text(json.dumps(days[: CFG["keep_days"]]), encoding="utf-8")
    print(f"done: {len(digest['technical'])} technical, {len(digest['business'])} business, {len(digest['models'])} models")

if __name__ == "__main__":
    main()
