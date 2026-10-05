"""Energyprijs — installer-integratie.

Schrijft het stroomprijs-package naar /config/packages/ en bewaakt
configuration.yaml op de packages-include. De entiteiten zelf komen uit het
YAML-package; deze integratie koppelt ze alleen zichtbaar aan de config-entry
(één device + entity_registry-links), zodat de integratiepagina niet leeg blijft.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from datetime import timedelta

from pathlib import Path

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, PACKAGE_FILENAME, VERSION as _VERSION
from .installer import (
    async_register_services,
    _dashboard_opslaan,
    _manifest_version,
    _ensure_helper_defaults,
    defaults_klaar,
    sync_package_if_changed as installer_sync_package,
)

_LOGGER = logging.getLogger(__name__)

# Entiteiten die het package aanmaakt, mirroring package.yaml.
# Template-entiteiten hebben een unique_id → koppelen op (platform, unique_id).
# Helpers (input_number/input_boolean) hebben géén unique_id → op entity_id.
TEMPLATE_UNIQUE_IDS: list[tuple[str, str]] = [
    ("sensor", "prijzen_bron_nordpool"),
    ("sensor", "prijzen_bron_enerprice"),
    ("sensor", "prijzen_bron_energyzero"),
    ("sensor", "stroomprijs_basis"),
    ("sensor", "stroomprijs_daglijst"),
    ("sensor", "stroomprijs_afname"),
    ("sensor", "stroomprijs_levering"),
    ("sensor", "energyprijs_accu_percentage"),
    ("sensor", "energyprijs_pv_vandaag"),
    ("sensor", "energyprijs_pv_morgen"),
    ("binary_sensor", "prijzen_kruiscontrole_afwijking"),
    ("binary_sensor", "prijzen_morgen_beschikbaar"),
]

HELPER_ENTITY_IDS: list[str] = [
    "input_number.prijs_btw",
    "input_number.prijs_energiebelasting",
    "input_number.prijs_opslag_afname",
    "input_number.prijs_opslag_levering",
    "input_number.prijs_afwijkingsdrempel",
    "input_number.prijs_laad_drempel",
    "input_boolean.prijs_saldering_energiebelasting_teruggave",
    "input_text.accu_bron_entity",
    "input_number.accu_capaciteit_kwh",
    "input_number.accu_vermogen_in_kw",
    "input_number.accu_vermogen_uit_kw",
    "input_text.pv_bron_vandaag",
    "input_text.pv_bron_morgen",
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registreer de installatieservices."""
    await async_register_services(hass)
    return True


async def _ruim_verouderde_helpers(hass: HomeAssistant) -> None:
    """Verwijder helpers die het package niet meer definieert (v1.2.42-review).

    Een in een eerdere release meegeleverde helper (nu: input_number.accu_handmatig_pct)
    blijft anders als 'niet meer beschikbaar'-entiteit in de registry staan.
    Veiligheidsregel: alleen verwijderen als de entity in de registry koppelbaar is
    aan DEZE config-entry (door ons package aangemaakt); een door de gebruiker zelf
    gemaakte gelijknamige helper laten we met rust.
    """
    from .installer import VEROUDERDE_HELPERS

    reg = er.async_get(hass)
    entry_ids = {e.entry_id for e in hass.config_entries.async_entries(DOMAIN)}
    for eid in VEROUDERDE_HELPERS:
        ent = reg.async_get(eid)
        if ent is None:
            continue
        if ent.config_entry_id in entry_ids or ent.platform == DOMAIN:
            reg.async_remove(eid)
            _LOGGER.info("energyprijs: verouderde helper %s verwijderd", eid)


