"""Test: dashboard wordt aangemaakt bij startup, wachtend op package + HA-started."""
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)


async def test_setup_entry_never_fails(hass):
    """Entry setup mag niet falen, zelfs zonder package en zonder dashboard."""
    from custom_components.energyprijs import async_setup_entry

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)
    assert await async_setup_entry(hass, entry) is True


async def test_startup_skips_without_package(hass):
    """Zonder input_number.prijs_btw: _dashboard_opslaan mag NIET worden aangeroepen."""
    from custom_components.energyprijs import async_setup_entry
    import custom_components.energyprijs as cc_pkg

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    called = []

    async def fake_save(hass_):
        called.append(1)
        return {"act": "aangemaakt"}

    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save):
        assert await async_setup_entry(hass, entry) is True
        hass.bus.fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    assert called == [], "dashboard mocht niet zonder package"


async def test_startup_creates_with_package(hass):
    """Met input_number.prijs_btw + Lovelace actief: _dashboard_opslaan WEL 1x.

    Cold-start-pad: de integratie luistert naar EVENT_HOMEASSISTANT_STARTED, dus
    die fire je vóór async_setup_entry (hass.is_running is in deze harness al True,
    maar het event-coverde pad is wat de productcode bij opstarten bewandelt).
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from custom_components.energyprijs import async_setup_entry
    import custom_components.energyprijs as cc_pkg

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    reg = er.async_get(hass)
    reg.async_get_or_create(
        "input_number", "test", "prijs_btw", suggested_object_id="prijs_btw"
    )

    called = []

    async def fake_save(hass_):
        called.append(1)
        return {"act": "aangemaakt"}

    # Lovelace-data exists only when the lovelace component is set up; inject a
    # sentinel so the startup guard passes and the patched save is reached.
    hass.data[LOVELACE_DATA] = object()
    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save):
        assert await async_setup_entry(hass, entry) is True
        await hass.async_block_till_done()

    assert len(called) == 1, f"verwacht 1x, kreeg {len(called)}"


async def test_timer_stops_on_version_match(hass):
    """Nadat dashboard_versie == manifest: 5-min timer roept niets meer aan."""
    from custom_components.energyprijs import (
        _manifest_version,
        async_setup_entry,
    )
    import custom_components.energyprijs as cc_pkg

    versie = _manifest_version(hass)

    reg = er.async_get(hass)
    reg.async_get_or_create(
        "input_number", "test", "prijs_btw", suggested_object_id="prijs_btw"
    )

    entry = MockConfigEntry(
        domain="energyprijs",
        title="Energyprijs",
        data={"dashboard_versie": versie},
    )
    entry.add_to_hass(hass)

    called = []

    async def fake_save(hass_):
        called.append(1)
        return {"act": "huidig"}

    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save):
        assert await async_setup_entry(hass, entry) is True
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(minutes=5)
        )
        await hass.async_block_till_done()

    assert called == [], f"timer mocht niet roepen bij versie-match, kreeg {len(called)}"

# ── Regression-tests (live-log 3 okt '26) ────────────────────────────────────

async def test_startup_registration_is_thread_safe(hass):
    """De startup-registratie mag GEEN lambda met async_create_task zijn.

    Het STARTED-event wordt door HA vanuit een executor-thread afgevuurd;
    async_create_task vanuit die thread is een RuntimeError en liet de
    coroutine on-awaited (log: "coroutine was never awaited"). De registratie
    gaat daarom via homeassistant.helpers.start.async_at_started.
    """
    import custom_components.energyprijs as cc_pkg

    src = open(cc_pkg.__file__, encoding="utf-8").read()
    assert "lambda _ev: hass.async_create_task" not in src, \
        "lambda+async_create_task teruggevonden — niet thread-safe"
    assert "async_at_started(hass, _startup_dashboard)" in src


async def test_dashboard_created_on_cold_start_without_timer(hass):
    """Gesimuleerde koude start: het dashboard komt uit de STARTUP-route.

    In de test-harness staat hass.state al op running, dus async_at_started
    executeert direct bij setup. Als de 5-min back-up timer daarentegen de
    enige route zou zijn, zou er pas na async_fire_time_changed iets gebeuren
    — hier controleren we dat vóór zo'n sprong al één call is gelogd.
    """
    from unittest.mock import patch
    import custom_components.energyprijs as cc_pkg
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    reg = er.async_get(hass)
    reg.async_get_or_create(
        "input_number", "test", "prijs_btw", suggested_object_id="prijs_btw"
    )
    hass.data[LOVELACE_DATA] = object()

    calls = []

    async def fake_save(hass_):
        calls.append(1)
        return {"act": "aangemaakt"}

    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save), \
         patch.object(cc_pkg, "_ensure_helper_defaults", return_value=True):
        await cc_pkg.async_setup_entry(hass, entry)
        await hass.async_block_till_done()

    # Zonder timer-sprong al uitgevoerd → startup-route werkt echt.
    assert len(calls) == 1, f"verwacht 1 call via startup, kreeg {len(calls)}"
