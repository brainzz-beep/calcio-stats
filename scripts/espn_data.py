"""Dati ESPN: calendario, giornate, marcatori/assist/cartellini con minuto, giocatori, arbitri.
Scrive data/<campionato>-espn.json. Va lanciato DOPO update_data.py (usa i nomi delle squadre di quel file)."""
import json, re, time, urllib.error, calendar, datetime, difflib, unicodedata, urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parent.parent / "data"
LEAGUES = {"serie-a": "ita.1", "premier-league": "eng.1", "bundesliga": "ger.1", "la-liga": "esp.1", "ligue-1": "fra.1"}
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/"
TZ = ZoneInfo("Europe/Rome")
STOP = {"fc", "ac", "as", "afc", "cf", "sc", "ssc", "us", "calcio", "club", "de", "1", "fsv", "sv", "vfb", "vfl", "rc", "ud", "cd"}
ALIAS = {"internazionale": "Inter", "ac milan": "Milan", "hellas verona": "Verona", "manchester united": "Man United",
         "manchester city": "Man City", "nottingham forest": "Nott'm Forest", "atletico madrid": "Ath Madrid",
         "athletic club": "Ath Bilbao", "borussia monchengladbach": "M'gladbach", "paris saint germain": "Paris SG",
         "wolverhampton wanderers": "Wolves", "tottenham hotspur": "Tottenham", "newcastle united": "Newcastle",
         "real sociedad": "Sociedad", "real betis": "Betis", "celta vigo": "Celta", "rayo vallecano": "Vallecano",
         "bayer leverkusen": "Leverkusen", "borussia dortmund": "Dortmund", "eintracht frankfurt": "Ein Frankfurt",
         "fc cologne": "FC Koln", "koln": "FC Koln", "olympique marseille": "Marseille", "olympique lyonnais": "Lyon", "brighton hove albion": "Brighton", "deportivo": "La Coruna",
         "espanyol": "Espanol", "stade rennais": "Rennes"}


def get(url):
    err = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 calcio-stats"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            err = e
            if e.code < 500:  # errore della richiesta: riprovare non serve
                break
            time.sleep(2)
        except Exception as e:
            err = e
            time.sleep(2)
    print("  errore", url, err)
    return None


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def toks(s):
    return {t for t in norm(s).split() if t not in STOP}


def team_map(names, fd_names):
    out = {}
    for n in names:
        if n in fd_names:
            out[n] = n; continue
        al = ALIAS.get(norm(n))
        if al in fd_names:
            out[n] = al; continue
        best, score = None, 0
        for f in fd_names:
            a, b = toks(n), toks(f)
            s = len(a & b) / max(1, len(a | b)) + 0.5 * difflib.SequenceMatcher(None, norm(n), norm(f)).ratio()
            if s > score:
                best, score = f, s
        if score >= 0.7:
            out[n] = best
        else:
            print(f"  ATTENZIONE: squadra ESPN senza corrispondenza: {n}")
            out[n] = n
    return out


def ref_fd(name, fd_refs):
    parts = norm(name).split()
    if not parts:
        return None
    c = [r for r in fd_refs if norm(r).split() and norm(r).split()[-1] == parts[-1]]
    return c[0] if c else None


def ival(st, k):
    try:
        return int(float(st.get(k) or 0))
    except (TypeError, ValueError):
        return 0


def detail(lg, eid, tm):
    s = get(BASE.format(lg=lg) + f"summary?event={eid}")
    if not s:
        return None
    arb, ref = [], None
    for o in (s.get("gameInfo") or {}).get("officials") or []:
        pos = o.get("position") or {}
        nome, ruolo = o.get("fullName") or o.get("displayName"), (pos.get("displayName") or pos.get("name") or "")
        arb.append({"nome": nome, "ruolo": ruolo})
        if ref is None and "referee" in ruolo.lower() and not re.search(r"assistant|fourth|video|var", ruolo.lower()):
            ref = nome
    ev = []
    for e in s.get("keyEvents") or []:
        t = ((e.get("type") or {}).get("text") or "").lower()
        kind = "gol" if ("goal" in t or "penalty - scored" in t) else "giallo" if "yellow" in t else "rosso" if "red" in t else None
        if not kind:
            continue
        ps = [(p.get("athlete") or {}).get("displayName") for p in e.get("participants") or []]
        team = (e.get("team") or {}).get("displayName")
        ev.append({"min": (e.get("clock") or {}).get("displayValue") or "", "tipo": kind, "squadra": tm.get(team, team),
                   "g": ps[0] if ps else None, "a": ps[1] if kind == "gol" and len(ps) > 1 else None,
                   "extra": "autogol" if "own" in t else "rigore" if "penalty" in t else None})
    pl, names = [], set()
    for r in s.get("rosters") or []:
        team = (r.get("team") or {}).get("displayName")
        for p in r.get("roster") or []:
            st = {x.get("name"): x.get("value") for x in p.get("stats") or []}
            names |= set(st)
            if not (p.get("starter") or p.get("subbedIn") or ival(st, "totalShots") or ival(st, "foulsCommitted") or ival(st, "appearances")):
                continue
            pl.append({"n": (p.get("athlete") or {}).get("displayName"), "sq": tm.get(team, team),
                       "sh": ival(st, "totalShots"), "sot": ival(st, "shotsOnTarget"), "g": ival(st, "totalGoals"),
                       "a": ival(st, "goalAssists"), "fc": ival(st, "foulsCommitted"), "fs": ival(st, "foulsSuffered"),
                       "y": ival(st, "yellowCards"), "r": ival(st, "redCards")})
    return {"arbitro_n": ref, "arbitri": arb, "eventi": ev, "pl": pl, "det": True, "_stat": sorted(names)}


