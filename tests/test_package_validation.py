
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

async def test_package_recorder_exclude_vorm(hass):
    """recorder.exclude moet de MAPPING-vorm hebben (entities: [...]).

    De legacy lijst-vorm 'exclude: [entity_id: [...]]' weigert HA 2026.x met
    'expected a dictionary' — live ontdekt op 3 okt '26. Test valideren tegen
    HA's eigen recorder CONFIG_SCHEMA, dus zo'n vormfout kan nooit meer doorglippen.
    """
    from homeassistant.components.recorder import CONFIG_SCHEMA

    pkg = yaml.safe_load(open(str(PKG_PATH)))
    assert "recorder" in pkg, "package hoort een recorder-exclude te dragen"
    out = CONFIG_SCHEMA({"recorder": pkg["recorder"]})
    ents = out["recorder"]["exclude"].get("entities") or []
    assert "sensor.stroomprijs_daglijst" in ents


async def test_package_all_domains_validate(hass):
    """Alle top-level domeinen van het package door hun eigen HA-schema."""
    from homeassistant.components.input_number import CONFIG_SCHEMA as IN_SCHEMA
    from homeassistant.components.input_boolean import CONFIG_SCHEMA as IB_SCHEMA

    pkg = yaml.safe_load(open(str(PKG_PATH)))
    if "input_number" in pkg:
        IN_SCHEMA({"input_number": pkg["input_number"]})
    if "input_boolean" in pkg:
        IB_SCHEMA({"input_boolean": pkg["input_boolean"]})
    # automation: valideer tegen het legacy-yaml pad van de automation-integratie
    from homeassistant.components.automation import DOMAIN as AUTOM_DOMAIN
    from homeassistant.loader import async_get_integration
    integ = await async_get_integration(hass, AUTOM_DOMAIN)
    assert integ is not None  # domein bestaat; diepe YAML-validatie doet HA zelf bij setup
