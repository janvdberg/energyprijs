"""Review-punten v1.5.3 (okt '26) — tests bij de fixes.

Punt 1: het triggers-blok 'Prijzen bron Energyzero' rendert alleen bij HA-start
en een btw-helperwijziging. Een prijswijziging of uitval van de EnergyZero-bron
wordt dus NOOIT gezien: de sensor bevriest op de opstartwaarde.

Punt 2: dezelfde blok deelt door (1 + input_number.prijs_btw). De prijs die
EnergyZero levert bevat ALTIJD 21% btw (wettelijk vast); de contract-helper is
daarvoor de verkeerde noemer — met prijs_btw=0 ontstaat een valse kruiscontrole-
afwijking.

Punt 3: shadow.yaml had 'initial:' op de modelconstanten — dat schrijft bij elke
HA-herstart de tactiekwaarden terug over eigen instellingen heen. Defaults komen
nu éénmalig via HELPERS_DEFAULTS (IsDone-store), exact zoals het hoofdpackage.

Punt 4: notify-doelen waren hardcoded (mobile_app_telefoon_jan). Nu een
input_text-helper; README-doc meegenomen.

Punt 5: packages-status 'handmatig' gaf geen reparatiehint in de UI. Installer-
install én config-flow creëren nu een repair-issue met de plakinstructie.
"""
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
PKG_PATH = ROOT / "custom_components" / "energyprijs" / "package.yaml"
SHADOW_PATH = (ROOT / "custom_components" / "energyprijs"
               / "shadow" / "shadow.yaml")

EZ_SRC = "sensor.energyzero_today_energy_current_hour_price"
EZ_BRON = "sensor.prijzen_bron_energyzero"


async def _setup_pkg(hass):
    from homeassistant.setup import async_setup_component
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    assert await async_setup_component(hass, "template", {"template": pkg["template"]})
    for d in ("input_number", "input_text", "input_boolean"):
        if d in pkg:
            assert await async_setup_component(hass, d, {d: pkg[d]}), d
    await hass.async_block_till_done()
    return pkg


# ── Punt 1 + 2: EnergyZero-bron live + vaste wettelijke deler ──────────────


async def test_energiezero_bron_volgt_prijswijziging_live(hass):
    """Punt 1: een nieuwe uurprijs moet de bron-sensor direct laten meelopen."""
    await _setup_pkg(hass)
    hass.states.async_set(EZ_SRC, "0.3021")
    await hass.async_block_till_done()
    st = hass.states.get(EZ_BRON)
    assert st is not None and st.state != "unavailable"
    basis = float(st.state)
    assert abs(basis - 0.3021 / 1.21) < 1e-6, f"verkeerde deler: {basis}"

    # prijswijziging in de BRON, geen helper aangeraakt → moet volgen
    hass.states.async_set(EZ_SRC, "0.1200")
    await hass.async_block_till_done()
    st2 = hass.states.get(EZ_BRON)
    assert abs(float(st2.state) - 0.1200 / 1.21) < 1e-6, (
        f"bron bevroren op startwaarde ({st2.state} na wijziging naar 0.1200)")


