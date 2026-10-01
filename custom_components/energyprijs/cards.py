"""Energie-dashboard-kaart builder.

Genereert een complete, kant-en-klare Lovace-kaartconfig (grafiek + contract-
invulvelden) die de gebruiker met één service-aanroep in zijn dashboard kan
plakken — geen handwerk meer via "Add card → Manual YAML".

De kaart is bewust puur core: alleen `custom:apexcharts-card` (via HACS te
installeren) als externe afhankelijkheid; de invulvelden zijn standaard
`entities`-kaarten. Alles leest uit de package-sensoren/helpers, dus het
blijft dynamisch meelopen met contractwijzigingen.
"""
from __future__ import annotations

import json

# ── De twee kaarten, als Python-dicts → deterministisch dumpbaar naar YAML/JSON ──

def _kopreeks(eid: str, naam: str) -> dict:
    """Header-only reeks: toont de actuele sensorwaarde in de kop.

    Let op: apexcharts-card v2.x kent GEEN `data_template` meer (bestond alleen
    in v1.x); een extraneous key geeft "Configuration error". De entiteit zelf
    is al live — `show.in_chart: false` tekent hem alleen niet in de grafiek.
    """
    return {
        "entity": eid,
        "name": naam,
        "float_precision": 3,
        "show": {"in_chart": False},
    }


GRAFIEK_CARD = {
    "type": "custom:apexcharts-card",
    "section_mode": True,
    "experimental": {"color_threshold": True},
    "graph_span": "24h",
    "span": {"start": "day"},
    "update_interval": "5min",
    "show": {"last_updated": True},
    "now": {"show": True, "label": "nu"},
    "header": {
        "show": True,
        "title": "Stroomprijs — bruto · inkoop · verkoop (EUR/kWh)",
        "show_states": True,
        "colorize_states": True,
    },
    "series": [
        _kopreeks("sensor.stroomprijs_basis", "bruto nu"),
        _kopreeks("sensor.stroomprijs_afname", "inkoopprijs"),
        _kopreeks("sensor.stroomprijs_levering", "verkoopprijs"),
        {
            "entity": "sensor.stroomprijs_daglijst",
            "name": "bruto",
            "type": "column",
            "data_generator": (
                "return entity.attributes.vandaag.map((e) => "
                "[new Date(e.t).getTime() + 450000, e.p]);"
            ),
            "float_precision": 3,
            "color_threshold": [
                {"value": 0, "color": "#0a8f3c"},
                {"value": 0.1, "color": "#2fbf5f"},
                {"value": 0.25, "color": "#e6b800"},
                {"value": 0.4, "color": "#d94040"},
            ],
            "show": {"in_header": False},
        },
    ],
    "apex_config": {
        "xaxis": {
            # as loopt een halve kolom (7,5 min) buiten de dag → eerste/laatste staaf volledig
            "min": "EVAL:new Date(new Date().setHours(0,0,0,0)).getTime() - 450000",
            "max": "EVAL:new Date(new Date().setHours(23,59,59,999)).getTime() + 450000",
        },
    },
    "yaxis": [{"decimals": 3, "min": 0, "max": "|+0.04|"}],
}

CONTRACT_CARD = {
    "type": "entities",
    "title": "Stroomprijs — contractinstellingen",
    "show_header_toggle": False,
    "state_color": True,
    "entities": [
        {"entity": "input_number.prijs_btw", "name": "Btw (factor, NL = 0,21)"},
        {"entity": "input_number.prijs_energiebelasting",
         "name": "Energiebelasting excl. btw (€/kWh)"},
        {"entity": "input_number.prijs_opslag_afname",
         "name": "Leveranciersopslag afname (€/kWh)"},
        {"entity": "input_number.prijs_opslag_levering",
         "name": "Leveranciersopslag levering (€/kWh)"},
        {"entity": "input_boolean.prijs_saldering_energiebelasting_teruggave",
         "name": "Saldering (teruggave belasting)"},
    ],
}


def _yaml_item(obj, item_pad: str = "") -> str:
    """Render een dict als één blok-YAML-lijstitem op top-niveau.

    Eerste regel: "<item_pad>- key: value"; overige sleutels op kolom
    "<item_pad>  " (2 spaties binnen het item) — exact de nested-mapping-notatie
    die een "cards:"-lijst in een dashboard vereist.
    """
    assert isinstance(obj, dict)
    key_pad = item_pad + "  "
    out = []
    first = True
    for k, v in obj.items():
        prefix = (item_pad + "- ") if first else key_pad
        first = False
        if isinstance(v, (dict, list)):
            out.append(f"{prefix}{k}:")
            out.append(_yaml_dump(v, len(item_pad) // 2 + 2))
        else:
            out.append(f"{prefix}{k}: {_scalar(v)}")
    return "\n".join(out)


def _yaml_dump(obj, indent: int = 0) -> str:
    """Mini-YAML dumper voor dicts/lists/scalars (geen PyYAML-randgeval nodig).

    Snaarwaarden worden gekotociteerd wanneer ze speciale karakters bevatten
    (:, {}, [] of leading/trailing spaties), anders kaal — zodat HA's parser
    alles netjes leest en de gebruiker het onmiddellijk begrijpt.
    """
    pad = "  " * indent
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            key = f"{k}:"
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{key}")
                out.append(_yaml_dump(v, indent + 1))
            else:
                out.append(f"{pad}{key} {_scalar(v)}")
        return "\n".join(out)
    if isinstance(obj, list):
        out = []
        for item in obj:
            if isinstance(item, dict):
                body = _yaml_dump(item, indent + 1)
                first, _, rest = body.partition("\n")
                head = first.lstrip()
                out.append(f"{pad}- {head}")
                if rest:
                    out.append(rest)
            else:
                out.append(f"{pad}- {_scalar(item)}")
        return "\n".join(out)
    return _scalar(obj)


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if (any(c in s for c in ":{}[]&*?|>!%@`,#")
            or s != s.strip() or not s
            or s.startswith("- ")):
        return json.dumps(s, ensure_ascii=False)
    return s


def build_cards_yaml() -> tuple[str, str]:
    """Geef (grafiek_yaml, contract_yaml)."""
    grafiek = _yaml_dump(GRAFIEK_CARD)
    contract = _yaml_dump(CONTRACT_CARD)
    return grafiek, contract
