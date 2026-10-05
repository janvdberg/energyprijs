"""Review-fixes v1.2.42: dubbele YAML-sleutels + kaarten/package-contract.

Waarom deze tests bestaan (review 5 okt '26): een tweede top-level `input_number:`
in package.yaml werd door de gewone PyYAML-loader stil doorlaten (laatste wint),
waardoor zes prijshelpers in het geparsede package verdwenen — op het dashboard
lege contractvelden en verkeerde all-in prijzen. Deze tests maken die klasse
fouten onmogelijk:
  1. strikte loader: elke dubbele mapping-sleutel (top-level én genest) faalt;
  2. alle verwachte helpers/sensoren moeten in het GEPARSTE package staan;
  3. elke entiteit waarnaar cards.py verwijst, moet door het package gedefinieerd
     zijn (of expliciet extern: bron-sensoren van integraties);
  4. accu_handmatig_pct mag nergens meer voorkomen (verwijderd in de review).
"""
import re
from pathlib import Path

import yaml

PKG_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "energyprijs" / "package.yaml"


class StrictLoader(yaml.SafeLoader):
    """SafeLoader die dubbele keys in ELKE mapping weigert (PyYAML zwijgt daarover)."""


def _no_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ValueError(
                f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep)


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


def strict_pkg():
    return yaml.load(PKG_PATH.read_text(encoding="utf-8"), Loader=StrictLoader)


def test_package_geen_dubbele_sleutels():
    pkg = strict_pkg()
    # sanity: het blok dat de bug veroorzaakte, bestaat nu één keer met ALLE helpers
    assert "prijs_btw" in pkg["input_number"], "prijshelpers weggefilterd?!"
    assert len(pkg["input_number"]) == 9


def test_alle_verwachte_helpers_aanwezig_in_geparsed_package():
    pkg = strict_pkg()
    voor_de_prijs = {"prijs_btw", "prijs_energiebelasting", "prijs_opslag_afname",
                     "prijs_opslag_levering", "prijs_laad_drempel",
                     "prijs_afwijkingsdrempel"}
    voor_de_accu = {"accu_capaciteit_kwh", "accu_vermogen_in_kw", "accu_vermogen_uit_kw"}
    assert voor_de_prijs | voor_de_accu <= set(pkg["input_number"]), \
        "elke helper uit de UI-kaart hoort in het geparsede package te staan"
    assert {"accu_bron_entity"} == set(pkg["input_text"])
    assert "prijs_saldering_energiebelasting_teruggave" in pkg["input_boolean"]


def test_handmatig_veld_overal_verwijderd():
    # package, cards, golden, installer: het veld bestaat nergens meer
    for rel in ("custom_components/energyprijs/package.yaml",
               "custom_components/energyprijs/cards.py",
               "tests/golden_dashboard.yaml"):
        tekst = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
        assert "accu_handmatig_pct" not in tekst, rel
    # installer mag hem SLECHTS als verouderde helper noemen (registry-opruiming)
    inst = (Path(__file__).resolve().parents[1]
            / "custom_components/energyprijs/installer.py").read_text(encoding="utf-8")
    assert inst.count("accu_handmatig_pct") == 1 and "VEROUDERDE_HELPERS" in inst
    # README mag het alleen in changelog/contextuele tekst vermelden (met backticked
    # verwijderde-helpermelding), niet als actieve helper: geen tabelrij "vul het percentage zelf in"
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "vul het percentage zelf in" not in readme


# ── 3) kaarten ↔ package: geen losse eindjes ───────────────────────────────

# Entiteiten die NIET door ons package komen maar van integraties of de gebruiker:
EXTERN_TOEGESTAAN = {
    "sensor.nord_pool_nl_current_price",
    "sensor.enerprice_nl_day_ahead_prices_market",
    "sensor.energyzero_today_energy_current_hour_price",
    "binary_sensor.enerprice_nl_day_ahead_prices_api_data_available",
    "notify.home",
}


def _package_entiteiten(pkg):
    """Alle entity_id's die het package definieert of aanmaakt."""
    eids = set()
    for domain in ("input_number", "input_text", "input_boolean"):
        for oid in pkg.get(domain, {}):
            eids.add(f"{domain}.{oid}")
    for block in pkg.get("template", []):
        for plat in ("sensor", "binary_sensor", "number", "select", "switch"):
            for ent in block.get(plat, []) or []:
                uid = ent.get("unique_id", "")
                naam = re.sub(r"[^a-z0-9]+", "_", str(ent.get("name", "")).lower()).strip("_")
                # HA slugify van de name → entity_id; unique_id is onze eigen sleutel
                eids.add(f"{plat}.{uid}")
                eids.add(f"{plat}.{naam}")
    return eids


def test_elke_entiteit_uit_cards_bestaat_in_package_of_is_extern():
    import sys
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from custom_components.energyprijs.cards import (ACCUCONTRACT_CARD,
                                                     ACCUEENHEDEN_CARD,
                                                     CONTRACT_CARD, GRAFIEK_CARD,
                                                     NU_CARD)
    pkg = strict_pkg()
    pakkent = _package_entiteiten(pkg)

    refs = set()
    def verzamel(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("entity",) and isinstance(v, str):
                    refs.add(v)
                elif k in ("entities", "series") and isinstance(v, list):
                    for it in v:
                        if isinstance(it, str):
                            refs.add(it)
                        else:
                            verzamel(it)
                else:
                    verzamel(v)
        elif isinstance(obj, list):
            for it in obj:
                verzamel(it)
        elif isinstance(obj, str):
            # states('...') / state_attr('...', ...) / has_value('...') in markdown-content
            refs.update(re.findall(r"(?:states|state_attr|has_value)\(\s*'([^']+)'", obj))
    for card in (NU_CARD, GRAFIEK_CARD, CONTRACT_CARD, ACCUEENHEDEN_CARD, ACCUCONTRACT_CARD):
        verzamel(card)

    onbekend = {e for e in refs
                if "." in e and e not in pakkent and e not in EXTERN_TOEGESTAAN
                and not e.startswith(("sensor.stroomprijs", "sensor.prijzen",
                                      "binary_sensor.prijzen"))}
    assert not onbekend, f"kaarten verwijzen naar ongedefinieerde entiteiten: {onbekend}"


def test_accu_template_sensor_definieert_zichzelf_niet_als_default_bron():
    """De contract-sensor heet energyprijs_accu_percentage (prefix, géén botsing)."""
    strict_pkg()  # parset door de strikte loader — faalt al bij dup-sleutels
    blob = PKG_PATH.read_text(encoding="utf-8")
    assert "energyprijs_accu_percentage" in blob
    assert "unique_id: accu_percentage_pkg" not in blob
    # state-based: geen triggers-blok rond dit template-onderdeel
    m = re.search(r"- sensor:\n(?:[^\n]+\n)*?        unique_id: energyprijs_accu_percentage", blob)
    assert m and "triggers:" not in blob[max(0, m.start()-200):m.start()+50]
