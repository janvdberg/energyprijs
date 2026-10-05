"""Energie-dashboard-kaart builder.

Genereert een complete, kant-en-klare Lovace-kaartconfig (prijs-tegels +
grafiek + contract-invulvelden) die de integratie zelf in het dashboard zet —
geen handwerk meer via "Add card → Manual YAML".

Sinds v1.2.41 exact de door Jan handmatig aangepaste opbouw (golden file in
tests/test_golden_dashboard.py): de grafiek toont ALLÉÉN de bruto-kolommen
(verkoopprijslijn bewust verwijderd), legenda weg, titel "Stroomprijs".
Wijzig hier alleen als je akkoord bent dat elk geïnstalleerd dashboard bij de
volgende update naar die opbouw wordt herbouwd (opbouw-check, installer.py).

De kaart is bewust puur core: alleen `custom:apexcharts-card` (via HACS te
installeren) als externe afhankelijkheid; de invulvelden zijn standaard
`entities`-kaarten. Alles leest uit de package-sensoren/helpers, dus het
blijft dynamisch meelopen met contractwijzigingen.
"""
from __future__ import annotations

import json

# ── De twee kaarten, als Python-dicts → deterministisch dumpbaar naar YAML/JSON ──

GRAFIEK_CARD = {
    "type": "custom:apexcharts-card",
    "section_mode": True,
    "experimental": {"color_threshold": True, "disable_config_validation": True},
    "graph_span": "24h",
    "span": {"start": "day"},
    "update_interval": "5min",
    "show": {"last_updated": True},
    "now": {"show": True, "label": "nu"},
    "header": {
        "show": True,
        "title": "Stroomprijs",
        "show_states": False,
        "colorize_states": False,
    },
    "series": [
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
        # hele legenda weg: de staafkleuren zijn voldoende (verzoek 4 okt '26)
        "legend": {"show": False},
        "xaxis": {
            # as loopt een halve kolom (7,5 min) buiten de dag → eerste/laatste staaf volledig
            "min": "EVAL:new Date(new Date().setHours(0,0,0,0)).getTime() - 450000",
            "max": "EVAL:new Date(new Date().setHours(23,59,59,999)).getTime() + 450000",
        },
    },
    "yaxis": [
        {"decimals": 3, "min": "|-0.04|", "max": "|+0.04|"},
    ],
}

NU_CARD = {
    "type": "grid",
    "square": False,
    "cards": [
        {"type": "entity",
         "entity": "sensor.stroomprijs_afname",
         "name": "Inkoopprijs",
         "icon": "mdi:arrow-bottom-right",
         "state_color": True},
        {"type": "entity",
         "entity": "sensor.stroomprijs_levering",
         "name": "Verkoopprijs",
         "icon": "mdi:arrow-top-right"},
    ],
    "columns": 2,
}

# ── ACCU-CONTRACT-tegel (v1.2.42): snelkoppeling + drie invulvelden + mee-rekenen.
#    Sensor-namen zijn het package-contract; ontbrekende velden tonen '—' (geen crash).
ACCUEENHEDEN_CARD = {
    "type": "markdown",
    "title": "Accu — contract & snelkoppeling",
    "content": (
        "## 🔋 Accupercentage\n"
        "Bron: `{{ state_attr('sensor.accu_percentage', 'bron') or 'nog niet ingesteld' }}`"
        " — **{{ states('sensor.accu_percentage') }}%**\n"
        "{% set soc = states('sensor.accu_percentage') | float(-1) %}\n"
        "{% set kwh = states('input_number.accu_capaciteit_kwh') | float(0) %}\n"
        "{% set p_in = states('input_number.accu_vermogen_in_kw') | float(0) %}\n"
        "{% set p_uit = states('input_number.accu_vermogen_uit_kw') | float(0) %}\n"
        "{% if soc >= 0 and kwh > 0 %}\n"
        "* In de accu: **{{ (soc / 100 * kwh) | round(2) }} kWh**\n"
        "{% endif %}\n"
        "{% if soc >= 0 and kwh > 0 and p_in > 0 %}\n"
        "* Vol laden vanaf nu: ± **{{ ((100 - soc) / 100 * kwh / p_in) | round(1) }} uur**\n"
        "{% endif %}\n"
        "{% if soc >= 0 and kwh > 0 and p_uit > 0 %}\n"
        "* Leeg ontladen vanaf nu: ± **{{ (soc / 100 * kwh / p_uit) | round(1) }} uur**\n"
        "{% endif %}"
    ),
}

ACCUCONTRACT_CARD = {
    "type": "entities",
    "title": "Accu — contractinstellingen",
    "show_header_toggle": False,
    "state_color": True,
    "entities": [
        {"entity": "input_text.accu_bron_entity",
         "name": "Bron-entity accu-% (leeg = handmatig)"},
        {"entity": "input_number.accu_handmatig_pct",
         "name": "Handmatig percentage (%)"},
        {"entity": "input_number.accu_capaciteit_kwh",
         "name": "Capaciteit (kWh)"},
        {"entity": "input_number.accu_vermogen_in_kw",
         "name": "Laadvermogen max (kW)"},
        {"entity": "input_number.accu_vermogen_uit_kw",
         "name": "Ontlaadvermogen max (kW)"},
    ],
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


def build_cards_yaml() -> tuple[str, str, str, str, str]:
    """Geef (nu_yaml, grafiek_yaml, contract_yaml, accueenheden_yaml, accucontract_yaml)."""
    nu = _yaml_dump(NU_CARD)
    grafiek = _yaml_dump(GRAFIEK_CARD)
    contract = _yaml_dump(CONTRACT_CARD)
    accueenheden = _yaml_dump(ACCUEENHEDEN_CARD)
    accucontract = _yaml_dump(ACCUCONTRACT_CARD)
    return nu, grafiek, contract, accueenheden, accucontract