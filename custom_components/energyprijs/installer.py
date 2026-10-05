"""Energyprijs-installer.

Doeboel:
  1. Package-YAML → /config/packages/energyprijs.yaml
  2. configuration.yaml: packages-include garanderen
     (voegt homeassistant: packages: !include_dir_named packages toe als die ontbreekt)
  3. Melding: herstart nodig (of optioneel: automatische herstart)

De package staat ingebed in package.yaml naast dit bestand, zodat de
integratie zelfvoorzienend is (geen netwerk nodig, werkt achter firewalls).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir

from . import cards as _cards

try:
    from homeassistant.core import SupportsResponse
except ImportError:  # kern < 2024.4 had 'Optional' i.p.v. 'ONLY/OPTIONAL'
    SupportsResponse = None

from .const import DOMAIN, PACKAGE_FILENAME, PACKAGE_SOURCE, CONFIG_FILENAME

_LOGGER = logging.getLogger(__name__)

CONF_FORCE_RESTART = "force_restart"

INSTALL_SCHEMA = vol.Schema(
    {vol.Optional(CONF_FORCE_RESTART, default=False): cv.boolean},
    extra=vol.ALLOW_EXTRA,
)

# Eénmalige startwaarden (NL-standaarden). Zonder 'initial' in het package
# herstelt HA bij herstart de LAATSTE waarde van de gebruiker — die mag niet
# overgeschreven worden. Bij allereerste installatie bestaan de helpers nog
# niet, dus zet we deze hier één keer via input_number.set_value; daarna
# bepaalt alleen Jan wat ze zijn. (Zie _defaults_gezet in entry.data.)
HELPERS_DEFAULTS: dict[str, float] = {
    "prijs_btw": 0.21,
    "prijs_energiebelasting": 0.0916,      # 2026-peil excl. btw
    "prijs_opslag_afname": 0.019,          # neutraal — eigen contract invullen
    "prijs_opslag_levering": 0.002,        # neutraal — eigen contract invullen
    "prijs_laad_drempel": 0.337,
    "prijs_afwijkingsdrempel": 0.005,
    # accu-contract (v1.2.42): conservatieve middenwaarden; gebruiker verzet ze.
    "accu_capaciteit_kwh": 10.0,
    "accu_vermogen_in_kw": 5.0,
    "accu_vermogen_uit_kw": 5.0,
}

# Helpers die in eerdere versies zijn meegeleverd maar niet meer door het package
# worden gedefinieerd → bij setup uit de entity registry opruimen, anders blijft er
# een "niet meer beschikbaar"-entiteit achter (review v1.2.42, punt 3).
VEROUDERDE_HELPERS: tuple[str, ...] = ("input_number.accu_handmatig_pct",)


def _config_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path())


# ── Versie-constanten uit manifest (één bron, geen I/O in de event-loop) ───
try:
    from .const import VERSION as _VERSION_STR
    _MANIFEST = {"version": _VERSION_STR}
except Exception:  # noqa: BLE001 — alleen tijdens extreem early import
    _MANIFEST = {}


def _write_package_sync(hass: HomeAssistant) -> Path:
    """Het ingebedde package naar /config/packages schrijven (blok-I/O, executor-only).

    Idempotent: het bronbestand uit de integratiemap is leidend en overschrijft
    het doel volledig. (De oude regel-voor-regel 'onttrekking' van input_number
    uit het bestaande bestand deed niets — het bestand werd daarna toch geheel
    herschreven — en is daarom geschrapt.)
    """
    packages_dir = _config_dir(hass) / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    target = packages_dir / PACKAGE_FILENAME
    source = Path(__file__).parent / PACKAGE_SOURCE
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


async def _write_package(hass: HomeAssistant) -> Path:
    """Async wrapper: wegschrijven buiten de event-loop (HA 2026 blocking-call-eis)."""
    return await hass.async_add_executor_job(_write_package_sync, hass)


async def sync_package_if_changed(hass: HomeAssistant) -> bool:
    """Schrijf het ingebedde package ALLEEN bij inhoudelijke wijziging.

    Chicken-and-egg (live-log 3 okt '26): een HACS-update vervangt alleen
    custom_components/; het op disk staande /config/packages/energyprijs.yaml
    blijft oud tot de integratie het herschrijft — en packages kunnen na het
    laden niet worden herladen. Daarom: zo vroeg mogelijk (async_setup_entry)
    synchroniseren op sha256, en bij een write een repair-issue zetten dat de
    gebruiker naar de verplichte herstart wijst. Geeft True terug als disk
    werd bijgewerkt (herstart nodig om het te laden).
    """
    changed = await hass.async_add_executor_job(_sync_package_sync, hass)
    if changed:
        await _create_restart_issue(hass)
    else:
        await _resolve_restart_issue(hass)
    return changed


def _package_gelijk_sync(hass: HomeAssistant) -> bool:
    """Heeft het package op disk exact dezelfde inhoud als het ingebedde?"""
    target = _config_dir(hass) / "packages" / PACKAGE_FILENAME
    source = Path(__file__).parent / PACKAGE_SOURCE
    if not target.exists():
        return False
    import hashlib

    def h(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return h(target) == h(source)


def _sync_package_sync(hass: HomeAssistant) -> bool:
    """Executor-deel van sync_package_if_changed: vergelijken + eventueel schrijven."""
    if _package_gelijk_sync(hass):
        return False
    _write_package_sync(hass)
    _LOGGER.info("energyprijs: package bijgewerkt op disk — HERSTART vereist om het te laden")
    return True


async def _create_restart_issue(hass: HomeAssistant) -> None:
    try:
        ir.async_create_issue(
            hass, DOMAIN, "package_restart_needed",
            is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key="package_restart_needed",
            translation_placeholders={"versie": _manifest_version(hass)},
        )
    except Exception:  # noqa: BLE001 — issue is behulpzaam, niet kritiek
        _LOGGER.debug("energyprijs: repair-issue aanmaken mislukt", exc_info=True)


async def _resolve_restart_issue(hass: HomeAssistant) -> None:
    try:
        ir.async_delete_issue(hass, DOMAIN, "package_restart_needed")
    except Exception:  # noqa: BLE001
        pass


PACKAGES_REGEL = "  packages: !include_dir_named packages"


def _packages_status_sync(config_path: Path) -> tuple[str, str]:
    """Controleer of HA onze package ZAL laden — zonder iets te schrijven.

    Les review 4 okt '26 (P2): de vorige versie plakte bij een bestaand
    homeassistant:-blok (met bv. alleen name:/unit_system:) een TWEEDE
    top-level homeassistant:-blok in. Dubbele sleutels zijn ongeldige YAML —
    HA startte dan niet meer goed. Een integratie hoort het hoofdbestand van
    de gebruiker al helemaal niet stil te herschrijven; deze functie leest en
    beoordeelt alleen. Statussen:

      ok            → include aanwezig (named of merge_named, met of zonder slash)
      geen_config   → configuration.yaml bestaat niet
      ui_only       → storage-only install (UI-modus), niets te patchen
      handmatig     → de regel ontbreekt; note bevat de exact te plakken regels.
                      De package staat al op disk; na invoegen + herstart laden
                      hem alle varianten.
    """
    if not config_path.exists():
        marker = config_path.parent / ".storage" / "auth_providers"
        if marker.exists():
            return "ui_only", ("configuration.yaml ontbreekt en deze install is "
                               "UI-only — packages werken hier niet; sensoren en "
                               "dashboard blijven beschikbaar via de services.")
        return "geen_config", "configuration.yaml bestaat niet; niets toegevoegd"

    original = config_path.read_text(encoding="utf-8")

    def _has(directive: str) -> bool:
        """Top-level homeassistant:-blok met packages eronder (geïnsprongen).

        Let op de ANCHOR: een `homeassistant:` dat zelf ingesprongen staat — bv.
        onder default_config:, zoals het oud energyprijs-blok van Jan deed — is
        GEEN top-level key en negeert HA stilzwijgend. Zulke blokken tellen dus
        NIET als ok; ze leveren 'handmatig' op met plakinstructie. Review 4 okt '26.
        """
        for m in re.finditer(r"(?m)^homeassistant\s*:[ \t]*$", original):
            tail = original[m.end():]
            # regels binnen het blok: leeg, commentaar of geïnsprongen content;
            # stop zodra een nieuwe kolom-0-sleutel begint.
            block_lines = []
            for ln in tail.splitlines()[1:]:
                if not ln.strip() or ln.lstrip().startswith("#"):
                    continue
                if ln[0] not in (" ", "\t"):
                    break
                block_lines.append(ln)
            pat = r"^\s+packages\s*:\s*!" + re.escape(directive) + r"\s+packages/?\s*$"
            if any(re.match(pat, bl) for bl in block_lines):
                return True
        return False

    for directive in ("include_dir_named", "include_dir_merge_named"):
        if _has(directive):
            return "ok", f"packages-include ({directive}) gevonden; niets gewijzigd"

    handmaat = ("In plaats van automatisch te schrijven: plak deze regels in "
                "configuration.yaml — als nieuw top-level blok op kolom 0, of "
                "(indien die er al is) 'packages:' INSPRINGEN onder je "
                "bestaande homeassistant:-blok:\n"
                "homeassistant:\n" + PACKAGES_REGEL)
    return "handmatig", handmaat


def _ensure_packages_include_sync(config_path: Path) -> tuple[bool, str]:
    """Verouderde ingang; gedraagt zich nu read-only (P2-fix 4 okt '26).

    Schrijft NIET meer naar configuration.yaml. Geeft (False, "[status] uitleg").
    """
    status, note = _packages_status_sync(config_path)
    return False, f"[{status}] {note}"


# ── Energie-dashboard (user dashboard) aanmaken/bijwerken ─────────────────

def _manifest_version(hass: HomeAssistant) -> str:
    """Versie uit het bij import gelezen manifest (geen I/O in de event-loop).

    importlib.metadata.version("energyprijs") doet bij elke call een listdir
    van de site-packages-root — een geblokkeerd I/O-pad dat HA 2026 flagt.
    Één bron: const.VERSION (review 4 okt '26, K3).
    """
    return str(_MANIFEST.get("version", "0"))

DASH_ID = "energyprijs"
DASH_TITEL = "Energie — stroomprijs"
DASH_ICOON = "mdi:flash"

async def _dashboard_opslaan(hass: HomeAssistant) -> dict:
    """Maak het user-dashboard aan of werk het bij — via HA's eigen collecties.

    User dashboards leven in HA-storage (geen los YAML-bestand):
      - .storage/lovelace_dashboards        → dashboard-metadata (DashboardsCollection)
      - .storage/lovelace.<dashboard-id>    → de kaartconfig (LovelaceStorage.async_save)

    We gebruiken daarvoor exact HA's publieke helpers, zodat panel + cache +
    lovelace_updated-event netjes meeliften en het dashboard direct zichtbaar is.

    Eerst: het ingebedde package wegschrijven. Een HACS-upgrade vervangt alléén
    custom_components/, dus /config/packages/energyprijs.yaml blijft anders op
    een oude (mogelijk ongeladbare) revisie staan tot iemand install aanroept.

    KNIEPUNT (bewust gekozen, 3 okt '26): er is GEEN publieke API voor
    "user-dashboard met panels toevoegen" — alleen `frontend.async_register_panel`
    (panel zonder storage-registratie) en de DashboardsCollection zelf, die HA
    intern houdt. We bouwen daarom een tweede instance op dezelfde storage-key:
    de itemids sluiten naadloos aan op de live-collectie (generate_id). Risico:
    `_flush_collection_save` gebruikt private attributen (`coll.store`,
    `coll._data_to_save`) om de metadata direct naar disk te duwen; bij een
    HA-update waarin die internals veranderen kan deze flush stil falen — dan
    staat het dashboard na ~10 s alsnog (HA's eigen delay-save), maar niet direct.
    De flush zit daarom in een try/except dat dat niet neerhaalt.
    """
    from .cards import (ACCUCONTRACT_CARD, ACCUEENHEDEN_CARD, CONTRACT_CARD,
                        GRAFIEK_CARD, NU_CARD, PVCONTRACT_CARD,
                        PVINSTELLINGEN_CARD)

    # ── 0a) package in sync met de geïnstalleerde code (veilige route:
    #        sha256-check + repair-issue bij een write, geen blinde overschrijving)
    try:
        await sync_package_if_changed(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("energyprijs: package-sync mislukt", exc_info=True)

    # ── 0) DIAGNOSE: draait deze instantie de LATEST code (versie-koppeling)?
    #    Als HACS/HA een verouderde module in RAM houden, zie je dat hier direct.
    manifest_version = _manifest_version(hass)
    diag = {"geinstalleerde_versie": manifest_version}

    # ── 1) dashboard-metadata: via HA's eigen lovelace-storage (met de live
    #    panel-registratie erbij). De draaiende DashboardsCollection is niet
    #    publiek te bereiken, dus bouwen we een tweede instance op exact dezelfde
    #    storage-key (.storage/lovelace_dashboards): itemids sluiten op elkaar aan
    #    (generate_id) en het add-change wordt zo netjes afgehandeld als via de UI
    #    (panel laten verlopen + storingen opschonen). Panel en kaartconfig voegen
    #    we daarna zelf toe via de publieke frontend/lovelace-helpers. ──
    from homeassistant.components import frontend
    from homeassistant.components.lovelace import dashboard as lb_dash
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    lov_data = hass.data.get(LOVELACE_DATA)
    if lov_data is None:
        raise RuntimeError(
            "Lovelace-integratie is niet actief — kan geen user-dashboard beheren."
        )

    # ── 1b) VALIDATIES — VÓÓR elke bijwerking (les live-log 3 okt '26, 17:52):
    #    eerder stond deze check ná async_create_item + panel-registratie, dus
    #    een gefaalde guard liet een LEEG dashboard achter. Nu: eerst toetsen,
    #    dan pas muteren. Een leeg dashboard is erger dan tijdelijk N/A.
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    alle_eids = {e.entity_id for e in ent_reg.entities.values()}
    diag["helpers_aanwezig"] = "input_number.prijs_btw" in alle_eids
    if not diag["helpers_aanwezig"]:
        raise RuntimeError(
            "De energie-helpers (input_number.prijs_btw …) ontbreken nog. "
            "Draai eerst de service energyprijs.install en herstart Home Assistant, "
            "voordat je dit dashboard vult."
        )

    # ── 1d) bronnen-check staat hieronder bij de kaartopbouw (warn-only).

    # Maak een foute panel-registratie onschadelijk (bv. overgebleven van een eerdere
    # versie van deze integratie): het re-registeren mag dan opnieuw slagen.
    frontend.async_remove_panel(hass, DASH_ID, warn_if_unknown=False)

    coll = lb_dash.DashboardsCollection(hass)
    await coll.async_load()

    existing = next((it for it in coll.data.values() if it.get("url_path") == DASH_ID), None)

    async def _flush_collection_save() -> None:
        """De collectie-save van HA zit op een timer van 10 s.

        Onmiddellijk flushen (delay=0) voorkomt dat de dashboard-metadata pas
        later — of helemaal niet, bij een tussentijdse herstart — op disk staat.
        """
        try:
            coll.store.async_delay_save(coll._data_to_save, 0)  # noqa: SLF001
            await hass.async_block_till_done()
        except Exception:  # noqa: BLE001
            pass

    # Bestaat ons dashboard al in de LIVE collectie (de instantie die de UI
    # bedient)? Haalbare route: een tweede DashboardsCollection op dezelfde
    # storage-key leest .storage/lovelace_dashboards — disk is waar de UI het
    # item vandaan haalt. De live-instantie zelf is niet publiek bereikbaar,
    # dus controleren we disk én registreren we daarna expliciet (hieronder).
    if existing is None:
        try:
            entry = await coll.async_create_item({
                "url_path": DASH_ID,
                "mode": "storage",
                "title": DASH_TITEL,
                "icon": DASH_ICOON,
                "show_in_sidebar": True,
                "require_admin": False,
                "allow_single_word": True,
            })
        except Exception as err:  # noqa: BLE001
            raise RuntimeError(f"dashboard aanmaken mislukt: {err}") from err
        act = "aangemaakt"
        await _flush_collection_save()
        # ── PROBLEEM 2 (review 5 okt '26): onze tweede collectie-instance heeft
        #    GEEN listeners, dus HA's storage_dashboard_changed draait niet en
        #    registreert het dashboard niet in de LIVE LovelaceData. De UI-websocket
        #    (lovelace/config?url_path=…) zoekt daar en krijgt 'config_not_found' →
        #    leeg dashboard tot een herstart. Oplossen doen we precies zoals core:
        #    handmatig registreren in hass.data[LOVELACE_DATA].dashboards. ──
        if DASH_ID not in lov_data.dashboards:
            try:
                lov_data.dashboards[DASH_ID] = lb_dash.LovelaceStorage(hass, entry)
                diag["live_geregistreerd"] = True
            except Exception:  # noqa: BLE001
                _LOGGER.warning("energyprijs: live-dashboardregistratie mislukt", exc_info=True)
                diag["live_geregistreerd"] = False
        else:
            diag["live_geregistreerd"] = "reeds_aanwezig"
        # panel zo snel mogelijk tonen; dit heeft geen effect op de luchtige
        # dashboard-view (mode "storage" haalt de content uit storage)
        try:
            frontend.async_register_built_in_panel(
                hass, "lovelace",
                frontend_url_path=DASH_ID,
                sidebar_title=DASH_TITEL,
                sidebar_icon=DASH_ICOON,
                require_admin=False,
                config={"mode": "storage"},
                update=True,
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        entry = existing
        act = "bijgewerkt"
        # Zelfde live-registratie als hierboven: mist de UI-collectie ons item
        # (bv. omdat HA het bij een eerdere run nooit heeft gezien), registreer nu.
        if DASH_ID not in lov_data.dashboards:
            try:
                lov_data.dashboards[DASH_ID] = lb_dash.LovelaceStorage(hass, entry)
                diag["live_geregistreerd"] = True
            except Exception:  # noqa: BLE001
                _LOGGER.warning("energyprijs: live-dashboardregistratie (bestaand) mislukt", exc_info=True)
                diag["live_geregistreerd"] = False
        try:
            frontend.async_register_built_in_panel(
                hass, "lovelace",
                frontend_url_path=DASH_ID,
                sidebar_title=DASH_TITEL,
                sidebar_icon=DASH_ICOON,
                require_admin=False,
                config={"mode": "storage"},
                update=True,
            )
        except ValueError:
            pass
        except Exception:  # noqa: BLE001
            pass

    dash_id = entry["id"]

    # ── 1c) prijsbronnen: WAARSCHUWING, geen blokkade. Bij EVENT_STARTED zijn
    #    template/integratie-sensoren vaak nog unknown; dat is race, geen fout.
    #    Structureel (= integratie níét geïnstalleerd) controleren we op domein-
    #    niveau via config entries, niet op state.
    PAKKET_BRONNEN = {
        "sensor.prijzen_bron_nordpool": ("nord_pool", "Nord Pool (core-integratie)"),
        "sensor.prijzen_bron_enerprice": ("enerprice", "EnerPrice (HACS: LenFaki; extended attributes AAN)"),
        "sensor.prijzen_bron_energyzero": ("energyzero", "EnergyZero (core-integratie)"),
    }
    werkend, dood, geinstalleerd = [], [], []
    installed_domains = {e.domain for e in hass.config_entries.async_entries()}
    for eid, (domein, naam) in PAKKET_BRONNEN.items():
        if domein in installed_domains or any(domein in d for d in installed_domains):
            geinstalleerd.append(naam)
        st = hass.states.get(eid)
        if st is not None and st.state not in ("unavailable", "unknown"):
            werkend.append(naam)
        else:
            dood.append(naam)
    diag["prijsbronnen_werkend"] = werkend
    diag["prijsbronnen_onbeschikbaar"] = dood
    if not werkend:
        _LOGGER.warning(
            "energyprijs: geen enkele prijsbron levert nu waarden (%s). Dashboard "
            "wordt wél gevuld; sensoren tonen N/A tot een bron vers is.",
            " · ".join(dood),
        )
        diag["prijsbronnen_waarschuwing"] = True

    # ── 2) kaartconfig: .storage/lovelace.<id> via LovelaceStorage (public API) ──
    from homeassistant.components.lovelace.const import ConfigNotFound

    store = lb_dash.LovelaceStorage(hass, entry)
    try:
        cfg = await store.async_load(force=False)
    except ConfigNotFound:
        cfg = None
    # async_save vereist een gevulde cache (_data) — async_load vulde 'm al wanneer
    # de storage bestond; bij ConfigNotFound (nog nooit opgeslagen) blijft ie None,
    # waarna async_save zelf _load() aanroept.

    views = (cfg or {}).get("views") or [{"title": "Energie", "path": "energie", "cards": []}]
    first = views[0]

    # ── idempotente check: is ons dashboard al gevuld met DEZE versie? Dan hoeft
    #    er niets te gebeuren — zo mag de service elke 5 min rustig langskomen. ──
    def _heeft_onze_kaarten(cards) -> bool:
        types = {str(c.get("type")) for c in cards if isinstance(c, dict)}
        return "custom:apexcharts-card" in types and "entities" in types

    def _opbouw_klopt(cards) -> bool:
        """De grafiekkaart moet exact de actuele opbouw van cards.py hebben.

        Les live-log 4 okt '26: een verouderde check (alleen yaxis_id 'prijzen',
        een kenmerk uit de multi-as-poging van 1.2.20-1.2.24 die nooit heeft
        gedraaid) maakte dat dashboards uit oudere versies — met kopwaarden en
        N/A onder de grafiek — bij elke herstart als 'actueel' golden en nooit
        werden vervangen. Nu: vergelijk de grafiekkaart sleutel-op-sleutel met
        GRAFIEK_CARD zelf; één bron van waarheid, dus elke kaartwijziging in
        cards.py forceert automatisch een herbouw van het dashboard.
        """
        graf = next((c for c in cards if isinstance(c, dict)
                     and c.get("type") == "custom:apexcharts-card"), None)
        return graf == GRAFIEK_CARD

    live_aanwezig = DASH_ID in lov_data.dashboards
    if (cfg is not None and act == "bijgewerkt"
            and first.get("energyprijs_versie") == manifest_version
            and _heeft_onze_kaarten(first.get("cards") or [])
            and _opbouw_klopt(first.get("cards") or [])
            and first.get("type") != "sections"):
        if live_aanwezig:
            return {"act": "huidig", "reeds_actueel_versie": manifest_version}
        # Review 5 okt '26, probleem 2: op disk is alles actueel, maar de LIVE
        # collectie kent ons dashboard niet → websocket vindt geen config.
        # Val door naar de normale schrijfroute; die registreert live en vult
        # de cache. Geen loop: na deze run is live_aanwezig True.
        diag["reden_doorgevallen"] = "niet_in_live_collectie"
    diag["view_type_voor"] = first.get("type", "(klassiek)")
    diag["cards_voor"] = len(first.get("cards") or [])
    # user dashboards worden in de UI als SECTIE-view aangemaakt ("New section");
    # secties hebben een nested structuur en kunnen niet direct losse kaarten dragen.
    # Onze kaarten zijn gewone cards → normaliseer naar een klassieke card-view.
    if first.get("type") == "sections" or any(
            isinstance(c, dict) and c.get("type") in ("section", "grid")
            for c in (first.get("cards") or [])):
        flat_cards = []
        for c in first.get("cards") or []:
            if isinstance(c, dict) and c.get("type") in ("section", "grid"):
                flat_cards.extend(c.get("cards") or [])
            else:
                flat_cards.append(c)
        first.pop("type", None)
        first["cards"] = flat_cards
    cards_list = first.get("cards") or []

    # onze kaarten herkennen op hun unieke entiteiten; rest blijft intact
    def _is_ours(card) -> bool:
        if not isinstance(card, dict):
            return False
        t = card.get("type")
        if t == "custom:apexcharts-card":
            ents = {x.get("entity") for x in card.get("series", []) if isinstance(x, dict)}
            return "sensor.stroomprijs_daglijst" in ents
        if t == "entities":
            ents = {c.get("entity") if isinstance(c, dict) else c for c in card.get("entities", [])}
            return ({"input_number.prijs_btw", "sensor.stroomprijs_afname",
                     "input_text.accu_bron_entity", "input_text.pv_bron_vandaag",
                     "input_text.pv_bron_morgen"} & ents)
        if t == "markdown":
            # accu- en pv-contracttegels herkennen op hun contract-sensoren
            return ("sensor.energyprijs_accu_percentage" in str(card.get("content", ""))
                    or "sensor.energyprijs_pv_vandaag" in str(card.get("content", "")))
        return False

    kept = [c for c in cards_list if not _is_ours(c)]
    removed = len(cards_list) - len(kept)
    first["cards"] = kept + [NU_CARD, GRAFIEK_CARD, CONTRACT_CARD,
                             ACCUEENHEDEN_CARD, ACCUCONTRACT_CARD,
                             PVCONTRACT_CARD, PVINSTELLINGEN_CARD]

    new_cfg = {"views": views}
    if (cfg or {}).get("jinja"):
        new_cfg["jinja"] = cfg["jinja"]
    await store.async_save(new_cfg)   # vuurt lovelace_updated af → frontend ververst

    # Kaarten in de LIVE LovelaceCache zetten: dezelfde instantie die de UI via
    # websocket bedient. async_save vult ._data, herbouwt de json-cache en vuurt
    # lovelace_updated af — de browser tekent de kaarten dan direct, zonder reload.
    try:
        live = lov_data.dashboards.get(DASH_ID)
        if live is None:
            # alsnog registreren (kan mislukt zijn bij create vóór deze run)
            try:
                live = lb_dash.LovelaceStorage(hass, entry)
                lov_data.dashboards[DASH_ID] = live
                diag["live_geregistreerd"] = True
            except Exception:  # noqa: BLE001
                pass
        if live is not None and hasattr(live, "async_save"):
            await live.async_save(new_cfg)
            diag["cache_bijgewerkt"] = True
        else:
            diag["cache_bijgewerkt"] = False
    except Exception as e3:  # noqa: BLE001
        diag["cache_fout"] = str(e3)

    # ── TERUGVAL (review 5 okt): lukt live-registratie/cache niet, dan ziet de
    #    UI het dashboard pas na een herstart. Laat dat géén stil falen zijn:
    #    repair-issue + INFO-log in plaats van een leeg dashboard. ──
    if not diag.get("cache_bijgewerkt") and DASH_ID not in lov_data.dashboards:
        try:
            ir.async_create_issue(
                hass, DOMAIN, "dashboard_live_registratie",
                is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="dashboard_live_registratie",
                translation_placeholders={"versie": manifest_version},
            )
            diag["repair_issue"] = "dashboard_live_registratie"
            _LOGGER.info(
                "energyprijs: dashboard staat op disk maar NIET in de live "
                "collectie — herstart Home Assistant om het te tonen (repair-issue geplaatst)"
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: repair-issue mislukt", exc_info=True)
    else:
        try:
            ir.async_delete_issue(hass, DOMAIN, "dashboard_live_registratie")
        except Exception:  # noqa: BLE001
            pass

    # ── NAVRAAG: lees terug wat er echt op disk staat (catcht silent failures)
    try:
        back = await store.async_load(force=True)
        b_cards = (back or {}).get("views", [{}])[0].get("cards") or []
        diag["cards_na"] = len(b_cards)
        diag["types_na"] = sorted({str(c.get("type")) for c in b_cards if isinstance(c, dict)})
    except Exception as e2:  # noqa: BLE001
        diag["teruglees_fout"] = str(e2)

    # versie-TAG pas bijhouden als de opslag aantoonbaar werkte — anders blijft
    # een verkeerde tag de volgende ronde doen overslaan (de 1.2.20-stuck-bug).
    if diag.get("cache_bijgewerkt") or diag.get("cards_na"):
        first["energyprijs_versie"] = manifest_version

    return {
        "diag": diag,
        "act": act,
        "dashboard_id": dash_id,
        "verwijderde_eigen_oude_kaarten": removed,
        "totaal_cards_eerste_view": len(first["cards"]),
        "url_path": DASH_ID,
    }


_DEFAULTS_STORE_KEY = "energyprijs_defaults"


class _DefaultsStore:
    """Persistent markering per helper (overleeft herstarts)."""

    def __init__(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        self._store = Store(hass, 1, _DEFAULTS_STORE_KEY, private=False)
        self._data: dict[str, bool] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    def all_done(self) -> bool:
        return all(self.is_done(k) for k in HELPERS_DEFAULTS)

    def is_done(self, key: str) -> bool:
        return bool(self._data.get(key))

    async def mark(self, key: str) -> None:
        if not self._data.get(key):
            self._data[key] = True
            await self._store.async_save(self._data)


async def defaults_klaar(hass: HomeAssistant) -> bool:
    """Zijn alle contract-defaults al gemarkeerd? (read-only, laadt de store)"""
    store = _DefaultsStore(hass)
    await store.async_load()
    return store.all_done()


async def _ensure_helper_defaults(hass: HomeAssistant) -> bool:
    """Zet eenmalig de contract-defaults voor helpers die NOG NOOIT zijn ingevuld.

    Nuance (review 4 okt '26): "waarde exact 0" betekent "nog nooit gezet".
    Wie bewust 0 invult vóór de allereerste run, wordt die ene keer overschreven
    met de neutrale default — daarna beschermt het persistente vlaggetje per helper.

    Regels (live-log 3 okt '26, punt 4):
      - Alleen handelen als de entiteit bestaat EN beschikbaar is in states
        (een service-call op een ontbrekende entiteit deed stil niets en werd
        toch als gelukt gemarkeerd).
      - Alleen zetten als de huidige waarde exact 0 is — een gebruiker die
        zelf een waarde koos (ook 0 later? nee: 0 betekent hier 'nog nooit
        gezet', want input_number start op 0 zónder initial) wordt niet
        overschreven zodra er méér dan 0 staat.
      - Markering persistent via Store, PER HELPER; na succes pas markeren,
        geverifieerd door de state na de call te lezen.
    """
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    for key in HELPERS_DEFAULTS:
        if reg.async_get(f"input_number.{key}") is None:
            return False  # package nog niet geladen — startup/timer probeert opnieuw

    store = _DefaultsStore(hass)
    await store.async_load()

    gezet: list[str] = []
    for key, value in HELPERS_DEFAULTS.items():
        eid = f"input_number.{key}"
        if store.is_done(key):
            continue
        st = hass.states.get(eid)
        if st is None or st.state in ("unavailable", "unknown"):
            continue  # nog niet beschikbaar — volgende poging weer
        try:
            current = float(st.state)
        except (TypeError, ValueError):
            continue
        if current != 0:
            # Gebruiker heeft al ingevuld → nooit meer aanraken, wel afvinken.
            await store.mark(key)
            continue
        try:
            await hass.services.async_call(
                "input_number", "set_value", {"entity_id": eid, "value": value},
                blocking=True,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("energyprijs: set_value %s mislukt: %s", eid, e)
            continue
        # Verifiëer vóór markeren: is de state daadwerkelijk veranderd?
        new_st = hass.states.get(eid)
        try:
            if new_st is not None and abs(float(new_st.state) - value) < 1e-9:
                await store.mark(key)
                gezet.append(key)
        except (TypeError, ValueError):
            pass

    if gezet:
        _LOGGER.info("energyprijs: contract-defaults gezet: %s", ", ".join(gezet))
    return all(store.is_done(k) for k in HELPERS_DEFAULTS)


async def async_register_services(hass: HomeAssistant) -> None:
    """Registreer energyprijs.install en energyprijs.status."""

    async def handle_install(call: ServiceCall) -> dict:
        hass_config = _config_dir(hass)
        cfg_file = hass_config / CONFIG_FILENAME

        # 1) package synchroniseren (sha256 — alleen schrijven bij verschil,
        #    inclusief repair-issue bij een write)
        pkg_changed = await sync_package_if_changed(hass)

        # 2) configuration.yaml CONTROLEREN (nooit schrijven — P2-fix 4 okt '26)
        status, note = await hass.async_add_executor_job(_packages_status_sync, cfg_file)

        # 3) status bepalen
        result = {
            "package_bijgewerkt": pkg_changed,
            "configuration_yaml_status": status,
            "toelichting": note,
            "herstart_nodig": pkg_changed or status == "handmatig",
        }

        # 4) dashboard automatisch aanmaken (of bijwerken) — één handeling
        try:
            dash = await _dashboard_opslaan(hass)
            result["dashboard"] = dash.get("act", "onbekend")
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("energyprijs.install: dashboard-aanmaak mislukt: %s", e)
            result["dashboard_fout"] = str(e)

        if restart_needed and call.data.get(CONF_FORCE_RESTART, False):
            _LOGGER.warning("energyprijs: herstart wordt forcerend geactiveerd")
            await hass.services.async_call("homeassistant", "restart", blocking=False)
            result["herstart_gestart"] = True
        elif restart_needed:
            result["actie"] = (
                "Herstart Home Assistant (Instellingen → Systeem → Herstarten) "
                "om de packages-include te activeren. Het dashboard is al aangemaakt."
            )
        else:
            result["actie"] = "Alles stond al goed; herstart niet nodig."

        # 5) Eénmalig defaults voor de contracthelpers (na restart pas bruikbaar)
        if not await _ensure_helper_defaults(hass):
            pass  # helpers bestaan pas na herstart; startup haalt het dan op

        _LOGGER.info("energyprijs.install → %s", result)
        return result

    async def handle_dashboard(call: ServiceCall) -> dict:
        """Maak het user-dashboard aan of werk de kaarten bij.

        Wordt NOOIT overgeslagen op alleen de versie-marker: een in de UI
        verwijderd dashboard wordt hiermee gegarandeerd hersteld (review 5 okt).
        """
        try:
            res = await _dashboard_opslaan(hass)
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("energyprijs.dashboard mislukt")
            return {"ok": False, "fout": str(e)}
        res["ok"] = True
        res["uitleg"] = (
            "Dashboard 'Energie — stroomprijs' staat nu in je dashboardmenu. "
            "Bij een volgende upgrade werk ik alleen de gemarkeerde blokken bij."
        )
        return res

    async def handle_cards(call: ServiceCall) -> dict:
        """Geef de kant-en-klare dashboardkaarten (grafiek + contractinvulvelden)."""
        from .cards import build_cards_yaml
        (nu, grafiek, contract, accueenheden, accucontract,
         pvcontract, pvinstellingen) = build_cards_yaml()
        return {
            "nu": nu,
            "grafiek": grafiek,
            "contract": contract,
            "accueenheden": accueenheden,
            "accucontract": accucontract,
            "pvcontract": pvcontract,
            "pvinstellingen": pvinstellingen,
            "uitleg": (
                "Plak de kaarten in deze volgorde in je view: 'nu' (grid-tegel met "
                "inkoop- en verkoopprijs), 'grafiek' (apexcharts bruto-staafjes zonder "
                "legenda, vereist HACS), 'contract' (entities-tegel), 'accueenheden' "
                "(accu-SOC + doorberekende kWh/uren), 'accucontract' (snelkoppeling "
                "naar jouw SOC-entity + capaciteit/vermogens), 'pvcontract' "
                "(verwachte zonnestroom vandaag/morgen + schatting in €) en "
                "'pvinstellingen' (snelkoppelingen naar jouw PV-forecast-entiteiten). "
                "Alles is dynamisch: sensoren herberekenen direct bij helper-wijziging."
            ),
        }

    async def handle_status(call: ServiceCall) -> dict:
        cfg_file = _config_dir(hass) / CONFIG_FILENAME
        pkg_file = _config_dir(hass) / "packages" / PACKAGE_FILENAME
        status, note = await hass.async_add_executor_job(_packages_status_sync, cfg_file)
        gelijk = await hass.async_add_executor_job(_package_gelijk_sync, hass)
        return {
            "configuration_yaml_bestaat": cfg_file.exists(),
            "packages_include_aanwezig": status == "ok",
            "configuration_yaml_status": status,
            "toelichting": note,
            "package_bestaat": pkg_file.exists(),
            "package_actueel": gelijk,
            "package_pad": str(pkg_file),
            "versie": _manifest_version(hass),
            "dashboard_bestaat": await dashboard_bestaat(hass),
        }

    hass.services.async_register(
        DOMAIN, "install", handle_install, schema=INSTALL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN, "cards", handle_cards,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "dashboard", handle_dashboard,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN, "status", handle_status, supports_response=SupportsResponse.ONLY,
    )


async def dashboard_bestaat(hass: HomeAssistant) -> bool:
    """Bestaat ons dashboard-item daadwerkelijk in .storage/lovelace_dashboards?

    Eén bron voor zowel __init__ (startup/timer-check, marker mag nooit alleen
    beslissen — review 5 okt '26 probleem 1) als handle_status. Leest via een
    verse DashboardsCollection op dezelfde storage-key die HA's UI-collectie
    vult; onbereikbaar → False (liever één herbouw te veel dan een stil
    verdwenen dashboard).
    """
    from homeassistant.components.lovelace import dashboard as lb_dash
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    if hass.data.get(LOVELACE_DATA) is None:
        return False
    try:
        coll = lb_dash.DashboardsCollection(hass)
        await coll.async_load()
        return any(it.get("url_path") == DASH_ID for it in coll.data.values())
    except Exception:  # noqa: BLE001
        _LOGGER.debug("energyprijs: dashboard-bestaanscheck mislukt", exc_info=True)
        return False
