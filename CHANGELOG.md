## 2026-11-11 — v1.9.3: shadow-beslisladder onder de huisreserve gecorrigeerd

**Aanleiding**: `test_shadow_huisreserve_is_apart_signaal_v190` bleef falen: bij
SOC 12 (onder flor 20), goedkope in-prijs 0,30 en dure toppen (V≈0,664) werd de
status `Spaar` in plaats van het verwachte vrije `Laden`.

**Oorzaak (bewezen via dump)**: de ladder had een Spaar-poort `in_reserve and
n_top <= 0`. Onder de reserve is het ontlaadbudget negatief (kwh_tot_reserve=0 →
n_top ≤ 0), dus die tak sneed élke laadbeslissing af — terwijl laden fysisch vrij
is en de reserve al als apart binair signaal (`binary_sensor.shadow_accu_blokkade`)
bestaat. Daarna bleek een tweede fout: de Ontladen-tak `uit_nu > v_eis + H` vuurde
ook onder de reserve, waar niets te ontladen valt.

**Oplossing** in custom_components/energyprijs/shadow/shadow.yaml:
- Spaar-poort op budgetloos geschrapt; de prijsregels beslissen nu vrij.
- Ontladen-taken krijgen `not in_reserve` (geen verkoop uit een lege accu).
- De hysterese-prev-tak `prev == 'Laden' … < g_laden_uit` staat vóór de
  beslisregels (dubbele exemplaren dedupliceerd).

**Gedrag**: onder de huisreserve blijft de status puur economisch (Laden/Neutraal/
Spaar op prijs); de blokkade voor ontladen blijft het aparte SOC-signaal.
Suite: 96 passed (tests/test_shadow_package.py + rest).

## 2026-11-11 — v1.9.2: helper-bewaking — verwijderde helpers blijven niet meer onzichtbaar

**Aanleiding**: `sync_package_if_changed` vergelijkt alleen de sha256 van het
package-bestand op disk met de ingebedde bron. Een per ongeluk verwijderde helper
wordt daardoor nóóit hersteld: het bestand is gelijk, dus de sync skip — terwijl de
live instanties verdwenen zijn. Precies dit verklaarde de "Shadow lukt niet"-klachten.

**Oplossing**: `controleer_helper_aanwezigheid(hass)` in installer.py:
- verzamelt alle helper-id's uit package.yaml + shadow/shadow.yaml (`_helper_ids_sync`),
- vergelijkt met de LIVE entity-registry,
- forceert bij afwezigheid het packageschrijven (`_forceer_package_herschrijf_sync`,
  omzeilt de hash-skip),
- maakt Repairs-issue `helpers_verwijderd` (NL/EN) met instructie HA te herstarten;
  issue verdwijnt automatisch zodra alles aanwezig is.
- Hook zit in `_sync_package_and_defaults()` → draait bij setup én bij elke update.

## 2026-11-05 — v1.9.0: shadow_status ontkoppeld van SOC — prijsstatus zuiver, reserve apart signaal

**Aanleiding**: in v1.8.x verstopte `sensor.shadow_status` twee dingen tegelijk:
de economische beslissing (prijzen vs. eis) én de accu-reserveband
(flor..flor+2). Daardoor was "Neutraal" soms "geen winst" en soms "reserve",
onverklaarbaar vanaf het dashboard. Ontkoppelen per besluit van oktober.

1. **`sensor.shadow_status` is nu een zuivere prijs-/economiestatus.** De
   beslis-logica zelf is ONVERANDERD (regression-test
   `test_shadow_beslissing_blijft_gedrag_v186_na_v190` bewijst het): de band
   blijft alleen via `Doorleveren`/R in de uitkomst, niet als eigen statuslabel.
2. **Vier gate-attributes op de status-sensor**: `verkoop_blokkade`,
   `spaar_blokkade`, `neutraal_vrij`, `in_reserve` — elk met zijn eigen
   volledige `{% set %}`-reeks in `>`-scalarstijl (consistent met `in_nu`/
   `uit_nu`). Het dashboard kan de blokkade nu verklaren zónder te gokken.
