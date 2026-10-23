"""Scarica i CSV di football-data.co.uk e genera data/<campionato>.json per il sito."""
import csv, io, json, datetime, urllib.request
from collections import defaultdict
from pathlib import Path

LEAGUES = {
    "serie-a": ("I1", "Serie A"),
    "premier-league": ("E0", "Premier League"),
    "bundesliga": ("D1", "Bundesliga"),
    "la-liga": ("SP1", "La Liga"),
    "ligue-1": ("F1", "Ligue 1"),
}
OUT = Path(__file__).resolve().parent.parent / "data"


def season_code(today=None):
    t = today or datetime.date.today()
    y = t.year if t.month >= 7 else t.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def fetch(code):
    url = f"https://www.football-data.co.uk/mmz4281/{season_code()}/{code}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "calcio-stats/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def num(row, key):
    v = (row.get(key) or "").strip()
    try:
        return int(float(v))
    except ValueError:
        return None


def parse_date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


_fx = None


def fixtures(code):
    """Partite future da football-data.co.uk/fixtures.csv (se non disponibile, lista vuota)."""
    global _fx
    if _fx is None:
        try:
            req = urllib.request.Request("https://www.football-data.co.uk/fixtures.csv",
                                         headers={"User-Agent": "calcio-stats/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                _fx = list(csv.DictReader(io.StringIO(r.read().decode("utf-8-sig", errors="replace"))))
        except Exception as e:
            print("fixtures.csv non disponibile:", e)
            _fx = []
    out = []
    for row in _fx:
        if (row.get("Div") or "").strip() != code:
            continue
        d = parse_date(row.get("Date") or "")
        if d and d >= datetime.date.today():
            out.append(dict(date=d.isoformat(), time=(row.get("Time") or "").strip(),
                            home=(row.get("HomeTeam") or "").strip(), away=(row.get("AwayTeam") or "").strip(),
                            ref=(row.get("Referee") or "").strip() or None))
    out.sort(key=lambda x: (x["date"], x["time"]))
    return out


def blank():
    return dict(p=0, w=0, d=0, l=0, gf=0, ga=0, ps=0, sf=0, sa=0, tf=0, ta=0,
                cf=0, ca=0, fc=0, fs=0, y=0, r=0)


def add(t, gf, ga, row, side):
    me, op = ("H", "A") if side == "home" else ("A", "H")
    t["p"] += 1
    t["gf"] += gf
    t["ga"] += ga
    t["w"] += gf > ga
    t["d"] += gf == ga
    t["l"] += gf < ga
    vals = [num(row, f"{me}S"), num(row, f"{op}S"), num(row, f"{me}ST"), num(row, f"{op}ST"),
            num(row, f"{me}C"), num(row, f"{op}C"), num(row, f"{me}F"), num(row, f"{op}F"),
            num(row, f"{me}Y"), num(row, f"{me}R")]
    if None in vals:
        return
    t["ps"] += 1
    for k, v in zip(["sf", "sa", "tf", "ta", "cf", "ca", "fc", "fs", "y", "r"], vals):
        t[k] += v


def summarize(t):
    out = dict(p=t["p"], w=t["w"], d=t["d"], l=t["l"], gf=t["gf"], ga=t["ga"],
               pts=t["w"] * 3 + t["d"], ps=t["ps"])
    out["gfm"] = round(t["gf"] / t["p"], 2) if t["p"] else 0
    out["gam"] = round(t["ga"] / t["p"], 2) if t["p"] else 0
    for k in ["sf", "sa", "tf", "ta", "cf", "ca", "fc", "fs", "y", "r"]:
        out[k] = round(t[k] / t["ps"], 2) if t["ps"] else None
    return out


def build(slug, code, name):
    rows = list(csv.DictReader(io.StringIO(fetch(code))))
    teams = defaultdict(lambda: {"tot": blank(), "casa": blank(), "fuori": blank()})
    matches, refs = [], defaultdict(lambda: dict(g=0, f=0, y=0, r=0))
    for row in rows:
        h, a = (row.get("HomeTeam") or "").strip(), (row.get("AwayTeam") or "").strip()
        hg, ag, d = num(row, "FTHG"), num(row, "FTAG"), parse_date(row.get("Date") or "")
        if not h or not a or hg is None or ag is None or d is None:
            continue
        for key, t, gf, ga, side in (("casa", teams[h], hg, ag, "home"), ("fuori", teams[a], ag, hg, "away")):
            add(t[key], gf, ga, row, side)
            add(t["tot"], gf, ga, row, side)
        ref = (row.get("Referee") or "").strip()
        f1, f2, y1, y2, r1, r2 = (num(row, k) for k in ("HF", "AF", "HY", "AY", "HR", "AR"))
        if ref and None not in (f1, f2, y1, y2, r1, r2):
            e = refs[ref]
            e["g"] += 1; e["f"] += f1 + f2; e["y"] += y1 + y2; e["r"] += r1 + r2
        matches.append(dict(date=d.isoformat(), home=h, away=a, hg=hg, ag=ag, ref=ref or None,
                            hs=num(row, "HS"), as_=num(row, "AS"), hst=num(row, "HST"), ast=num(row, "AST"),
                            hc=num(row, "HC"), ac=num(row, "AC"), hf=f1, af=f2, hy=y1, ay=y2, hr=r1, ar=r2))
    matches.sort(key=lambda m: m["date"])
    squadre = {n: {k: summarize(v) for k, v in t.items()} for n, t in teams.items()}
    classifica = sorted(({"squadra": n, **s["tot"]} for n, s in squadre.items()),
                        key=lambda x: (-x["pts"], -(x["gf"] - x["ga"]), -x["gf"]))
    per_giornata = max(1, len(teams) // 2)
    arbitri = sorted(({"arbitro": r, "g": e["g"], "falli": round(e["f"] / e["g"], 2),
                       "gialli": round(e["y"] / e["g"], 2), "rossi": round(e["r"] / e["g"], 2)}
                      for r, e in refs.items()), key=lambda x: -x["gialli"])
    OUT.mkdir(exist_ok=True)
    (OUT / f"{slug}.json").write_text(json.dumps({
        "campionato": name, "stagione": season_code(),
        "aggiornato": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes"),
        "classifica": classifica, "ultima_giornata": matches[-per_giornata:][::-1],
        "prossima_giornata": fixtures(code)[:per_giornata],
        "squadre": squadre, "arbitri": arbitri, "partite": matches,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{name}: {len(matches)} partite")


if __name__ == "__main__":
    for slug, (code, name) in LEAGUES.items():
        try:
            build(slug, code, name)
        except Exception as e:  # un campionato che fallisce non blocca gli altri
            print(f"ERRORE {name}: {e}")
