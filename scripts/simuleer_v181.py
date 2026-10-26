"""Simulatie-generiek voor de energyprijs v1.8.1 templates (geen HA nodig).

Render de 'vandaag'- en 'morgen'-templates uit package.yaml met synthetische
prijzenseries, in drie scenario's: overdag, 's nachts, en zonder enige prijs.
Verifieert: rollend minimum = laagste all-in over vandaag + eerste 6u morgen;
statusverdeling laden/comfort/ontladen; geen crashes bij lege lijsten.

Gebruik: python3 scripts/simuleer_v181.py   (uitvoeren vanaf repo-root)
"""
import datetime as dt
import re
import sys
from collections import Counter

import yaml
from jinja2 import Environment

P = "custom_components/energyprijs/package.yaml"
TZ = dt.timezone(dt.timedelta(hours=2))


def find(o):
    if isinstance(o, dict):
        if "vandaag" in o and "morgen" in o:
            return o
        for v in o.values():
            r = find(v)
            if r:
                return r
    elif isinstance(o, list):
        for x in o:
            r = find(x)
            if r:
                return r


def quarters(base, hlo, hhi, lo, hi):
    out = []
    for h in range(24):
        for m in (0, 15, 30, 45):
            pr = lo(h) if hlo <= h < hhi else hi(h)
            out.append({"time": (base + dt.timedelta(hours=h, minutes=m)).isoformat(),
                        "price": round(pr, 5)})
    return out


def make_env(now, prices_today=None, prices_tomorrow=None, fractie="1.25"):
    env = Environment()
    def as_datetime(v):
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")) if isinstance(v, str) else v
    env.filters["as_datetime"] = as_datetime
    env.filters["regex_findall"] = lambda s, p: re.findall(p, s)
    BRON = "sensor.prijzen_bron_enerprice"
    tomorrow = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    pt = prices_today if prices_today is not None else quarters(
        now, 2, 8, lambda h: -0.05 + (h % 6) * 0.01, lambda h: 0.30 + (h % 4) * 0.02)
    tm = prices_tomorrow if prices_tomorrow is not None else quarters(
        tomorrow, 1, 7, lambda h: -0.08 + (h % 3) * 0.01, lambda h: 0.28 + (h % 3) * 0.01)
    attrs = {BRON: {"prices_today": pt, "prices_tomorrow": tm},
             "sensor.prijzen_bron_nordpool": {"prices_today": [], "prices_tomorrow": []},
             "sensor.prijzen_bron_energyzero": {"prices_today": [], "prices_tomorrow": []},
             "sensor.prijzen_bron_voorspelling": {"prices_tomorrow": tm[:24]}}
    inputs = {"input_number.prijs_opslag_tijdsafhankelijk": "0",
              "input_number.prijs_dal_uren": "7", "input_number.prijs_top_uren": "17",
              "input_text.prijs_net_blokken": "",
              "input_number.rendement_roundtrip_pct": "70",
              "input_number.prijs_laad_fractie": fractie}
    env.globals.update(states=lambda e, d=None: inputs.get(e, ""),
                       state_attr=lambda e, k: attrs.get(e, {}).get(k, []),
                       now=lambda: now, timedelta=dt.timedelta)
    return env


PAT = re.compile(r"'in':\s*(-?[0-9.]+)[^}]*?'s':\s*'([a-z]+)'")


def report(env, sens, name):
    out = env.from_string(sens[name]).render()
    pairs = [(float(m.group(1)), m.group(2)) for m in PAT.finditer(out)]
    lad = [i for i, s in pairs if s == "laden"]
    comf = [i for i, s in pairs if s == "comfort"]
    ont = [i for i, s in pairs if s == "ontladen"]
    line = f"{name}: {len(pairs)} intervallen — laden={len(lad)} comfort={len(comf)} ontladen={len(ont)}"
    if lad:
        line += f"; max laden={max(lad):.4f}"
    elif comf:
        line += f"; comfort={min(comf):.4f}..{max(comf):.4f}"
    return line, pairs


