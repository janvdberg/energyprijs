![HA](https://img.shields.io/badge/Home%20Assistant-2026.x-blue?logo=homeassistant)
![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-orange?logo=hackthebox)
![versie](https://img.shields.io/badge/versie-1.5.1-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

# ⚡ Energyprijs

**Eén klik (of één service-call) plant het complete dynamische-stroomprijs-package in Home Assistant.**

| Wat je krijgt | Details |
|---|---|
| 🔀 3 bronnen, kruiscontrole | Nord Pool · EnerPrice · EnergyZero — basisprijs faalt als <2 bronnen vers zijn |
| 📊 Bruto daglijst (15 min) | Direct grafiekklaar voor ApexCharts-card, vandaag + morgen |
| 💶 All-in formules | Afname/levering via instelbare velden: btw, energiebelasting, opslagen |
| 🔔 Meldingen | Automatisch bij bronuitval, spreiding of ontbrekende morgenprijzen |
| 🗓️ 2027-bestendig | Saldering vervalt 1-1-2027 → één schakelaar om, formules passen zichzelf aan |
| 🔋 Shadow tactiek (v1.5.1) | Regime-vrije accuhandel: 5 statussen (LADEN · NEUTRAAL · OP HET NET · SPAAR · COMFORT) op zonvenster van `sun.sun`, PV-ruimte en PV-herlaad-eis — meedraait in shadow-mode naast G1–G4 |

## Installatie

### Stap 0 — Integratie toevoegen (UI, één klik)

Ga naar **Instellingen → Apparaten en services → Integratie toevoegen → "Energyprijs"**
en bevestig. Het config-flow plant daarna zelf het package + de contract-helpers
(geen service-aanroep nodig). Na één HA-herstart zijn alle sensoren en helpers aanwezig.

> Wil je liever de service-route (bv. vóór herstart), dan is **Stap 2** de aanroep.

### Stap 1 — HACS
1. **HACS → ⋮ → Custom repositories → Add repository**
   - Repository: `janvdberg/energyprijs` (of de URL van deze repo)
   - Category: **Integration**
2. Zoek **Energyprijs** → **Download**
3. **Herstart Home Assistant**

### Stap 2 — Installeren
Developer Tools → Actions (Service):

```yaml
action: energyprijs.install
data: {}
```

De installer doet dan automatisch:

| # | Actie | Veiligheid |
|---|---|---|
| 1 | Package (re)schrijven naar `/config/packages/energyprijs.yaml` | Overschrijft alleen dit bestand |
| 2 | Controleren of de package wordt geladen (status `ok` / `ui_only` / `handmatig`) | configuration.yaml wordt **nooit** herschreven — bij `handmatig` volgt een plakinstructie |
| 3 | Melden dat herstart nodig is | Forceert niets — jij kiest het moment |

Optioneel: `force_restart: true` meesturen als je de herstart meteen wilt.

### Stap 3 — Controleren

```yaml
action: energyprijs.status
```

Toont of package + include aanwezig zijn.

## Voorwaarden

De package gebruikt sensoren van integraties die al geïnstalleerd moeten zijn —
**minstens één** prijsbron is vereist, zonder bron blijven de sensoren `unavailable`:

- **Nord Pool** (core-integratie)
- **EnerPrice** (HACS: `LenFaki/home-assistant-nl-day-ahead-prices`) — zet *extended attributes* aan in de opties (aanbevolen)
- **EnergyZero** (core-integratie)
- Een notify-service genaamd `notify.home` (anders de naam in het package aanpassen)

> De basisprijs vereist **twee** verse bronnen (kruiscontrole); met één bron
> blijft de daglijst beschikbaar maar wordt de basis unavailable. Heb je alleen
> Zonneplan-forecast draaien? Voeg dan Nord Pool óf EnergyZero toe
> (beide core-integraties, twee klikken).

## Entiteiten na installatie

```
sensor.prijzen_bron_nordpool          sensor.stroomprijs_basis
sensor.prijzen_bron_enerprice         sensor.stroomprijs_daglijst
sensor.prijzen_bron_energyzero        sensor.stroomprijs_afname
                                    sensor.stroomprijs_levering
binary_sensor.prijzen_kruiscontrole_afwijking
binary_sensor.prijzen_morgen_beschikbaar
input_number.prijs_btw / _energiebelasting / _opslag_afname / _opslag_levering / _afwijkingsdrempel / _laad_drempel
input_boolean.prijs_saldering_energiebelasting_teruggave
input_text.accu_bron_entity           sensor.energyprijs_accu_percentage (snelkoppeling)
input_number.accu_capaciteit_kwh / _vermogen_in_kw / _vermogen_uit_kw / _accu_reserve_pct  → sensor.energyprijs_accu_reserve (kWh)
input_text.pv_bron_vandaag / _pv_bron_morgen   sensor.energyprijs_pv_vandaag / _pv_morgen (snelkoppelingen)
automation.prijzen_*  (2 meld-automatiseringen)
```

## Jouw contract: invulvelden (helpers)

De formules voor inkoop en verkoop zijn **niet** voor iedereen gelijk — alleen de bruto spotprijs is dat. Daarom staan alle contractafhankelijke getallen in aanpasbare helpers (**Instellingen → Automatiseringen & scenes → Helpers**), die het package bij installatie aanmaakt met neutrale startwaarden:

| Helper | Betekenis | Formule-role |
|---|---|---|
| `input_number.prijs_btw` | btw-percentage (NL: 0,21) | ×(1+btw) in beide formules |
| `input_number.prijs_energiebelasting` | energiebelasting excl. btw (EUR/kWh) | inkoopprijs; vervalt per 1-1-2027 grotendeels |
| `input_number.prijs_opslag_afname` | leveranciersopslag afname (EUR/kWh) | inkoopprijs — **jouw leverancier, niet van mij** |
| `input_number.prijs_opslag_levering` | leveranciersopslag levering (EUR/kWh) | verkoopprijs |
| `input_boolean.prijs_saldering_energiebelasting_teruggave` | saldering aan/uit | per 1-1-2027 uitzetten → formule past zichzelf aan |

Formules: **inkoop** = (bruto + opslag_afname + energiebelasting) × (1+btw) · **verkoop** = (bruto + opslag_levering) × (1+btw) (+ belasting-teruggave zolang saldering aan staat).

Vul na installatie de waarden in die op **jouw contract** slaan (te vinden in je leveringsvoorwaarden of op je factuur); de sensoren `sensor.stroomprijs_afname` / `_levering` rekenen dan direct mee. De startwaarden in het package zijn indicatief — pas ze aan, anders kloppen inkoop/verkoop niet voor jouw situatie.

### Instellingen-tegel op je dashboard

Plak deze kaart om de velden direct bij te stellen

```yaml
type: entities
title: Stroomprijs — contractinstellingen
show_header_toggle: false
state_color: true
entities:
  - entity: input_number.prijs_btw
    name: Btw (factor, NL = 0,21)
  - entity: input_number.prijs_energiebelasting
    name: Energiebelasting excl. btw (€/kWh)
  - entity: input_number.prijs_opslag_afname
    name: Leveranciersopslag afname (€/kWh)
  - entity: input_number.prijs_opslag_levering
    name: Leveranciersopslag levering (€/kWh)
  - entity: input_boolean.prijs_saldering_energiebelasting_teruggave
    name: Saldering (teruggave belasting)
```

✅ **Volledig dynamisch:** de prijs-sensoren hebben state-triggers op hun contract-helpers. Verzet btw, energiebelasting, een opslag of zet saldering om — `sensor.stroomprijs_afname` / `_levering` (en de EnergyZero-bron) herberekenen **direct**, zonder herstart en zonder package-reload; de prijs-tegels en de daglijst-gaten lopen binnen een paar seconden mee.

### Accu-contract: de snelkoppeling naar jóuw accu (v1.2.42)

De meeste huizen hebben allang een accu-percentage-entity — alleen heet die bij de één
`sensor.solarman_battery_soc`, bij de ander `sensor.battery`. Het package lost dat op met
één vaste, botsingvrije naam plus één invulveld:

| Helper | Betekenis |
|---|---|
| `input_text.accu_bron_entity` | entity_id van jouw SOC-sensor (plakken of via de entiteitenkiezer). Leeg → `sensor.energyprijs_accu_percentage` is unavailable en de tegel toont "Geen bron ingesteld" |
| `input_number.accu_capaciteit_kwh` | accucapaciteit — maakt %→kWh mogelijk |
| `input_number.accu_vermogen_in_kw` / `_uit_kw` | max laad-/ontlaadvermogen — deurtijd-berekening |

`sensor.energyprijs_accu_percentage` is een state-based template-sensor en volgt de
gekozen bron **live**: HA triggert op elke entiteit die tijdens het renderen met
`states()` wordt gelezen — dus óók de dynamisch gekozen bron-entiteit. Vul iets anders
in of laat je SOC veranderen, de tegel en elke formule lopen direct mee. Elk dashboard,
elke automatisering en elke formule verwijst alleen naar `sensor.energyprijs_accu_percentage`
— nooit naar de bron van iemand anders. De prefix voorkomt een naambotsing met een
bestaande `sensor.accu_percentage` in jouw setup. Zelfverwijzing (het veld bevat de
sensor zelf) wordt gedetecteerd → unavailable, geen lus. De drie getal-helpers krijgen
bij de allereerste installatie conservatieve startwaarden (10 kWh / 5 kW); verzet ze
naar jouw accu.

| Helper | Betekenis |
|---|---|
| `input_text.pv_bron_vandaag` | entity_id van jouw PV-forecast-sensor voor vandaag (bijv. `sensor.<forecast_solar>_energy_production_today_remaining`). Leeg → `sensor.energyprijs_pv_vandaag` is unavailable en de tegel toont "Geen bron ingesteld" |
| `input_text.pv_bron_morgen` | entity_id van jouw PV-forecast-sensor voor morgen (bijv. `sensor.<forecast_solar>_energy_production_tomorrow`). Leeg → `sensor.energyprijs_pv_morgen` is unavailable |

`sensor.energyprijs_pv_vandaag` en `sensor.energyprijs_pv_morgen` zijn state-based
template-sensoren en volgen de gekozen bron **live** — exact hetzelfde patroon als de
accu-snelkoppeling. In de `pvcontract`-tegel zie je de verwachte kWh en een schatting
van de extra verkoopwaarde op basis van jouw `prijs_opslag_levering` + `prijs_btw`.

## Dashboard in één keer

### Weg 1: automatisch — eigen dashboard, compleet gevuld

Roep de service `energyprijs.dashboard` aan. Makkelijkste vindplaats:

- **Instellingen → Apparaten en services → Integraties → tegel "Energyprijs"** → onderaan
  staat bij *Services* een directe link **`energyprijs.dashboard`** (en `.cards`, `.install`,
  `.status`) → klik → velden leeg laten → **Action**.
- Of Developer Tools → Actions (linkerbovenhoek ☰ → Developer Tools → tab Actions) → typ
  `energyprijs.dashboard`.

Beide routes werken; de integratietegel is het duidelijkst omdat hij de services letterlijk
toont. (Zet na een HACS-upgrade eerst de integratie opnieuw uit/in of herstart HA — dan
verschijnen nieuwe services ook in die lijst.)

Dan:
- **bestaat het dashboard niet** → er wordt een nieuw user dashboard **"Energie"**
  aangemaakt met de prijs-tegels (inkoop/verkoop), de inkoop-/verkoopgrafiek en de
  contractinvulvelden. Het verschijnt direct in je dashboardmenu;
- **bestaat het dashboard al** → de kaarten worden bijgewerkt naar de opbouw uit de
  huidige versie. **Andere kaarten in het dashboard blijven 100% intact.**

Na een HACS-upgrade herbouwt het dashboard zichzelf automatisch bij de volgende
herstart (of via de 5-minutencheck) — er hoeft niets handmatig aangeroepen te worden.
Handmatig aangepaste kaarten van de integratie zelf worden dan vervangen door de
opbouw uit de repo (golden file, `tests/golden_dashboard.yaml`); wil je iets anders,
pas dan `cards.py` in de repo aan.

### Weg 2: handmatig — kaarten in je bestaande dashboard

Liever zelf bepalen waar de kaarten komen? Roep **`energyprijs.cards`** aan
(Developer Tools → Actions, Response data aan) en plak de vijf YAML-blokken
(`nu` + `grafiek` + `contract` + `accueenheden` + `accucontract`) via **Add card →
Show code editor** in je eigen dashboard — in die volgorde. De grafiek vereist de
HACS-kaart `apexcharts-card`; de tegels zijn pure core.

## Zo ziet je dashboard er daarna uit

![Voorbeeldgrafiek](docs/voorbeeld-grafiek.png)

*Inkoop- en verkoopprijs als tegels boven de grafiek (2-koloms grid). Daaronder 15-min balkjes van de inkoopprijs all-in; donkergroen < €0,10 · lichtgroen < €0,25 · geel < €0,40 · rood ≥ €0,40 — en onder de balkjes een dun rood lijntje voor de verkoopprijs. Geen legenda: balk = inkoop, lijn = verkoop. De gestippelde lijn is 'nu'. Ten slotte de contract-tegel. Dit is een nabouwing met echte data van vandaag — in HA tekent ApexCharts-card exact dit beeld, inclusief hover-waarden per kwartier.*

## Grafiek — handmatig plakken

Weg 2 (handmatig) plak je deze grafiekkaart zelf in een dashboard
(vereist `custom:apexcharts-card` via HACS). Dit is exact de kaart die de
integratie zelf genereert:

```yaml
type: custom:apexcharts-card
section_mode: true
experimental:
  color_threshold: true
graph_span: 24h
span:
  start: day
update_interval: 5min
show:
  last_updated: true
now:
  show: true
  label: nu
header:
  show: true
  title: Stroomprijs
  show_states: false
  colorize_states: false
series:
  # ── balkjes = inkoopprijs all-in per kwartier, gekleurd op prijsniveau ──
  - entity: sensor.stroomprijs_daglijst
    name: inkoop
    type: column
    yaxis_id: prijzen
    data_generator: >
      return entity.attributes.vandaag.concat(entity.attributes.morgen).map((e) => [new Date(e.t).getTime() + 450000, e.in]);
    float_precision: 3
    color_threshold:
      - value: 0
        color: "#0a8f3c"
      - value: 0.1
        color: "#2fbf5f"
      - value: 0.25
        color: "#e6b800"
      - value: 0.4
        color: "#d94040"
    show:
      in_header: false
  # ── dun lijntje onder de balkjes = verkoopprijs all-in ──
  - entity: sensor.stroomprijs_daglijst
    name: verkoop
    type: line
    yaxis_id: prijzen
    stroke_width: 1
    color: "#d94040"
    data_generator: >
      return entity.attributes.vandaag.concat(entity.attributes.morgen).map((e) => [new Date(e.t).getTime() + 450000, e.uit]);
    float_precision: 3
    show:
      in_header: false
apex_config:
  legend:
    show: false
  xaxis:
    # as loopt een halve kolom verder dan de dag → eerste/laatste staafje volledig zichtbaar
    min: EVAL:new Date(new Date().setHours(0,0,0,0)).getTime() - 450000
    max: EVAL:new Date(new Date().setHours(23,59,59,999)).getTime() + 450000
yaxis:
  - decimals: 3
    min: '|-0.04|'
    max: '|+0.04|'
```

### Staafkleur = laadstatus

Wil je elk 15-min-blok zien als *beslissing* in plaats van als prijs? De daglijst bevat
per interval ook `s` (status), berekend tegen jouw drempel
(`input_number.prijs_laad_drempel`, standaard €0,337 — pas 'm aan via Settings →
Automatiseringen & Scenes → Helpers):

| Status | Betekenis | Kleur |
|---|---|---|
| laden | afname all-in ≤ drempel | 🟢 donkergroen |
| comfort | tot €0,08 boven drempel | 🟡 geel |
| ontladen | ver daarboven | 🔴 rood |

```yaml
type: custom:apexcharts-card
experimental:
  color_threshold: true
graph_span: 24h
span:
  start: day
now:
  show: true
  label: nu
series:
  - entity: sensor.stroomprijs_daglijst
    name: laden
    type: column
    color: "#109650"
    data_generator: >
      return entity.attributes.vandaag.filter(e => e.s === 'laden').map(e => [new Date(e.t).getTime(), e.p]);
  - entity: sensor.stroomprijs_daglijst
    name: comfort
    type: column
    color: "#e6b800"
    data_generator: >
      return entity.attributes.vandaag.filter(e => e.s === 'comfort').map(e => [new Date(e.t).getTime(), e.p]);
  - entity: sensor.stroomprijs_daglijst
    name: ontladen
    type: column
    color: "#d94040"
    data_generator: >
      return entity.attributes.vandaag.filter(e => e.s === 'ontladen').map(e => [new Date(e.t).getTime(), e.p]);
yaxis:
  - decimals: 3
```

![Statusvoorbeeld](docs/voorbeeld-status.png)

De grafiek toont de **inkoopprijs** als balkjes (gekleurd op prijsniveau) met daaronder een
**dun rood lijntje voor de verkoopprijs** — geen legenda, de vormen zijn het onderscheid
(sinds v1.4.1; vóór die tijd alleen bruto-staafjes). Inkoop- en verkoopprijs staan daarnaast
als aparte tegels boven de grafiek. Hover je over een staafje,
dan geeft de tooltip bruto/in/uit voor dat kwartier — want de daglijst-sensor bevat per
interval alle drie (`{t, p, in, uit}`). Liever bruto-staafjes met in/uit erbij als dunne
lijnen? Vervang in de eerste serie `e.in` door `e.p` en voeg deze twee lijn-series toe
aan `series:` (met `show: {in_header: false}`):

```yaml
  - entity: sensor.stroomprijs_daglijst
    name: in
    type: line
    data_generator: >
      return entity.attributes.vandaag.map((e) => [new Date(e.t).getTime(), e.in]);
  - entity: sensor.stroomprijs_daglijst
    name: uit
    type: line
    data_generator: >
      return entity.attributes.vandaag.map((e) => [new Date(e.t).getTime(), e.uit]);
```

## Werking & ontwerp

- **Rekenen nooit met onverse data:** elke bron heeft een beschikbaarheidsvlag; de basisprijs vereist ≥2 verse bronnen, anders unavailable + notificatie.
- **Bruto is de basis** (kale markt excl. belasting/btw) — geschikt voor arbitrage en grafiek; all-in zit in aparte sensoren.
- **Helpers in UI aanpasbaar** — contractwijziging volgend jaar? Alleen input-velden verzetten, geen YAML-edits.

## Verwijderen

In **Instellingen → Apparaten en services → Energyprijs** het item verwijderen (ruimt
config-entry, eigen dashboard en het package-bestand op), of handmatig: de map
`custom_components/energyprijs` verwijderen + `/config/packages/energyprijs.yaml`
weghalen + herstart. configuration.yaml raakt de integratie níet meer aan
(read-only-packagesstatus sinds v1.2.39).

## Versiehistorie

| Versie | Wijziging |
|---|---|
| 1.5.0 | **Shadow-mode accu-handel**: nieuw optioneel package `shadow/energyprijs_shadow.yaml` dat de regime-vrije regel uit `stroomhandel_tactiek.md` (revisie 3) berekent naast de bestaande G1–G4-logica — 6 sensoren (doel-SOC, V, herlaadkosten, verkoop-eis, ruimte R, status in de vijf bestaande labels) + log-automation. Schrijft NOOIT naar de omvormer. Zes modelconstanten als instelbare helpers (η=0,83, w=0,025, m=0,015, N=12, C=92, grens=20%). Minimaal 2 weken shadow vóór overname. ||
| 1.4.3 | **Verkooplijn volgt de salderingschakelaar direct** (structureel): de grafiekkaart heeft géén `update_interval` meer — apexcharts v2 negeert zolang die key gezet is elke statuswijziging van de sensor en tekent alleen op de timer. Zonder die sleutel ververst de kaart ~1,5 s na elke sensor-update. De verkoopserie leest weer gewoon het daglijst-attribuut `e.uit`; de formule staat maar op één plek (package.yaml), dat blok herberekent al direct op elke helper-toggle. Nieuwe `time_pattern` (/5 min) houdt de sensor-state en dus de "nu"-markering in beweging. ||
| 1.4.2 | **Verkooplĳn volgt saldering direct**: de lijn herberekent per interval live vanuit de contract-helpers (btw, energiebelasting, leveringopslag, salderings-schakelaar) in plaats van het cached `uit`-attribuut van de sensor te lezen. Toggle je saldering om, dan beweegt de rode lijn meteen mee ||
| 1.4.1 | **Grafiek toont echte prijzen**: de balkjes zijn nu de **inkoopprijs all-in** per kwartier (`e.in`, kleurcodering blijft), met eronder een **dun rood lijntje voor de verkoopprijs** (`e.uit`). De gebruiker hoeft niet meer zelf vanuit bruto te rekenen. Beide series delen één y-as via `yaxis_id: prijzen`; legenda blijft uit — balk = inkoop, lijn = verkoop. Hover toont bruto/in/uit zoals altijd ||
| 1.4.0 | **Reserve-contract**: `input_number.accu_reserve_pct` — de SOC-ondergrens die geen enkele strategie mag underschrijden (netstoring-backup + cel-beveiliging), één bron van waarheid in plaats van verspreide hardcoded 20%-reserves. Afgeleide `sensor.energyprijs_accu_reserve` (kWh, volgt beide accu-contractnamen live; reserve 0% of ontbrekende SOC → unavailable). Accu-tegel toont nu "Boven de reserve: X kWh", contractkaart krijgt het invulveld, default éénmalig 20%. Voorbereiding solver/backtest-fase: elke winststrategie rekent vanaf nu tegen deze grens ||
| 1.3.3 | **Reviewpunten 1-4 + 6**: eigen view-behoud (herkenning op `path: energie`, nooit meer `views[0]` — jouw eerste view blijft ongemoeid), één schrijver per herbouw (live-instantie wint; geen dubbel `lovelace_updated`-event), `dashboard_bestaat()` geeft True/False/None → een blijvende storage-leesfout veroorzaakt géén herbouw-loop en de bewakingstimer daalt na succes naar 1 uur, dode imports/variabelen weg + GitHub Actions CI met ruff (ving dabei een bestaande crasher op: `restart_needed` undefined in de install-service) en een canary-test die de private HA-API's (`coll.store`, `_data_to_save`) tegen minimum-HA bewaakt. Historische review-notities verhuisden naar CHANGELOG.md ||
| 1.3.2 | **Verwijderd dashboard komt terug** (review 5 okt): de bestaanscheck is nu twee-voorwaardelijk — versie-marker **én** het item daadwerkelijk in `.storage/lovelace_dashboards`. Bij gedetecteerde verwijdering wist de integratie zijn marker en herbouwt startup/timer/service het dashboard vanzelf. Nieuw: na aanmaken registreert de integratie het dashboard expliciet in de **live** LovelaceData (`dashboards[url_path]`, exact zoals HA core dat doet), zodat de UI-websocket het direct vindt — geen leeg dashboard meer tot een herstart. Lukt die registratie niet, dan verschijnt er een repair-issue 'herstart Home Assistant' in plaats van stil falen. Startup-log op INFO meldt altijd: marker vs manifest + of het dashboard bestaat. Service `energyprijs.status` geeft veld `dashboard_bestaat` terug ||
| 1.3.1 | **Grafiek toont vandaag + morgen**: `graph_span` 24h → 48u, de daglijst-samenstelling `vandaag.concat(morgen)` tekent beide dagen op één datetime-as met daglabels (wo 5 / do 6). Morgenprijzen zijn ~14:00 bekend en verschijnen dan direct rechts in beeld; vóór die tijd blijft de as netjes bij één dag. xaxis-structuur is bewust een platte string-methode (geen geneste EVAL-objecten) — apexcharts 2.2.3 aanvaardt alleen dat formaat. ||
| 1.3.0 | **PV-contract**: twee extra snelkoppelingen voor de verwachte zonnestroom — `input_text.pv_bron_vandaag` / `input_text.pv_bron_morgen` → `sensor.energyprijs_pv_vandaag` / `sensor.energyprijs_pv_morgen` (state-based, live, zelfverwijzing-guard). Dashboard krijgt twee kaarten: pvcontract (kWh vandaag/morgen + schatting in €) en pvinstellingen. Tests uitgebreid met e2e-pv-snelkoppeling en golden-file extensie ||
| 1.2.43 | Review-fixes op v1.2.42: (1) dubbele top-levelsleutel `input_number` verwijderd — het tweede blok schuwde de zes prijshelpers uit het geparsede package (lege contracttegel, foute all-in prijzen); (2) strikte YAML-loader-test + kaarten↔package cross-check: elke entiteit die een dashboardkaart gebruikt moet door het package gedefinieerd zijn; (3) `accu_handmatig_pct` overal verwijderd, incl. registry-opruiming bij setup voor bestaande installaties; (4) accu-sensor is nu écht state-based/live: zonder triggers-blok, volgt HA de dynamisch gekozen bron-entiteit vanzelf (live bewezen in e2e-test, incl. zelfverwijzing-guard); (5) naamconflict opgelost: de contract-sensor heet `sensor.energyprijs_accu_percentage` met expliciete unique_id — geen botsing meer met bestaande `sensor.accu_percentage`. 34/34 tests groen, package door HA's eigen componenten geladen in e2e ||
| 1.2.42 | **Accu-contract**: het bewezen snelkoppeling-patroon uit de package — `input_text.accu_bron_entity` bevat een entity_id en `sensor.energyprijs_accu_percentage` (state-based template, volgt de dynamische bron live; zelfverwijzing → unavailable) is dé vaste contractnaam met prefix tegen naambotsing. Leeg veld → unavailable + "Geen bron ingesteld". Nieuwe invulvelden capaciteit (kWh) + laad-/ontlaadvermogen (kW), éénmalige defaults. Dashboard krijgt twee extra kaarten: accu-eenheden (SOC + doorrekenen naar kWh en laad-/ontlaaduren) en accu-contractinstellingen; golden file + tests uitgebreid naar 5 kaarten. Review-fixes same-day: dubbele top-levelsleutel `input_number` verwijderd (prijshelpers bestonden niet meer in het geparsede package → lege contracttegel), strikte YAML-loader-test tegen dubbele sleutels, cross-check kaarten↔package-entiteiten, handmatig-veld overal verwijderd incl. registry-opruiming bij setup ||
 1.2.41 | Dashboard genereert exact de door Jan handmatig aangepaste opbouw: alleen bruto-staafjes (verkoopprijslijn verwijderd), legenda verborgen, titel "Stroomprijs", prijs-tegels als 2-koloms grid met `state_color` op Inkoopprijs. Golden-file-test (`tests/golden_dashboard.yaml`) verankert: code en gebruikersdashboard lopen niet uit elkaar ||
| 1.2.40 | Legenda verborgen (`apex_config.legend.show: false`) + fix lege verkoopprijsserie (data_generator riep de Jinja-only `states()` aan in browser-JS → ReferenceError; nu via `hass.states`) ||
| 1.2.39 | Review-ronde: config-flow gerepareerd (ImportError → altijd install_failed); configuration.yaml wordt nooit meer herschreven (read-only status-check + plakinstructie); defaults krijgen vervolgpogingen (STARTED + 5-min timer) ||
| 1.2.38 | Opbouw-check vergelijkt de grafiekkaart sleutel-op-sleutel met `GRAFIEK_CARD` — stalen dashboards uit oudere versies worden automatisch vervangen, zonder eindeloze herbouw-loop ||
| 1.2.37 | `recorder.exclude` naar de mapping-vorm (HA 2026.x weigert de legacy lijst-vorm); package gevalideerd tegen HA's eigen recorder-schema ||
| 1.2.36 | Validatie vóór mutaties (geen leeg dashboard bij gefaalde guards); bronnen-check warn-only + op domein-niveau; package-sync met sha256 + repair-issue "herstart nodig"; defaults persistent per helper ||
| 1.2.35 | Startup-check thread-safe; blocking I/O naar executor; eenmalige defaults via `set_value`; daglijst uitgesloten van de recorder ||
| 1.2.34 | Startup-check in `async_at_started` (geen executor-thread crash); package altijd meegeschreven bij `_dashboard_opslaan` ||
| 1.2.33 | Package herschreven: helpers als `input_number` (box-mode), gecoördineerde template-triggers (HA-validator faalde op per-entity triggers); code + tests meeverhuisd naar `input_number.prijs_*` ||
| 1.2.32 | Fix `input_text`-options (HA wees template+input_text af); nu `pattern` op decimale invoer, gevalideerd tegen het HA-schema ||
| 1.2.31 | packages-include altijd op kolom 0 (ingesprongen onder `default_config:` werd door HA stil genegeerd) ||
| 1.2.30 | Test-suite groen: conftest wint van de plugin-testing-config; lovelace-guard in startup-check; manifest-versie gesynchroniseerd ||
| 1.2.29 | Startup-dashboard gefixt: lambda voor het STARTED-event, exception-logging, dashboard-klaar-check ||
| 1.2.28 | Dashboard pas ná `EVENT_HOMEASSISTANT_STARTED` (5-min timer alleen als back-up) ||
| 1.2.27 | 1-handeling installatie: `install` ruimt oude helpers op en maakt het dashboard automatisch aan ||
| 1.2.26 | Contractinstellingen tijdelijk als `input_text` — definitief `input_number` vanaf v1.2.33 ||
| 1.2.25 | Nieuwe dashboard-basis: kopwaarden uit de grafiek, losse nu-tegel (inkoop/verkoop), grafiek alleen staafjes + LIVE verkooplijn; terug naar bewezen 1-as-architectuur ||
| 1.2.24 | Dashboard-onderhoud alleen bij update: timer stopt na geslaagde setup-check, versie onthouden in de config-entry ||
| 1.2.23 | `disable_config_validation` — HA 2026.x injecteert een `disabled`-key die apexcharts v2.2.3 als extraneous afwijst (issue #997) ||
| 1.2.22 | `section_mode` en de `'+0.04'`-yaxis-max uit de grafiekkaart — extraneous keys veroorzaakten Configuration error in apexcharts v2.2.3 ||
| 1.2.21 | Versie-tag pas ná aantoonbaar geslaagde opslag + herbouw-detectie op serie-opbouw — stuck-configs worden alsnog vervangen ||
| 1.2.20 | Kopwaarden als getekende prijslijnen op een eigen y-as — header-N/A kan data niet meer verbergen ||
| 1.2.19 | Bronnen-check kijkt naar de package-sensoren zelf i.p.v. integratie-entity-namen — geen vals alarm meer ||
| 1.2.18 | Dashboard-service meldt expliciet wanneer geen enkele prijsbron werkt — N/A-dashboard wordt benoemd in plaats van getoond ||
| 1.2.17 | Dashboard onderhoudt zich automatisch: bij setup en elke 5 min, idempotent via versie-marker op de view ||
| 1.2.16 | Kaarten via de LIVE LovelaceCache (frontend ververst direct) + diagnostiek in de service-response ||
| 1.2.15 | Rode verkooplijn herberekent LIVE bij saldering/helper-wijziging; daglijst-sensor krijgt state-triggers op alle contract-helpers ||
| 1.2.14 | Sectie-view ("New section") wordt genormaliseerd naar klassieke card-view — kaarten landen nu altijd zichtbaar in het dashboard ||
| 1.2.13 | `data_template`-kopreeksen verwijderd — apexcharts-card v2.x kent die key niet (extraneous → Configuration error) ||
| 1.2.12 | Duidelijke foutmelding als het package (helpers) nog niet is geïnstalleerd, in plaats van een leeg dashboard achter te laten ||
| 1.2.11 | Dashboard-service via HA's eigen lovelace-storage + live panel-registratie (geen herstart nodig) ||
| 1.2.10 | `sw_version` uit manifest + entry-titel → services verschijnen op de integratietegel; README legt de service-vindroute uit ||
| 1.2.9 | Nieuwe service `energyprijs.dashboard` (eigen user-dashboard aanmaken of bijwerken, upgrade-proof) + `energyprijs.cards`: kant-en-klare grafiek- én contractkaart-YAML opvragen ||
| 1.2.6 | Prijs-sensoren + EnergyZero-bron krijgen state-triggers op de contract-helpers: formules herberekenen direct bij wijziging, geen HA-herstart meer ||
| 1.0.1 | Fixes uit HA-test: `min/max/initial`, mode `restart`, Jinja zonder zip-filter, availability-patroon |
| 1.0.0 | Eerste versie: installer + package |
