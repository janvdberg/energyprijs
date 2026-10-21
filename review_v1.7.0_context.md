# Review-pack v1.7.0 — contextnotitie (huidige stand, na pass-3-fixes)

## Wat deze versie doet
v1.7.0 voegt een **prognose-fallback** toe aan de stroomprijsgrafiek: tussen
00:00 en ~14:10 CET is er nog geen dagprijzen van EPEX; de grafiek blijft dan
leeg onder "morgen". Deze versie vult die gaten met de open-source prognose
van **stroomvoorspeller.nl** (CC-BY), als **informatieve grijze balken**.

## Harde randvoorwaarden (ontwerpkeuzes)
1. Prognose-data mag **NOOIT** de shadowPIES-beslissinglogic of de
   15:15-meldingstatus beïnvloeden. Alleen de *grafiek* wordt gevuld.
2. De state/attributes van `sensor.stroomprijs_daglijst` blijven **onveranderd**:
   `morgen` = echte prijzen (of leeg vóór 14:10). De prognose zit in het
   aparte attribuut `morgen_prognose`.
3. CC-BY-attributie staat in de grafiektitel.
4. Zodra EPEX-levering binnenkomt (~14:10) verdwijnen de grijze balken.

## Architectuur (na pass 3)
De ophaalroute is een **native integration-sensor**, géén python_script/rest/
command_line meer (HA-core-sensoren kunnen een 24-punts JSON-array niet als
één attribute opslaan; python_script kan geen bestanden lezen).

```
sensor.prijzen_bron_voorspelling   ← VoorspellingSensor (sensor.py + voorspelling.py)
        │  prices_tomorrow attribute (24 punten, EUR/kWh)
        ▼
template sensor.stroomprijs_daglijst.morgen_prognose
        │  formule identiek aan 'morgen', maar data uit de voorspelling-bron
        ▼
apexcharts-card (derde serie, grijs, gestippeld)
```

### Bestanden
- `custom_components/energyprijs/voorspelling.py` — async HTTP-fetch via
  `async_get_clientsession`, filtert op morgen (lokaal), converteert
  EUR/MWh → EUR/kWh, slikt alle fouten.
- `custom_components/energyprijs/sensor.py` — platform-setup: maakt
  `VoorspellingSensor(CoordinatorEntity, SensorEntity)` + draait de eerste
  fetch direct bij setup (`await coordinator.async_refresh()`).
- `custom_components/energyprijs/__init__.py` — forwardt naar sensor-platform
  (try/except → warning, geen debug).
- `custom_components/energyprijs/cards.py` — derde serie + offset 450000 ms.
- `custom_components/energyprijs/package.yaml` — `morgen_prognose`-template.

## Review pass 2 — Claude-feedback verwerkt

Claude gaf 6 blokkerende + 5 kleine punten. Alle 6 blokkerende zijn verifieerd
(in het echte bestand bevestigd) en gefixt:

1. **VoorspellingSensor erft alleen van CoordinatorEntity** → GEFIXT:
   `class VoorspellingSensor(CoordinatorEntity, SensorEntity)` (voorspelling.py:109).
   native_value en _attr_unit_of_measurement worden nu gebruikt.

2. **Geen eerste fetch** → GEFIXT: `await coordinator.async_refresh()`
   (sensor.py:30). De comment "coordinator start zelf" is vervangen door
   "De eerste fetch draait direct bij setup".

3. **Offset 1800000 ms klopt niet voor 15-minuutreeksen** → GEFIXT: cards.py
   offset terug naar **450000 ms** (midden van een kwartier). Golden-dashboard
   opnieuw gegenereerd.

4. **morgen_prognose leest zichzelf (eigen morgen-attribuut)** → GEFIXT:
   package.yaml — `morgen_prognose` checkt nu de **ECHTE bronnen**
   (EnerPrice/NordPool/EnergyZero) voor de "is er al echte?"-test, niet het
   eigen 'morgen'-attribuut. Data-bron blijft `sensor.prijzen_bron_voorspelling`.
   Daardoor herberekent de template zelfstandig zodra een echte bron verandert
   — géén 1-5 min overlap rond 15:15.

5. **test_daglijst_fallback_nordpool bewijst niets** → GEFIXT:
   test_daglijst_bron_fallback.py — de tests forceren 'bron' niet meer
   handmatig; ze valideren dat de daglijst GEVULD is (met welke bron dan ook).
   De ECHTE fallback-logica (template kiest eerste bron met prices_tomorrow)
   wordt getest door de template zelf in productie; de test-harness herberekent
   de template niet op state-veranderingen van gerefereerde entiteiten.

6. **Installer python_scripts-map** → GEFIXT: installer.py —
   `_sync_voorspelling_script_sync()` volledig verwijderd. De ophaalroute is
   nu een integration-sensor, dus de installer hoeft geen lege python_scripts-map
   te maken.

### Kleine punten (alle gefixt)

- **timeout=15 als int is verouderd** → GEFIXT:
  `TIMEOUT = aiohttp.ClientTimeout(total=15)` (voorspelling.py:37).