def run(slug, lg):
    fdp = DATA / f"{slug}.json"
    if not fdp.exists():
        return
    fd = json.loads(fdp.read_text("utf-8"))
    fd_names, fd_refs = list(fd["squadre"]), [a["arbitro"] for a in fd["arbitri"]]
    outp = DATA / f"{slug}-espn.json"
    old = {}
    if outp.exists():
        old = {m["id"]: m for m in json.loads(outp.read_text("utf-8")).get("partite", [])}
    t = datetime.date.today(); y = t.year if t.month >= 7 else t.year - 1
    season_start = datetime.date(y, 8, 1)
    played = [m["date"] for m in old.values() if m.get("stato") == "post"]
    start = max(season_start, datetime.date.fromisoformat(max(played)) - datetime.timedelta(days=5)) if played else season_start
    end = t + datetime.timedelta(days=10)
    base = BASE.format(lg=lg) + "scoreboard?dates="
    fmt = lambda d: d.strftime("%Y%m%d")
    # prova prima l'intervallo di date; se ESPN lo rifiuta, passa a una richiesta per giorno
    size = 31 if get(base + f"{fmt(start)}-{fmt(min(end, start + datetime.timedelta(days=6)))}") is not None else 1
    events = {}
    d0 = start
    while d0 <= end:
        d1 = min(end, d0 + datetime.timedelta(days=size - 1))
        sb = get(base + (fmt(d0) if size == 1 else f"{fmt(d0)}-{fmt(d1)}"))
        for ev in (sb or {}).get("events", []):
            events[ev["id"]] = ev
        d0 = d1 + datetime.timedelta(days=1)
    raw = []
    for m in old.values():  # partite già salvate e fuori dalla finestra appena scaricata
        if m["id"] not in events:
            raw.append({"id": m["id"], "dt": datetime.datetime.fromisoformat(m["date"] + "T" + m["time"]).replace(tzinfo=TZ),
                        "stato": m.get("stato"), "home": m["home"], "away": m["away"], "hg": m["hg"], "ag": m["ag"]})
    for ev in events.values():
        comp = (ev.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in cs or "away" not in cs:
            continue
        sc = lambda c: int(float((c.get("score") or {}).get("value", 0) if isinstance(c.get("score"), dict) else c.get("score") or 0))
        dtm = datetime.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(TZ)
        raw.append({"id": ev["id"], "dt": dtm, "stato": (ev.get("status") or {}).get("type", {}).get("state"),
                    "home": cs["home"]["team"]["displayName"], "away": cs["away"]["team"]["displayName"],
                    "hg": sc(cs["home"]), "ag": sc(cs["away"])})
    tm = team_map({r["home"] for r in raw} | {r["away"] for r in raw}, fd_names)
    raw.sort(key=lambda r: r["dt"])
    n, matches = {}, []
    for r in raw:
        h, a = tm[r["home"]], tm[r["away"]]
        n[h] = n.get(h, 0) + 1; n[a] = n.get(a, 0) + 1
        matches.append({"id": r["id"], "g": max(n[h], n[a]), "date": r["dt"].date().isoformat(), "time": r["dt"].strftime("%H:%M"),
                        "home": h, "away": a, "hg": r["hg"], "ag": r["ag"], "stato": r["stato"]})
    pre = [m for m in matches if m["stato"] == "pre"]
    next_g = pre[0]["g"] if pre else None
    campione = None
    for m in matches:
        prev = old.get(m["id"])
        need = (m["stato"] == "post" and not (prev and prev.get("det"))) or (m["stato"] == "pre" and m["g"] == next_g)
        if need:
            d = detail(lg, m["id"], tm)
            if d:
                campione = campione or {"stat": d["_stat"], "eventi": d["eventi"][:2]}
                m.update({k: v for k, v in d.items() if k != "_stat"})
                continue
        if prev:
            m.update({k: prev[k] for k in ("arbitro_n", "arbitri", "eventi", "pl", "det") if k in prev})
    for m in matches:
        if m.get("arbitro_n"):
            m["ref"] = ref_fd(m["arbitro_n"], fd_refs)
    agg = {}
    for m in matches:
        if m["stato"] != "post":
            continue
        for p in m.get("pl", []):
            a = agg.setdefault((p["n"], p["sq"]), {"n": p["n"], "sq": p["sq"], "p": 0, "sh": 0, "sot": 0, "g": 0, "a": 0, "fc": 0, "fs": 0, "y": 0, "r": 0})
            a["p"] += 1
            for k in ("sh", "sot", "g", "a", "fc", "fs", "y", "r"):
                a[k] += p[k]
    prossima = [{"date": m["date"], "time": m["time"], "home": m["home"], "away": m["away"], "ref": m.get("ref")}
                for m in pre if m["g"] == next_g]
    out = {"aggiornato": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
           "partite": [m for m in matches], "prossima": prossima, "giocatori": list(agg.values()), "campione": campione}
    outp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{slug}: {len(matches)} partite ESPN, {len(agg)} giocatori, prossima giornata: {len(prossima)} partite")


if __name__ == "__main__":
    for slug, lg in LEAGUES.items():
        try:
            run(slug, lg)
        except Exception as e:
            print(f"ERRORE {slug}: {e}")
