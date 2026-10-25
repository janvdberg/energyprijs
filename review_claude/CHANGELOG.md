## 2026-10-24 — v1.7.8: triggers + bevroren-daglijstcheck (review-opvolging Claude)

**Aanloop**: opvolging van de v1.7.7-review; drie open punten uit die review gesloten.

**Shadow (shadow.yaml)**
- Trigger-list status-sensor: `input_text.shadow_status_vorige` toegevoegd. De
  hysterese leest prev via `states()`; zonder trigger herberekende de sensor te
  laat na een prev-wijziging (hysterese-band liep achter).
- Bevroren-daglijstcheck: is het laatste verstreken kwartier ouder dan 45 min,
  dan is de daglijst niet meer vers (na middernacht bevat 'vandaag' anders de
  laatste prijs van gisteren). Status blijft `unavailable` — geen besluit op
  oude prijzen.

**Test**
- Nieuw: `test_bevroren_daglijst_geen_besluit` (60 min oude lijst → unavailable).
- P4-assert hysterese versoepeld naar `!= "LADEN"` (niet vastgezet op een
  specifieke ruststatus).

**Gedrag in productie (release-note)**
- Door de η-schrapping (v1.7.7) ligt de laadgrens ruimer (~factor 1/0,77 op de
  inkoopprijs): verwacht méér LADEN-kwartieren. Eerste dagen status-historie
  controleren op plausibel patroon.
- SOC-latch (wisselend besluit rond flor+2) staat nog open voor een volgende
  iteratie; veilig (onder flor blijft verkoop geblokkeerd) maar rommelig.

**Bewijs**: `pytest tests/ -q` → **84 passed, 0 failed**.

## 2026-10-24 — v1.7.7: η-laad schrapping (dubbel laadverlies) + test-fix scenario 4 + curtail-comment

**Review** (Claude, externe review-van 24 okt): de LADEN-tak `(in_nu / eta_laad) + w + m < V − H`
telt het laadverlies dubbel — `V` bevat al `η_rt = η_laad × η_ontlaad` (v1.6.2).
Daardoor was laden per kwartier systematisch te streng, en viel scenario 4 van de
huisreserve-test in het gat.

**Shadow (shadow.yaml)**
- LADEN-takken: `in_nu + w + m < V − H` / `< V + H` (hysterese-band). `/ eta_laad`
  weg; de onbereikte `eta_laad`/`eta_ontl`-vars uit V- en status-sensor verwijderd.
  η-fallback is nu automatisch consistent: de enige η is `eta_rt` met het
  `rend_ok`-contract (v1.5.5) en `shadow_eta`-noodvallet.
- Kopcommentaar status-sensor: curtail *is* een status (`ONTLADEN (curtail)`) —
  eerdere tekst zei "geen status maar attribute".

**Test (test_shadow_package.py)**
- Scenario 4 (goedkoop laden onder reserve): `_daglijst_attr(0.05, 0.05, 0.30, 0.30,
  dal=0.01)` → `_daglijst_piek_met_pv(0.05, 0.05, 0.30, 0.30)`. De oude fixture
  had geen spread (V = in_nu = 0,05), dus laden was verliesgevend en `OP HET NET`
  was correct. Met spread: V = 0,30 > in_nu 0,05 → LADEN, ook onder reserve.
- Hysterese-test opnieuw afgeleid zonder η-laad: V = 0,83 × 0,40 = 0,332,
  band (0,327 ; 0,337) → P1 0,295 NEUTRAAL, P2 0,285 LADEN, P3 0,292 LADEN
  (band), P4 0,30 uit LADEN.

**Niet mee opgenomen** (opmerking uit de review, voor een volgende iteratie):
- SOC-uitstapband (`band_uit` = `soc > flor + 2`): werkt niet als latching, want
  de geblokkeerde beslissing overschrijft `prev` zelf — bij SOC 21 wisselt het
  besluit per kwartier. Fix = aparte trigger-template-binary_sensor met
  `this.state`-latch vóór de status. Besproken, maar dit is gedragswijziging
  buiten het draad van deze fix.

**Bewijs**: volledige suite `pytest tests/ -q` → **83 passed, 0 failed**.

*wanneer/welke-review* staat hier.

## 2026-10-24 — v1.7.6: Shadow-huisreserve (flor-check) + test_hulpjes de deur uit

**Shadow (shadow.yaml)**
- Beslisketen krijgt de huisreserve-check die er al hoorde: `onder_reserve = soc_now < 0 or soc_now <= flor` (SOC via `sensor.accu_percentage`, grens via `input_number.shadow_soc_min`). Onder de reserve geen ONTLADEN en geen SPAAR — wel NEUTRAAL. Negatieve prijzen (curtail) gaan altijd door: dat is verplicht, geen keuze.
- Nieuwe test `test_shadow_huisreserve_blokkeert_ontladen`: verkoop onder reserve geblokkeerd, spaar onder reserve geblokkeerd, curtail wél door, boven reserve wél verkopen.

**Package (package.yaml)**
- `input_text.test_dagmodus` (test-only schakelaar uit v1.7.5) **verwijderd**. Die liet bij invullen van `vers` alle punten van een oude dag onder "morgen" renderen — ongewenst in een productiepackage.
- De datumfilter in `morgen_prognose` is nu weer ongeforseerd: alleen punten van morgen.
- Tests vriezen de klok in plaats daarvan (`freezegun`, autouse-fixture op een vaste `now`) — deterministisch, ook rond middernacht.

**Bewijs**: volledige suite `pytest tests/ -q` → **82 passed, 0 failed, 0 errors**.

## 2026-10-23 — v1.7.5: Jinja2-compat + daglijst-fallback robuust (tests groen)

HA 2026.10 acceptseert `max(default=-1)` niet meer als Jinja2-filter in de
reserve-template (`do_max() got an unexpected keyword argument 'default'`) →
vervangen door een conditionele max met count-check op de SOC-kandidatenlijst.

Daarnaast de daglijst-fallback-test productietrouw gemaakt: bron-entiteiten
dragen `prijs|vandaag-json|morgen-json` als state (gesplitst in de
bron-templates) i.p.v. handmatige input_text-zuivel; time_pattern-triggers
in tests geaccepteerd via `expected_lingering_timers`.

Volledige suite: 81 passed, 0 failed, 0 errors.

## 2026-10-21 — v1.7.4: status COMFORT → ONTLADEN (state én weergave)

Doorloop v1.7.3 (zelfde dag): die paste alleen de *weergave*
(`COMFORT (verkoop)`); de state-waarde 'COMFORT' bleef. Jan: prutswerk —
de statusnaam moet OVERAL hetzelfde zijn. Vastgelegde statusnamen van
2026-10-05 (`/opt/data/roi-monitor/accu_statusnamen.md`): de verkoop-band
heet **Ontladen**; 'Comfort' is óf Neutraal of Spaar. Dus de state-waarde
verandert definitief: COMFORT → ONTLADEN, COMFORT (curtail) → ONTLADEN