def main():
    d = yaml.safe_load(open(P))
    sens = find(d["template"])
    fails = 0

    # 1) overdag: vandaag heeft eigen laag blok → moet laden bevatten
    now = dt.datetime(2026, 10, 26, 10, 0, tzinfo=TZ)
    env = make_env(now)
    line, pairs = report(env, sens, "vandaag")
    print("[overdag]", line)
    if not any(s == "laden" for _, s in pairs):
        print("  FAIL: verwachte 'laden' in het goedkope vandaag-blok"); fails += 1
    else:
        # het allergoedkoopste vandaag-interval MOET laden zijn
        goedkoopste = min(pairs)[0]
        status_goedkoopste = [s for i, s in pairs if i == goedkoopste][0]
        if status_goedkoopste != "laden":
            print(f"  FAIL: goedkoopste vandaag-interval ({goedkoopste:.4f}) is '{status_goedkoopste}', niet 'laden'"); fails += 1

    # 2) nacht-scenario: vandaag alleen dure uren, morgen laagsblok binnen 6u
    #    → VOORLOOP moet laden halen (dit was de originele klacht van Jan)
    night = dt.datetime(2026, 10, 26, 0, 30, tzinfo=TZ)
    tomorrow0 = (night + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    env = make_env(night,
                   prices_today=quarters(night, 99, 99, lambda h: 0.5, lambda h: 0.40 + (h % 4) * 0.02),
                   prices_tomorrow=quarters(tomorrow0, 1, 7, lambda h: -0.08 + (h % 3) * 0.01,
                                            lambda h: 0.28 + (h % 3) * 0.01))
    line, pairs = report(env, sens, "vandaag")
    print("[nacht+laag-morgen-blok]", line)
    if any(s == "laden" for _, s in pairs):
        print("  FAIL: vandaag toont 'laden' terwijl alle vandaag-uren duurder zijn dan het morgen-blok"); fails += 1
    # VOORLOOP-controle: dump ns_mn.tm/drem via debug-render en verifieer dat
    # tm < wm (morgen-blok is lager) en dat drem rond tm*fractie/marge ligt.
    dbg = sens["vandaag"].replace("{{ ns2.fin }}", "WM={{ ns_mn.wm }}|TM={{ ns_mn.tm }}|DREM={{ drem }}")
    m = re.search(r"WM=(-?[\d.]+)\|TM=(-?[\d.]+)\|DREM=(-?[\d.]+)", env.from_string(dbg).render())
    wm, tm_, drem = float(m.group(1)), float(m.group(2)), float(m.group(3))
    print(f"   rollend minimum: wm={wm:.4f} tm={tm_:.4f} drem={drem:.4f}")
    if not (tm_ < wm):
        print("  FAIL: VOORLOOP-min (tm) wordt niet gevonden — ochtendblok blijft buiten beschouwing"); fails += 1
    if not (drem < wm - 0.0001):
        print("  FAIL: drempel ligt niet onder het vandaag-minimum → VOORLOOP heeft geen effect"); fails += 1

    # 3) morgen-sjabloon rendert en gebruikt hetzelfde rollende minimum
    line, pairs = report(env, sens, "morgen")
    print("[morgen]", line)
    if not pairs:
        print("  FAIL: morgen renderde geen intervallen"); fails += 1

    # 4) lege prijzenseries → geen crash, alles ontladen (drem=-1)
    env = make_env(now, prices_today=[], prices_tomorrow=[])
    for name in ("vandaag", "morgen"):
        try:
            line, pairs = report(env, sens, name)
            cnt = Counter(s for _, s in pairs)
            ok = set(cnt) <= {"ontladen"} or not pairs
            print(f"[leeg {name}]", line, "→ OK" if ok else "→ FAIL (laden/comfort bij lege data!)")
            if not ok:
                fails += 1
        except Exception as e:
            print(f"[leeg {name}] CRASH: {type(e).__name__}: {e}"); fails += 1

    print("RESULTAAT:", "ALLE SIMULATIES OK" if fails == 0 else f"{fails} FAIL(S)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
