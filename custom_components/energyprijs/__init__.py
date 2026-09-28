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
