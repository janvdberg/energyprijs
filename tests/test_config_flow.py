"""Config-flow-tests — review 4 okt '26 punt 1.

De flow importeerde _ensure_packages_include — die naam bestond niet meer
(ImportError, verzwolgen door de brede except → abort 'install_failed'):
toevoegen via de UI faalde ALTIJD en geen enkele test ving dat op.
"""
from unittest.mock import patch

from homeassistant import data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_user_flow_aanmaken_succes(hass, enable_custom_integrations, tmp_path):
    """Bevestigen in de UI moet een entry opleveren — geen install_failed."""
    import custom_components.energyprijs.installer as inst

    async def fake_sync(h):
        return False

    with patch.object(inst, "_config_dir", lambda h: tmp_path), \
         patch.object(inst, "sync_package_if_changed", side_effect=fake_sync):
        result = await hass.config_entries.flow.async_init(
            "energyprijs", context={"source": "user"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY, \
            f"flow faalde: {result2}"
        assert result2["title"] == "Energyprijs"


async def test_user_flow_abort_bij_bestaande_entry(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "energyprijs", context={"source": "user"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"
