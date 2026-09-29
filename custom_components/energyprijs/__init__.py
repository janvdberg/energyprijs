"""Energyprijs — installer-integratie.

Schrijft het stroomprijs-package naar /config/packages/ en bewaakt
configuration.yaml op de packages-include. Zelf geen entiteiten.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .installer import async_register_services

DOMAIN = "energyprijs"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registreer de installatieservices."""
    await async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """De config-flow heeft het package al weggeschreven; alleen services bevestigen.

    De integratie beheert zelf geen entiteiten — alle logica zit in het
    YAML-package. Dit bestaat alleen zodat HA de entry niet als fout markeert
    (HA vereist async_setup_entry zodra er een config-entry bestaat).
    """
    await async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Nothing to unload — we own no platforms."""
    return True