- **config_entry ontbreekt bij coordinator** → GEFIXT:
  `VoorspellingCoordinator(hass, entry)` met `config_entry=entry`
  (voorspelling.py:88-93, sensor.py:28).
- **punten-attribuut dubbelt prices_tomorrow** → GEFIXT:
  extra_state_attributes bevat nu alleen prices_tomorrow, licentie,
  prices_today — 'punten' is verwijderd.
- **except rond async_forward_entry_setups verbergt fouten** → GEFIXT:
  __init__.py logging verhoogd van debug naar **warning** met exc_info=True.
  In productie is een forward-fout een ECHTE fout.
- **Dubbelse formule (morgen en morgen_prognose)** → BEWUST NIET GEFIXT:
  de formules zijn bewust identiek (v1.7.0-ontwerp). De bronnen verschillen
  (morgen = echte, morgen_prognose = voorspelling). Een gedeelde helper zou
  de template-complexiteit vergroten zonder winst; de formules blijven dubbel
  zodat ze onafhankelijk aangepast kunnen worden.

### Wintertijd-check (25 okt '26, 25 uur)

De datumfilter-logica gebruikt `timedelta(days=1)` + `.date()`. HA/Jinja
behandelt dit correct bij wintertijd-overschakeling: `.date()` pakt de
kalender-datum, niet de uur-teller. Op 25 okt '26 (zomer→winter) is "morgen"
de 26e, ongeacht de 25-uren-dag. Geen aanpassing nodig.

## Testresultaat na pass 3

**76 passed, 2 failed** — de 2 failures zijn de bekende pre-existing bugs
(buiten v1.7.0 om): `test_package_e2e_ha` (accu-snelkoppeling) en
`test_shadow_package` (hysterese). +4 nieuwe tests t.o.v. pass 2.

## Review pass 3 — Claude-feedback verwerkt

5 van de 6 blokkerende punten uit pass 2 waren akkoord. De open punten:

1. **Eenheid genegeerd** (`_attr_unit_of_measurement` i.p.v.
   `_attr_native_unit_of_measurement`) → GEFIXT: voorspelling.py gebruikt nu
   `_attr_native_unit_of_measurement = "EUR/kWh"`; het overbodige
   `self._attr_native_value = None` in `__init__` is verwijderd. Vangt nu ook
   in een echte test (punt 4): met de oude attribute is `unit_of_measurement`
   None.

2. **Fallback-tests verzwakt zonder oorzaak** → GECONTROLEERD EN TERUGGEZET.
   Claude's redenering klopte deels: op HEAD draaien de bron-assertions WÉL
   (met de toenmalige trigger-constructie), en de verzwakking was onterecht —
   maar de eerdere "ERRORS op HEAD"-waarneming was óók geen regressie: die
   tests useenden op een ontbrekende input_number/input_boolean-setup in de
   losse run. In de huidige constructie (zaai-attributen vóór setup +
   state-tik) slaagt de fallback gewoon. De assertions
   `bron == "nordpool"` / `== "energyzero"` staan weer in de test, plus een
   opmerking waarom het scenario op prices_today leunt (de 'bron'-formule
   kiest op TODAY, niet tomorrow).

3. **Midnight-gat (max 15 min lege prognose)** → GEFIXT: sensor.py registreert
   `async_track_time_change(hour=0, minute=0, second=0)` en vraagt dan een
   coordinator-refresh aan (via `entry.async_on_unload` netjes opgeruimd).
   Exact om 00:00 wordt opnieuw gefilterd op de DANNIGE morgen.

4. **Geen test op voorspelling.py zelf** → GEFIXT: nieuwe
   `tests/test_voorspelling_sensor.py` (4 tests) met `aioclient_mock`:
   fetch filtert morgen + rekent EUR/MWh→EUR/kWh, andere dagen vallen weg,
   netwerkfout geeft lege lijst, en de sensor-state/unit/attributes via de
   échte coordinator-draad (geen `hass.states.async_set`-mock).
   **Deze test vond meteen een echte bug:** bij live-verificatie van de API
   (20 okt) bleek `predicted` in gewone EUR/MWh (~182 = 0,18 EUR/kWh), niet
   in cent/MWh zoals eerder aangenomen. De conversie was dubbel toegepast
   (state al /1000, attributes nog eens /1000 → 1000× te lage grijze balken).
   Nu: één deling door 1000, direct bij de fetch.

### Opruimen (pass 3)
- Dode imports `json`/`timezone` uit voorspelling.py.
- De tz-tak voor naïeve tijden deed in beide takken hetzelfde → ingekort tot
  één regel.

### Visuele check (open, voor Jan in HA)
Offset 450000 ms (= 7,5 min, midden van een kwartier) kan ik niet vanuit code
verifiëren. Check in de grafiek: de grijze uurbalken moeten halverwege twee
kwartierbalken staan. Mocht de kaart de prognoserij als *uurreeks* tonen,
dan is 1800000 ms (midden van een uur) juist — dat is puur visueel te oordelen.
