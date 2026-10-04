"""Config-flow: installeert het stroomprijs-package bij het toevoegen via de UI.

Patroon overgenomen van core-integraties met een confirm-only flow
(bijv. shelly/tasmota): async_show_form ZONDER data_schema-argument +
_set_confirm_only(). Een Formulier met data_schema=None is namelijk een
ongeldige staat waar de HA-frontend op crasht.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class EnergyprijsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Eén-klik flow: bij bevestigen het package installeren."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Toon een bevestigings-scherm en installeer bij bevestiging."""
        # Dubbele entry's voorkomen vóórdat er iets geschreven wordt
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is None:
            # Confirm-only formulier: géén data_schema meesturen (frontend
            # verwacht een lijst velden; None laat de dialoog crashen).
            self._set_confirm_only()
            return self.async_show_form(step_id="user")

        # Idempotent: unique id + abort als er al een entry/existing flow is
        await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        # Package synchroniseren + configuration.yaml controleren. Review
        # 4 okt '26: deze route importeerde _ensure_packages_include — die naam
        # bestond niet meer (ImportError, verzwolgen door de brede except →
        # abort 'install_failed'): UI-installatie faalde ALTIJD. Nu via de
        # veilige publieke routes: sync_package_if_changed (async, executor-correct)
        # en _packages_status_sync (read-only, schrijft nooit naar cfg).
        try:
            from pathlib import Path

            from .installer import _packages_status_sync, sync_package_if_changed

            pkg_changed = await sync_package_if_changed(self.hass)
            status, note = await self.hass.async_add_executor_job(
                _packages_status_sync, Path(self.hass.config.path("configuration.yaml"))
            )
            _LOGGER.info(
                "energyprijs config-flow: package_bijgewerkt=%s | cfg=%s | %s",
                pkg_changed, status, note,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("energyprijs: installeren mislukt")
            return self.async_abort(reason="install_failed")

        return self.async_create_entry(title="Energyprijs", data={})

    async def async_step_import(self, import_config) -> ConfigFlowResult:
        """YAML-import: direct aanmaken zonder bevestigingsscherm."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(DOMAIN, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Energyprijs", data={})