3. **Nieuwe `binary_sensor.shadow_accu_blokkade`** (`template.binary_sensor`,
   unique_id `energyprijs_shadow_accublokkade`): on wanneer de reserve een
   vers verkoop/spaar-besluit blokkeert. Fail-safe: onbekende SOC → on
   (nooit stille verkoop uit de reserve). Laden en curtail zijn NOOIT een
   blokkade — laden is juist hoe je boven de reserve komt, curtail is verplicht.
4. **Eenheid**: `unit_of_measurement: "prijsstatus"` zoals getipt faalt in de
   praktijk — HA's sensor-component weigert niet-numerieke states bij een
   eigenlijke eenheid (ValueError → state `unknown`, alle regression-tests rood).
   Oplossing: de eenheid staat als attribute `prijsstatus: "prijsstatus"` op de
   sensor; `unit_of_measurement` blijft afwezig. Test aangepast + commentaar.
5. **Top-level `binary_sensor:` naast `template:` faalt ook**: de core
   binary_sensor vraagt `platform:`. Template-binaire sensoren moeten ín
   `template:` staan — sectie daarheen verplaatst.

**Getest**: `tests/test_shadow_package.py` + `tests/test_shadow_yaml_valid.py`
— 23 passed. De 71 errors/1 failure in de rest van suite zijn pre-existing
(bewezen met `git stash`: 66 errors/1 failure op schone HEAD; +5 errors door
nieuwe testnamen).

## 2026-10-31 — v1.8.6: restpunten uit de v1.8.5-review (CI-lint, docs, curtail-keus)

**Aanleiding**: tweede review-rondje op v1.8.5 — geen nieuwe beslisbugs meer;
lint, verouderde tekst en één ontwerppunt dat een bewuste keuze verdient.

1. **CI-lint groen** (tests/): de acht ruff-F-vondsten in de testbestanden waren
   de oorzaak dat de CI-lintjob (exact `ruff check --select F` op `tests/`)
   faalde: ongebruikte `json`- en `timezone`-imports (test_voorspellingsbron,
   test_daglijst_bron_fallback, dubbele lokale `json`-import), de onbruikte
   `pt` in test_voorspellingsbron (F841 — de assertie op `morgen_prognose` was
   de bedoeling) en een ongebruikte `installer`-import in
   test_defaults_and_package. Ruff meldt nu 0 fouten over de hele repo.
2. **Verouderd commentaar** (shadow.yaml): de bevroren-lijst-check noemde nog
   "geen besluit (Neutraal)"; sinds v1.7.8 wordt de status `unavailable`.
3. **e2e-test eerlijker** (test_package_e2e_ha): de e2e-reservetest was al
   rood op v1.8.4 (pre-existing, bewezen met `git stash` op de oude HEAD).
   Gemeten oorzaak: de reserve-sensor hangt aan een keten van twee
   template-hops en de tweede herberekening valt na één `block_till_done`
   weg door HA's coalescing. De losse render van de templates zelf gaf
   True / 20.0 — de template is correct; de fix is een tijdstick na de
   tweede hop (testfixture-timing, geen productiewijziging).
4. **Cosmetica**: de versie-versie → versie, verwachtingen omdraaid →
   omgedraaid en de verhaspelde v1.8.4-zin in het CHANGELOG; de
   STATUS_MIGRATIE-commentaarblokken in installer.py samengevoegd boven de
   dict (stonden op kolom 0 midden in de dict).
