# Review-opdracht voor Claude — Shadow LADEN-tak faalt onder η-contract

## Context (in one sentence)
Een Home Assistant YAML-template-package (`shadow.yaml`, "Shadow handel": beslist per kwartier LADEN / OP HET NET / NEUTRAAL / SPAAR / ONTLADEN op basis van EPEX-prijzen en een Deye-accu) heeft één falende test: **scenario 4 van `test_shadow_huisreserve_blokkeert_ontladen`** — verwacht `LADEN`, krijgt `OP HET NET`.

## Het productprincipe (mag niet gebroken worden)
Onder de huisreserve (SOC ≤ `shadow_soc_min`) mag **nooit** ONTLADEN of SPAAR plaatsvinden, maar **LADEN wordt níét geblokkeerd**: goedkoop laden is juist de manier om boven de reserve te komen. Zie commentaar in `shadow.yaml` ter hoogte van de huisreserve-check.

## Wat er misgaat — exacte observatie

De beslissingstak in `shadow.yaml` (state-template van `sensor.shadow_status`):

```jinja
{% set eta_laad = states('input_number.rendement_laad_pct') | float(77) / 100 %}
...
{%- elif prev == 'LADEN' and (nu2.in_nu / eta_laad) + w + m < g_laden_uit %}{% set besluit.s = 'LADEN' %}
{%- elif (nu2.in_nu / eta_laad) + w + m < g_laden %}{% set besluit.s = 'LADEN' %}
```

met `g_laden = V - H` en `H = shadow_hysteresis` (default 0,005).

In de test-setup (fixture overschrijft waarden via `input_number.set_value` en `hass.states.async_set`):

- `shadow_w = 0`, `shadow_m = 0`, `shadow_eta = 1` (noodvallet)
- daglijst: `in_nu = 0,05`, `dal = 0,01` → `V` (sensor `shadow_v_waarde_opgeslagen_kwh`) = **0,05**
- gemeten rendements-helpers `input_number.rendement_laad_pct` / `_ontlaad_pct` bestaan **niet** in deze fixture

Gemeten via debug-dump (`/tmp/dbgout.txt`, reproduceerbaar):

```
DBG sensor.shadow_status = OP HET NET
DBG sensor.shadow_v_waarde_opgeslagen_kwh = 0.05
DBG input_number.rendement_laad_pct = BESTAAT NIET
DBG input_number.shadow_eta = 1
DBG input_number.shadow_w = 0
DBG input_number.shadow_m = 0
DBG input_number.shadow_hysteresis = 0.005
```

Berekening: `eta_laad` valt stil terug op de `float(77)`-fallback → lhs = `0,05 / 0,77 + 0 + 0 ≈ 0,0649`; rhs = `V − H = 0,045`. `0,0649 < 0,045` is false → geen LADEN. De sensor eindigt in `OP HET NET` want `in_nu (0,05) > g_laden (0,045)`.

**Zelfs met η_rt = 1** (zoals de test bedoelt via `shadow_eta = 1`) zou lhs = `0,05` zijn, nog steeds ≥ `V − H = 0,045` door de hysterese-marge — dus ook dan geen LADEN bij gelijke prijs.

## De twee problemen die wij zien (jullie mogen het anders zien!)

1. **η-fallback inconsistent.** `eta_rt` respecteert het contract: als de gemeten helpers ontbreken (`rend_ok` false) valt het terug op `input_number.shadow_eta` (hier op 1 gezet). Maar `eta_laad` kent dat contract niet: `states(...) | float(77)/100` zwiĳgt naar 0,77 terwijl η elders op 1 staat. Daardoor gebruikt de LADEN-tak een andere η dan de V-grens waar hij tegen rekent.

2. **De vergelijking kan nooit raak zijn bij gelijke prijs.** LADEN-eis is `(in/η_laad) + w + m < V − H`. Bij η_laad = 1, w = m = 0 wordt dit `in < V − H`: laden tegen precies de V-prijs is per definitie onmogelijk, en de hysterese maakt het nog scherper. Voor het principe "goedkoop laden is vrij" lijkt dat te streng — of moet de hysterese aan de linkerkant, of moet er een expliciete vrijstelling komen.

## Vraag aan Claude

Wat is de correcte, minimale fix in `shadow.yaml` zodat:

- scenario 4 (`in_nu = 0,05`, `dal = 0,01`, `w = m = 0`, η-fallback op `shadow_eta = 1`) → **LADEN** geeft;
- de bestaande hysterese- en blokkade-tests (scenario's 1–3 en 5, plus `test_shadow_hysterese_laden` en de curtail-/ruimte-taktests in dezelfde file) **groen blijven**;
- het productprincipe intact blijft: onder reserve geen verkoop/spaar, wel vrijheid om goedkoop te laden;
- het η-contract (v1.5.5) consistent wordt: η in de LADEN-tak via hetzelfde `rend_ok`-contract als `eta_rt`, met fallback op `shadow_eta`.

Opties die wij al overwogen (red ze of verbeter ze):

- A: `eta_laad` laten terugvallen op `sqrt(shadow_eta)` of op `shadow_eta` zelf als `rend_ok` false is.
- B: de LADEN-tak een vrijstelling geven wanneer `in_nu <= V` (prijs-kant) i.p.v. `in/η + w + m < V − H`.
- C: hysterese aan de lhs optellen i.p.v. de rhs te verlagen.

Geef een concrete Jinja-patch (diff-stijl) op `shadow.yaml`, en zeg erbij of de test-verwachting zelf (`assert st.state == "LADEN"` bij `in_nu == V`) billijk is of dat de test aangepast moet worden.

## Bestanden in deze map

| Bestand | Rol |
|---|---|
| `shadow.yaml` | Het package (template-sensors + input_* + automation). Beslissingstak ~regel 286–330; η-contract ~regel 145–152. |
| `test_shadow_package.py` | E2E-test via HA's eigen template-component. Falende test: `test_shadow_huisreserve_blokkeert_ontladen`, scenario 4 (~regel 276–285). |
| `installer.py` | Beheert `HELPERS_DEFAULTS` (o.a. `shadow_eta: 0.83`, `rendement_laad_pct: 77.0`). |
| `CHANGELOG.md` | Versiehistorie; relevant: v1.5.5 (η-contract), v1.5.2 (hysterese), v1.7.6 (huisreserve toegevoegd). |

## Reproductie

```bash
cd <repo-root>   # energyprijs-hacs
.venv/bin/python -m pytest tests/test_shadow_package.py::test_shadow_huisreserve_blokkeert_ontladen -q
# → AssertionError: goedkoop laden moet vrij zijn, got OP HET NET (regel 285)
```

Volledige suite: 82 passed, 1 failed (deze).
