"""Config-flow: installeert het stroomprijs-package bij het toevoegen via de UI."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = None  # geen velden — alles gebeurt automatisch


class EnergyprijsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Eén-klik flow: bij afronding het package installeren."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Toon een bevestigings-scherm en installeer bij bevestiging."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=None)

        # Idempotent: dubbele toevoeging voorkomen
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Package + configuration.yaml patchen bij het toevoegen
        from .installer import _ensure_packages_include, _write_package

        target = _write_package(self.hass)
        cfg_file = self.hass.config.path("configuration.yaml")
        from pathlib import Path

        changed, note = _ensure_packages_include(Path(cfg_file))
        _LOGGER.info("energyprijs config-flow: package=%s | cfg gewijzigd=%s | %s",
                     target, changed, note)

        return self.async_create_entry(title="Energyprijs", data={})

    async def async_step_import(self, import_config) -> ConfigFlowResult:
        """YAML-import (niet gebruikt, maar HA verwacht 'm soms)."""
        return await self.async_step_user()
