"""Eenmalig: golden_dashboard.yaml vernieuwen vanuit cards.py (v1.5.6).

Behoudt de handmatige opmaak van het bestand; vervangt alleen de 7 kaarten
door de gegenereerde versies, en meldt welke kaarten feitelijk wijzigen.
"""
import importlib.util
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[1]


def _laad_cards():
    # cards.py is moduleschoon (geen HA-imports); directe load om de
    # package-__init__ (die homeassistant vereist) te omzeilen.
    spec = importlib.util.spec_from_file_location(
        "ep_cards", BASE / "custom_components" / "energyprijs" / "cards.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_c = _laad_cards()

PAD = BASE / "tests" / "golden_dashboard.yaml"
NIEUW = [_c.NU_CARD, _c.GRAFIEK_CARD, _c.CONTRACT_CARD, _c.ACCUEENHEDEN_CARD,
         _c.ACCUCONTRACT_CARD, _c.PVCONTRACT_CARD, _c.PVINSTELLINGEN_CARD]

data = yaml.safe_load(PAD.read_text(encoding="utf-8"))
view = data["views"][0]
oud = view["cards"]
assert len(oud) == len(NIEUW), f"verwacht 7 kaarten, schijf heeft er {len(oud)}"

for i, (o, n) in enumerate(zip(oud, NIEUW)):
    if o != n:
        print("WIJZIGT kaart", i, n.get("type"), n.get("title", ""))

view["cards"] = NIEUW
PAD.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                              default_flow_style=False, width=1000),
               encoding="utf-8")
print("golden_dashboard.yaml ververst.")
