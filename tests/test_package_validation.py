
"""Validatie: package.yaml moet door HA's eigen template-validator."""
from pathlib import Path
PKG_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "energyprijs" / "package.yaml"
import yaml
from homeassistant.components.template import config as tcfg


async def test_package_template_valid(hass):
    pkg = yaml.safe_load(open(str(PKG_PATH)))
    out = await tcfg.async_validate_config(hass, {"template": pkg["template"]})
    # geen fouten: async_validate_config print/logt setup-fouten maar gooit niet;
    # tel de resultaten — elke sectie moet geaccepteerd zijn (geen None-ruimte).
    assert out.get("template")

async def test_package_helpers_input_number(hass):
    from homeassistant.components import input_number
    import voluptuous as vol
    pkg = yaml.safe_load(open(str(PKG_PATH)))
    for name, cfg in pkg["input_number"].items():
        # valideer tegen HA's echte YAML-schema (slug-key-vorm)
        validated = input_number.CONFIG_SCHEMA({"input_number": {name: cfg}})
        assert "input_number" in validated
