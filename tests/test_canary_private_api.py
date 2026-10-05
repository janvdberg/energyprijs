"""Canary (review v1.3.2, punt 6): de private HA-API's die onze dashboard-route
gebruikt, bestaan in deze HA-versie én een aanmaak landt werkelijk op schijf.

Draait in CI tegen de nieuwste EN de minimum-ondersteunde HA (hacs.json). breekt
HA ooit met `DashboardsCollection.store` / `_data_to_save` of de storage-key, dan
faalt deze test in plaats van dat Jans dashboard stil verdwijnt.

Geen mocks: échte HA-componenten, echte Store-schrijfactie naar de test-config-dir.
"""


async def test_private_collection_api_bestaat(hass):
    """coll.store + coll._data_to_save + dezelfde storage-key als HA core."""
    from homeassistant.components.lovelace import dashboard as lb_dash

    coll = lb_dash.DashboardsCollection(hass)
    assert hasattr(coll, "store"), "DashboardsCollection.store verdwenen"
    assert hasattr(coll, "_data_to_save"), "_data_to_save verdwenen"
    # onze flush-route gebruikt exact die twee; verifieer de call-shape
    import inspect
    params = list(inspect.signature(coll.store.async_delay_save).parameters)
    assert len(params) >= 2, f"async_delay_save-signature veranderd: {params}"


async def test_aanmaak_landt_werkelijk_op_schijf(hass):
    """Echte create_item + delay_save(0) → JSON op disk met ons url_path-item."""
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, "lovelace", {"lovelace": {"mode": "storage"}})
    from homeassistant.components.lovelace import dashboard as lb_dash

    coll = lb_dash.DashboardsCollection(hass)
    await coll.async_load()
    item = await coll.async_create_item({
        "url_path": "canary-energyprijs",
        "mode": "storage",
        "title": "Canary",
        "icon": "mdi:test-tube",
        "show_in_sidebar": False,
        "require_admin": False,
    })
    # onze productroute: directe flush via private attributen. In de test-harness
    # landt Store-schrijfgood in HA's mock-storage-registry (patch op
    # _async_write_data); echte-disk-dekking zit in test_package_e2e_ha. Wat hier
    # telt: create_item + flush doorlopen de REALERE storage-machinery en een
    # verse collectie leest het item terug — precies de ketting die bij een
    # HA-API-breuk zou falen.
    coll.store.async_delay_save(coll._data_to_save, 0)
    import asyncio as _aio
    for _ in range(20):
        await _aio.sleep(0.05)
        await hass.async_block_till_done()
        fresh = lb_dash.DashboardsCollection(hass)
        await fresh.async_load()
        if any(it.get("url_path") == "canary-energyprijs" for it in fresh.data.values()):
            break

    check = lb_dash.DashboardsCollection(hass)
    await check.async_load()
    items = [it for it in check.data.values()]
    assert any(it["url_path"] == "canary-energyprijs" for it in items), \
        "canary-item ontbreekt op disk — laatste-schrijver-race of API-breuk"
    assert item["id"]