5. **Curtail-keus vastgelegd** (shadow.yaml + nieuwe test):
   `Ontladen (curtail)` telt bewust NIET mee in de verkoop-hysterese —
   prev 'Ontladen (curtail)' ≠ 'Ontladen', dus direct na een curtail gelden
   de instapregels van een vers besluit (uit > verkoop-eis + H én
   SOC > flor + 2). Keuze: curtail is géén verkoop maar een verplichte
   export-limiet van de grid-operator; de reserveband (v1.8.5-flapperfix)
   bestaat precies om te voorkomen dat de verkoop bij SOC ≤ flor + 2 direct
   na zo'n dwang-event doorgaat. Vastgelegd met
   `test_shadow_curtail_geen_verkoop_hysterese_v186` (curtail gaat door op
   SOC 21, verkoop mag daar níét direct na instappen, bij SOC 23 wél).

## 2026-10-31 — v1.8.5: review-fixes op v1.8.4 (hysteresen, reserve-band, migratie, CI, docs)

**Aanleiding**: code-review (Claude) op de v1.8.4-stand: vijf echte bugs plus
documentatie- en opruimwerk. Beslislogica buiten de hieronder genoemde takken
onveranderd.

1. **Ontladen-hysterese hersteld** (shadow.yaml): de uit-tak had géén
   prev-eis en ving met `g_eis_uit = v_eis − H` alles op tot onder de
   instapdrempel `v_eis + H` — de instaptak was dode code en instappen
   gebeurde al op eis−H. Nu: instappen vereist `uit > v_eis + H`; blijven
   vereist `prev == 'Ontladen'` en `uit > v_eis − H`. Nieuwe test:
   `prev='Neutraal'` + `uit = v_eis` → Neutraal; `prev='Ontladen'` +
   dezelfde `uit` → Ontladen.
2. **Reserve-band omgekeerd** (shadow.yaml): `verkoop_blokkade = in_reserve or
   (prev == 'Ontladen' and not band_uit)` flopte elke tick rond de reserve
   (vers besluit vrij → volgende tick geblokkeerd → tick daarna weer vrij).
   Nu: instappen pas boven flor+2, blijven tot flor. `test_onder_reserve_model`
   verwachtingen omgedraaid; e2e-reservescenario stap 6 aangepast (21 → géén
   Ontladen, 23 → wél); nieuwe flapper-test: 4 ticks bij SOC 21 wisselen
   niet.
3. **Neutraal-bandbreedte écht gebouwd** (shadow.yaml): het CHANGELOG van
   v1.8.4 belooft flor..flor+2, maar de code gebruikte alleen `not
   in_reserve`. Nieuwe vlag `neutraal_vrij = soc_ok and (soc > flor+2 or
   (prev == 'Neutraal' and soc > flor))`; de verbruiksband-tak gebruikt die
   i.p.v. `not in_reserve`. Nieuwe test: SOC 21 met vers besluit → Spaar, met
   prev='Neutraal' → Neutraal, SOC 20 → altijd Spaar.
4. **Statusmigratie niet laten ketenen** (installer.py): `__init__.py` doet
   één lookup, dus `"SPAAR" → "Op het net"` kwam nooit bij "Doorleveren" uit;
   wie van ≤1.8.1 direct naar ≥1.8.3 ging, kreeg een ongeldige prev. Nu
   `"SPAAR" → "Doorleveren"` direct; `"Op het net" → "Doorleveren"` blijft
   staan voor 1.8.2-installaties. Nieuwe test: géén waarde in
   STATUS_MIGRATIE is zelf een sleutel, en alle waarden zijn geldige
   eindlabels.
5. **CI-lint** (ruff `--select F`): ongebruikte `from pathlib import Path`
   weg uit config_flow.py; ongebruikte `dt_util` /
   `async_fire_time_changed` weg uit test_voorspellingsbron.py. (Overige
   ruff-vondsten buiten het opdrachtvlak — `timezone`-imports,
   `import json`-duplicaten, F841 `pt` — zijn op de achtergrond; die raken
   geen test en geen beslislogica.)