@callback
def _link_entities(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> int:
    """Koppel package-entiteiten aan de config-entry + device. Idempotent."""
    reg = er.async_get(hass)
    gekoppeld = 0
    for platform, uid in TEMPLATE_UNIQUE_IDS:
        # registry-sleutel is (platform, domain, unique_id); bij template-
        # entiteiten is platform == domein van de entiteit zelf.
        eid = reg.async_get_entity_id(platform, "template", uid)
        if eid is None:
            continue
        ent = reg.async_get(eid)
        if ent is not None and ent.config_entry_id != entry.entry_id:
            try:
                reg.async_update_entity(eid, config_entry_id=entry.entry_id, device_id=device_id)
                gekoppeld += 1
            except Exception:  # noqa: BLE001
                _LOGGER.debug("energyprijs: koppelen %s mislukt", eid)
    for eid in HELPER_ENTITY_IDS:
        ent = reg.async_get(eid)
        if ent is not None and ent.config_entry_id != entry.entry_id:
            try:
                reg.async_update_entity(eid, config_entry_id=entry.entry_id, device_id=device_id)
                gekoppeld += 1
            except Exception:  # noqa: BLE001
                _LOGGER.debug("energyprijs: koppelen %s mislukt", eid)
    return gekoppeld


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Maak het apparaat, koppel entiteiten en plan de achtergrondtaken.

    Services registreert ALLEEN async_setup (HA roept die gegarandeerd één keer
    per start vóór elke setup_entry aan); dubbel registreren was overbodig.
    """
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "energyprijs-package")},
        name="Energyprijs package",
        manufacturer="Energyprijs",
        model="3-bronnen stroomprijs-package",
        sw_version=_VERSION,
    )

    # Het package wordt pas bij een herstart geladen; direct na installeren
    # bestaan de entiteiten dus nog niet. Review 4 okt '26: het commentaar
    # beloofde "elk half uur opnieuw" maar er was géén timer — entiteiten die
    # later in de registry verschenen werden nooit gekoppeld. Nu wél: een
    # halfuurtijdner die stopt zodra alles (< totaal resterend) onder het
    # device staat.
    totaal = len(TEMPLATE_UNIQUE_IDS) + len(HELPER_ENTITY_IDS)

    def _try_link(_=None) -> None:
        n = _link_entities(hass, entry, device.id)
        if n:
            _LOGGER.info("energyprijs: %d package-entiteiten gekoppeld", n)

    unsub_link = async_track_time_interval(hass, _try_link, timedelta(minutes=30))
    entry.async_on_unload(unsub_link)
    _try_link()

    # Package synchroniseren vóór alles + éénmalige contract-defaults.
    # Beide zijn non-fataal: een fout hier mag de entry-setup nooit breken.
    async def _sync_package_and_defaults(_now=None) -> None:
        try:
            await installer_sync_package(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: package-sync mislukt", exc_info=True)
        try:
            await _ruim_verouderde_helpers(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: opruimen verouderde helpers mislukt", exc_info=True)
        try:
            await _ensure_helper_defaults(hass)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: defaults-setten mislukt", exc_info=True)

    task = hass.async_create_task(_sync_package_and_defaults())
    entry.async_on_unload(lambda: task.cancel() if not task.done() else None)

    # Zet een herkenbare titel op de entry → de integratie-tegel linkt naar de services
    try:
        if entry.title != "Energyprijs":
            hass.config_entries.async_update_entry(entry, title="Energyprijs")
    except Exception:  # noqa: BLE001
        pass

    # ── 5-min back-up timer: alleen zolang het dashboard niet op de huidige
    #    manifest-versie staat. Biedt vangnet als het package te laat laadt.
    # ────────────────────────────────────────────────────────────────────────
    async def _auto_dashboard(_now=None) -> None:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        if not hass.is_running:
            return
        if hass.data.get(LOVELACE_DATA) is None:
            return

        # Package moet klaar zijn
        reg = er.async_get(hass)
        if reg.async_get("input_number.prijs_btw") is None:
            return

        # Defaults kunnen hier nog ontbreken als beide eerdere runs te vroeg
        # vielen (helper-stats leeg). IsDone-bewaking in de store maakt dit cheap.
        if not await defaults_klaar(hass):
            try:
                await _ensure_helper_defaults(hass)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("energyprijs: defaults in timer mislukt", exc_info=True)

        manifest_version = _manifest_version(hass)
        if entry.data.get("dashboard_versie") == manifest_version:
            return  # al op de juiste versie

        try:
            res = await _dashboard_opslaan(hass)
            _LOGGER.info("energyprijs: dashboard back-up → %s", res.get("act"))
            if res.get("act") in ("aangemaakt", "bijgewerkt", "huidig"):
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "dashboard_versie": manifest_version}
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: dashboard nog niet gereed — later opnieuw",
                          exc_info=True)

    # ── Startup-orchestratie (les uit WrtManager #156 + HA core #165767):
    #    Pas nadat HA volledig is gestart (EVENT_HOMEASSISTANT_STARTED) maken we
    #    dashboards/resources aan — anders raast dat concurrent met andere
    #    integraties en de laatste schrijver wint.
    #
    #    Volgorde:
    #      1. EVENT_HOMEASSISTANT_STARTED (of direct als HA al draait bij reload)
    #      2. Package-control: input_number.prijs_btw MOET in de registry staan
    #      3. Eénmalig contract-defaults (na eerste install, helpers op 0)
    #      4. Pas dan _dashboard_opslaan (DashboardsCollection + LovelaceStorage)
    #      5. 5-min back-up timer alleen zolang het nog niet is geslaagd
    #


    def _package_klaar() -> bool:
        reg = er.async_get(hass)
        return reg.async_get("input_number.prijs_btw") is not None

    def _dashboard_klaar() -> bool:
        """True als het dashboard op de huidige manifest-versie staat."""
        return entry.data.get("dashboard_versie") == _manifest_version(hass)

    async def _startup_dashboard(_event=None) -> None:
        _LOGGER.debug("energyprijs: dashboard-check bij startup")
        # Eerst de taken die bij setup misschien te vroeg vielen (helpers bestonden
        # toen nog niet in states): package-sync + contract-defaults. Review 4 okt:
        # zonder dit punt had een vroege setup-run de defaults voor altijd gemist.
        await _sync_package_and_defaults()
        if _dashboard_klaar():
            _LOGGER.debug("energyprijs: dashboard al op versie %s — skip", _manifest_version(hass))
            return
        if not _package_klaar():
            _LOGGER.info("energyprijs: package nog niet geladen; dashboard later")
            return
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        if hass.data.get(LOVELACE_DATA) is None:
            # Lovelace nog niet actief (bv. test-harness zonder http/lovelace):
            # de 5-min back-up timer neemt over zodra het wél kan.
            _LOGGER.debug("energyprijs: lovelace nog niet actief — timer neemt over")
            return
        try:
            res = await _dashboard_opslaan(hass)
            act = res.get("act")
            _LOGGER.info("energyprijs: dashboard bij startup → %s", act)
            if act in ("aangemaakt", "bijgewerkt", "huidig"):
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "dashboard_versie": _manifest_version(hass)}
                )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("energyprijs: dashboard-aanmaak bij startup mislukt — 5-min timer overneemt")

    # Startup-check: async_at_started handelt koude start ÉN entry-reload af,
    # en is per definitie thread-safe (HA's eigen helper voor precies dit).
    # Eerdere versies deden dit met een lambda + hass.async_create_task, maar
    # het STARTED-event wordt vanuit een executor-thread afgevuurd → RuntimeError
    # + 'coroutine never awaited' (live-log 3 okt). Niet opnieuw.
    from homeassistant.helpers.start import async_at_started

    entry.async_on_unload(async_at_started(hass, _startup_dashboard))

    # 5-min back-up: alleen actief zolang het dashboard niet op de huidige
    # manifest-versie staat. Biedt vangnet als het package te laat laadt of
    # de startup-check te vroeg draaide.
    unsub2 = async_track_time_interval(hass, _auto_dashboard, timedelta(minutes=5))
    entry.async_on_unload(unsub2)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Opruimen bij verwijderen: ons dashboard-item + repair-issue.

    Het package op disk laten we staan? Nee — dat hoort bij deze integratie en
    wordt door HACS toch niet aangeraakt; we verwijderen het expliciet, samen
    met de entity-/device-koppelingen die wij hebben aangebracht. De
    configuration.yaml hoeven we nooit terug te draaien (wij schrijven daar
    niet meer — zie P2-fix).
    """
    from homeassistant.components import frontend
    from homeassistant.components.lovelace import dashboard as lb_dash
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from .installer import DASH_ID

    # 1) dashboard-item + storage van onszelf verwijderen
    if hass.data.get(LOVELACE_DATA) is not None:
        try:
            coll = lb_dash.DashboardsCollection(hass)
            await coll.async_load()
            item = next((it for it in coll.data.values()
                         if it.get("url_path") == DASH_ID), None)
            if item is not None:
                store = lb_dash.LovelaceStorage(hass, item)
                await store.async_delete()
                await coll.async_delete_item(item["id"])
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: dashboard-opruimen mislukt", exc_info=True)
        try:
            frontend.async_remove_panel(hass, DASH_ID, warn_if_unknown=False)
        except Exception:  # noqa: BLE001
            pass

    # 2) package-bestand van disk halen + repair-issue sluiten
    def _cleanup_files() -> None:
        pkg = Path(hass.config.path()) / "packages" / PACKAGE_FILENAME
        try:
            pkg.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        await hass.async_add_executor_job(_cleanup_files)
    except Exception:  # noqa: BLE001
        pass
    try:
        ir.async_delete_issue(hass, DOMAIN, "package_restart_needed")
    except Exception:  # noqa: BLE001
        pass


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to unload — we own no platforms."""
    return True