async def test_energiezero_bron_ziet_uitval(hass):
    """Punt 1: availability moet ook zonder helperwijziging updaten."""
    await _setup_pkg(hass)
    hass.states.async_set(EZ_SRC, "0.3021")
    await hass.async_block_till_done()
    assert hass.states.get(EZ_BRON).state != "unavailable"

    hass.states.async_set(EZ_SRC, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(EZ_BRON).state == "unavailable", (
        "uitval van de bron wordt nooit gezien — trigger mist")


async def test_energiezero_bron_onafhankelijk_van_btw_helper(hass):
    """Punt 2: EnergyZero-prijzen bevatten wettelijk 21% btw; de contract-
    helper mag de deler niet veranderen (met 0 → valse kruiscontrole)."""
    await _setup_pkg(hass)
    hass.states.async_set(EZ_SRC, "0.2420")
    await hass.async_block_till_done()
    with_bt21 = float(hass.states.get(EZ_BRON).state)

    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.prijs_btw", "value": 0}, blocking=True)
    await hass.async_block_till_done()
    without_btw = float(hass.states.get(EZ_BRON).state)

    assert abs(with_bt21 - 0.20) < 1e-6, f"verwacht 0.2420/1.21=0.20, got {with_bt21}"
    assert abs(without_btw - 0.20) < 1e-6, (
        f"deler hangt aan de contract-helper ({without_btw}); moet constante 1.21 zijn")


# ── Punt 3: shadow-initials weg, defaults via installer ────────────────────


def test_shadow_geen_initial():
    """'initial:' zet bij ELKE HA-herstart de fabriekswaarde terug — verboden
    in een package wiens waarden de gebruiker zelf instelt (zelfde regel als
    package.yaml r.385)."""
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-8"))
    for domain in ("input_number", "input_text", "input_boolean"):
        for oid, cfg in (pkg.get(domain) or {}).items():
            assert "initial" not in cfg, f"{domain}.{oid} heeft nog 'initial:'"


def test_shadow_defaults_in_helpers_defaults():
    """De tactiek-startwaarden leven nu in HELPERS_DEFAULTS (éénmalige zet,
    IsDone-bewakend) — exact de getallen uit tactiek-revisie 3."""
    import sys
    sys.path.insert(0, str(ROOT))
    from custom_components.energyprijs import installer as inst
    for k, v in (("shadow_eta", 0.83), ("shadow_w", 0.025), ("shadow_m", 0.015),
                 ("shadow_n_top", 12), ("shadow_capaciteit", 92),
                 ("shadow_soc_min", 20), ("shadow_hysteresis", 0.005)):
        assert inst.HELPERS_DEFAULTS.get(k) == v, \
            f"{k} mist of verkeerd in HELPERS_DEFAULTS"


# ── Punt 4: notify-doel configureerbaar ────────────────────────────────────


def test_notify_doel_via_helper():
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    text_helpers = pkg.get("input_text", {})
    assert "prijs_notify_doel" in text_helpers, "input_text.prijs_notify_doel ontbreekt"
    raw = PKG_PATH.read_text(encoding="utf-8")
    assert "notify.mobile_app_telefoon_jan" not in raw, \
        "hardcoded persoonlijk notify-doel staat nog in het package"
    assert "states('input_text.prijs_notify_doel')" in raw


def test_readme_notify_doc_klopt():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "prijs_notify_doel" in readme, \
        "README meldt nog niet hoe het notify-doel aan te passen"


# ── Punt 5: repair-issue bij 'handmatig' ───────────────────────────────────


async def test_install_creëert_handmatig_issue(hass, tmp_path):
    """configuration.yaml zónder packages-include → status 'handmatig' →
    er móét een repair-issue verschijnen met de plakinstructie."""
    import custom_components.energyprijs.installer as inst
    from homeassistant.helpers import issue_registry as ir

    cfg = tmp_path / "configuration.yaml"
    cfg.write_text("default_config:\n", encoding="utf-8")

    async def fake_sync(h):
        return False

    with patch.object(inst, "_config_dir", lambda h: tmp_path), \
         patch.object(inst, "sync_package_if_changed", side_effect=fake_sync), \
         patch.object(inst, "_dashboard_opslaan", side_effect=RuntimeError("nvt")), \
         patch.object(inst, "_ensure_helper_defaults", return_value=False):
        await inst.async_register_services(hass)
        res = await hass.services.async_call(
            "energyprijs", "install", {}, blocking=True, return_response=True)

    assert res["configuration_yaml_status"] == "handmatig"
    issues = ir.async_get(hass).issues
    key = ("energyprijs", "packages_include_handmatig")
    assert key in issues, f"geen repair-issue bij handmatige status: {list(issues)}"
    assert "homeassistant:" in issues[key].translation_placeholders["toelichting"]


async def test_config_flow_creëert_handmatig_issue(hass, enable_custom_integrations, tmp_path):
    """De UI-flow mag niet stilzwijgend slagen bij 'handmatig'."""
    import custom_components.energyprijs.installer as inst
    from homeassistant import data_entry_flow
    from homeassistant.helpers import issue_registry as ir

    cfg = tmp_path / "configuration.yaml"
    cfg.write_text("logger:\n", encoding="utf-8")

    async def fake_sync(h):
        return False

    with patch.object(inst, "_config_dir", lambda h: tmp_path), \
         patch.object(inst, "sync_package_if_changed", side_effect=fake_sync):
        result = await hass.config_entries.flow.async_init(
            "energyprijs", context={"source": "user"})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={})

    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    key = ("energyprijs", "packages_include_handmatig")
    assert key in ir.async_get(hass).issues, \
        "config-flow eindigt success zonder repair-issue bij 'handmatig'"