6. **Documentatie en versie**: manifest 1.8.4 → 1.8.5; README-badge 1.6.2 →
   1.8.5; README-versiehistorie (stopte bij 1.6.2) vervangen door
   verwijzing naar CHANGELOG.md; Shadow-featurezin in de README-featuretabel
   in twee zinnen herschreven; commentaar bij de bevroren daglijst
   gecorrigeerd — bij een stagnerende daglijst wordt
   `sensor.shadow_status` 'unavailable', níét 'Neutraal' (de oude zin
   klopte niet met code én test); typo's: verkoopfallemaal → "verkoop-eis:
   alles", histore → historie, STATUS_HISTOIRE → STATUS_HISTORIE (overal
   tegelijk), zonnoverschot → zonoverschot.

**Vergeten v1.8.1** (26 okt '26, commit b33f2b2; geen release-page/tag):
review-fixes op v1.8.0 — `ns_mn` in morgen-template, vandaag-min (wm) in
morgen, lege-data guard (drem=-1), tmin-scan + negatieve-prijsdrempel
(simulatie-fix), plus `scripts/simuleer_v181.py` als simulatie-generiek.
De versie in manifest/README telde toen óók niet mee (de CAPS-/
manifest-mismatch die later in v1.8.2 werd opgeruimd).

## 2026-10-31 — v1.8.4: Neutraal is de VERBRUIKSBAND (accu voert het huis)

**Aanleiding**: Jan (31 okt '26): "Daar was eigenlijk de Neutraal-status ook voor
bedoeld — de stroomprijs is te duur om te laden maar te goedkoop om te verkopen,
ook rekening houdend met de efficiëntie." De code maakte er tot nu toe een passieve
rustband van (huis op net zolang in ≤ V+H), waardoor elke prijs tussen laad- en
verkoop-eis stil viel op Spaar — dure uren (bv. €0,48 's middags, top-12 's avonds
€0,50) werden nooit vermeden terwijl de accu 25% SOC had.

**Fix**: één nieuwe tak vóór het Spaar-vangnet in de beslisboom:
`in + w + m ≥ V + H` EN (`uit` onbekend of ≤ verkoop-eis + H) EN niet in reserve
→ **Neutraal** = ontladen voor eigen verbruik. η round-trip zit al in V
(top-n × η_rt) én in de verkoop-eis (herlaadkosten/η + w + m). Bandbreedte
flor..flor+2 tegen geflapper rond de reserve; onder flor blijft Spaar.
Spaar wordt het vangnet daarboven (uit boven de eis → wachten op de top).
Beslissingen-met-gekende-prijzen test aangepast + dedicated test
`test_shadow_neutraal_als_verbruiksband` (8/8 groen). cards.py-tekst en
accu_statusnamen.md band 3 bijgewerkt. Geen naamswijziging — geen
STATUS_MIGRATIE-regel nodig (prev 'Neutraal' blijft geldige hysterese-waarde).

## 2026-10-31 — v1.8.3: band 4 hernoemd "Op het net" → "Doorleveren"

**Aanleiding**: Jan's opmerking (31 okt '26) dat "op het net" te veel ruimte laat voor
verkeerde interpretatie — de accu staat bij deze band niet parallel aan het net; het
zonoverschot wordt doorgesluisd en de lading wordt gehouden.

**Fix**: alle code-labels, tests, README en kaarttekst hernoemd naar **Doorleveren**
(⚪ behouden). Beslislogica ONVERANDERD — alleen de naam.
STATUS_MIGRATIE krijgt een extra regel `"Op het net" → "Doorleveren"` zodat de
hysterese-historie van bestaande instanties meegaat. Documentatie (accu_statusnamen.md)
is apart aangepast.

## 2026-10-28 — v1.8.2: shadow-statusnamen gelijk aan de documentatie-banden

**Aanleiding**: Jan's swap van 28 okt (accu_statusnamen.md): 'Spaar' en 'Op het net'
wisselden van betekenis, en de ShadowPIES-labels (CAPS) weken af van de bandennamen.
Eis: "namen moeten overal in de code hetzelfde zijn".

**Fix**: alle shadow-statuslabels hernoemd naar de banden uit accu_statusnamen.md:
`LADEN→Laden`, `ONTLADEN→Ontladen`, `ONTLADEN (curtail)→Ontladen (curtail)`,
`NEUTRAAL→Neutraal`; én de inhoudswap: ruimtetak `SPAAR→Op het net` (lading houden,
band 4), else-vangnet `OP HET NET→Spaar` (goedkoopste rust, band 2). De beslislogica is
ONVERANDERD — alleen de labels. cards.py: kleurcodering nu 🟢🟡🔵⚪🔴 per documentatie.

**Volgschade**: hysterese-historie `input_text.shadow_status_vorige` bevat oude CAPS-
waarden → STATUS_MIGRATIE (installer.py) vertelt ze eenmalig; zonder die tabel missen
de hysterese-takken hun prev-waarde na de upgrade. Bestaande HA-instanties migreren
automatisch bij setup.
## 2026-10-26 — v1.8.0: laden-sein zonder vaste drempel (relatief per daglijst)

**Aanleiding**: Jan's kritiek (okt '26) dat het `s`-sein "nu laden" voorstelde terwijl
de goedkoopste uren later lagen. De oude regel vergeleek elk uur met een VASTE
helper-waarde (`prijs_laad_drempel`, €0,337) en had dus geen tijdsblik: dure uren
binnen een verder goedkope dag kregen óók 'laden'.

