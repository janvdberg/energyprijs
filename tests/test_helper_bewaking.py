"""v1.9.2: helper-bewaking — een verwijderde helper mag niet onzichtbaar blijven.

Achtergrond: sync_package_if_changed skip op gelijke sha256 tussen disk-package en
ingebedde bron. Een handmatig uit de registry verwijderde helper blijft dan weg ook
na een update. controleer_helper_aanwezigheid() vergelijkt daarom de definities met
de LIVE registry, forceert packageschrijven bij afwezigheid en maakt een
Repairs-issue 'helpers_verwijderd' aan (instructie: herstart HA).

Eisen, één test per eis:
  1. alles aanwezig → geen ontbrekende id's, geen issue.
  2. helper uit registry verwijderd → gemeld + issue met aantal/namen + package
     staat op disk gelijk aan de ingebedde bron.
  3. hersteltijd: opnieuw controleren nadat de helper teruggaat → lijst leeg EN
     issue opgeruimd.
"""
import shutil
from pathlib import Path

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir


def _issue(hass):
    return ir.async_get(hass).async_get_issue("energyprijs", "helpers_verwijderd")

import custom_components.energyprijs.installer as inst


def _kopieer_packages_naar_disk(hass):
    """Zet beide package-bestanden naar de tijdelijke hass-config-dir."""
    bron_dir = Path(inst.__file__).parent
    pkg_dir = Path(hass.config.path("packages"))
    pkg_dir.mkdir(parents=True, exist_ok=True)
    for best in (bron_dir / "package.yaml", bron_dir / "shadow" / "shadow.yaml"):
        shutil.copy(best, pkg_dir / best.name)


def _schrijf_verkeerd_package(hass):
    """Disk-package wijkt af van de bron → de forceer-sync MOET het herstellen."""
    pad = Path(hass.config.path("packages")) / "energyprijs.yaml"
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text("# verouderd package zonder helpers\n", encoding="utf-8")


def _zaai_alle_helpers(hass):
    """Registreer elke door de packages gedefinieerde helper in de registry."""
    ent_reg = er.async_get(hass)
    for eid in inst._helper_ids_sync():
        domein, object_id = eid.split(".", 1)
        ent_reg.async_get_or_create(domein, "energyprijs", object_id,
                                    suggested_object_id=object_id)


async def test_alles_aanwezig_geen_issue(hass):
    _kopieer_packages_naar_disk(hass)
    _zaai_alle_helpers(hass)
    ontb = await inst.controleer_helper_aanwezigheid(hass)
    assert ontb == []
    assert _issue(hass) is None


async def test_verwijderde_helper_wordt_gemeld_en_package_hersteld(hass):
    _schrijf_verkeerd_package(hass)
    _zaai_alle_helpers(hass)
    ent_reg = er.async_get(hass)
    ids = inst._helper_ids_sync()
    assert ids, "geen helpers gevonden in de package-bron — test kan niets bewijzen"
    doel = next((e for e in ids if e.startswith("input_number.")), ids[0])
    ent_reg.async_remove(doel)

    ontb = await inst.controleer_helper_aanwezigheid(hass)
    assert ontb == [doel], f"verwacht [{doel}], kreeg {ontb}"

    issue = _issue(hass)
    assert issue is not None, "geen Repairs-issue aangemaakt"
    assert issue.translation_placeholders["aantal"] == "1"
    assert doel in issue.translation_placeholders["helpers"]

    # geforceerd packageschrijven: disk == ingebedde bron
    geschreven = Path(hass.config.path("packages")) / "energyprijs.yaml"
    bron = Path(inst.__file__).parent / "package.yaml"
    assert geschreven.read_bytes() == bron.read_bytes(), \
        "package niet teruggezet naar de bron ondanks ontbrekende helper"


async def test_herstel_schoont_issue_op(hass):
    _kopieer_packages_naar_disk(hass)
    _zaai_alle_helpers(hass)
    ent_reg = er.async_get(hass)
    doel = inst._helper_ids_sync()[0]
    ent_reg.async_remove(doel)

    ontb = await inst.controleer_helper_aanwezigheid(hass)
    assert ontb == [doel]
    assert _issue(hass) is not None

    # herstel: helper terug in de registry (nabootsen van een HA-herstart die het
    # package herlaadt) → volgende check meldt leeg én ruimt het issue op
    domein, object_id = doel.split(".", 1)
    ent_reg.async_get_or_create(domein, "energyprijs", object_id,
                                suggested_object_id=object_id)
    ontb2 = await inst.controleer_helper_aanwezigheid(hass)
    assert ontb2 == []
    assert _issue(hass) is None