**Fix**: `input_number.prijs_laad_drempel` → `input_number.prijs_laad_fractie`
(× laagste all-in-uur van de betreffende lijst, default 1,25; prognose-blok 1,40).
De status wordt nu in een tweede pass ná de renderloop bepaald: minimum uit de lijst,
grens = fractie × minimum, comfort-grens blijft +€0,08. 'laden' betekent nu altijd
"dit uur hoort bij de goedkoopste van de dag".

**Volgschade**: helper heet anders (installer-default, __init__-lijst, e2e-/review-tests,
README). Bestaande installaties: vervang de helper via Settings → Helpers of laat de
package-update hem opnieuw aanmaken; de oude drempelwaarde is niet meer van toepassing.

## 2026-10-25 — v1.7.9: notify-doel-template robuust tegen unknown/unavailable helper

**Aanleiding**: HA-repair "unknown action notify.unknown" op
`automation.prijzen_meld_bronuitval`. De oude één-regel-vorm
`{{ 'notify.' ~ (states('input_text.prijs_notify_doel') or 'persistent_notification') }}`
valt alleen terug bij een LEGE helper. Staat de helper op `unknown`/`unavailable`
(rond herstart/update — precies toen de bronuitval-melding om 23:10 afging), dan is
`'unknown'` een niet-lege string → actie wordt `notify.unknown` → ServiceNotFound.

**Fix**: alle vier templated notify-doelen (package: prijzen_meld_bronuitval,
prijzen_meld_morgen_missing, prijzen_meld_nettoeslag_blokken; shadow:
energyprijs_shadow_log) naar:

```yaml
- action: >-
    {% set d = states('input_text.prijs_notify_doel') | trim %}
    {{ 'notify.' ~ (d if d not in ['', 'unknown', 'unavailable', 'none'] else 'persistent_notification') }}
```

Triggers en data-blokken ongewijzigd (`to: [unavailable, unknown]` + `for: 5 min` is bewust).

**Test**: nieuw `tests/test_notify_doel_robuust_v179.py` (opgenomen in de
pytest.ini-whitelist): geen enkele plaats mag nog de kwetsbare `or`-vorm bevatten;
elke notify-template moet trim + not-in-fallback hebben.

**Bewijs**: `pytest tests/ -q` → 86 passed, 1 failed (pre-existing:
test_package_e2e_ha faalt ook op schone HEAD — accu-snelkoppeling in test-venv).

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
