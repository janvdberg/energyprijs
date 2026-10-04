![HA](https://img.shields.io/badge/Home%20Assistant-2026.x-blue?logo=homeassistant)
![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-orange?logo=hackthebox)
![versie](https://img.shields.io/badge/versie-1.2.41-brightgreen)
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
  aangemaakt met de prijs-tegels (inkoop/verkoop), de 24-uur-brutografiek en de
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
(Developer Tools → Actions, Response data aan) en plak de drie YAML-blokken
(`nu` + `grafiek` + `contract`) via **Add card → Show code editor** in je eigen
dashboard — in die volgorde. De grafiek vereist de HACS-kaart `apexcharts-card`;
de tegels zijn pure core.

## Zo ziet je dashboard er daarna uit

![Voorbeeldgrafiek](docs/voorbeeld-grafiek.png)

*Inkoop- en verkoopprijs als tegels boven de grafiek (2-koloms grid). Daaronder 15-min staafjes van de bruto spotprijs; donkergroen < €0,10 · lichtgroen < €0,25 · geel < €0,40 · rood ≥ €0,40 — geen legenda, de kleuren zijn het onderscheid. De gestippelde lijn is 'nu'. Ten slotte de contract-tegel. Dit is een nabouwing met echte data van vandaag — in HA tekent ApexCharts-card exact dit beeld, inclusief hover-waarden per kwartier.*

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
  # ── staafjes = bruto spot per kwartier, gekleurd op prijsniveau ──
  - entity: sensor.stroomprijs_daglijst
    name: bruto
    type: column
    data_generator: >
      return entity.attributes.vandaag.map((e) => [new Date(e.t).getTime() + 450000, e.p]);
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

De grafiek toont bewust alléén de bruto-staafjes (geen legenda — de staafkleuren zijn het
onderscheid; de verkoopprijslijn is sinds v1.2.41 verwijderd). Inkoopprijs en verkoopprijs
staan als aparte tegels boven de grafiek. Hover je over een staafje,
dan geeft de tooltip bruto/in/uit voor dat kwartier — want de daglijst-sensor bevat per
interval alle drie (`{t, p, in, uit}`). Wil je in/uit per interval in de grafiek zelf,
voeg dan deze twee lijn-series toe aan `series:` (met `show: {in_header: false}`):

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
| 1.2.41 | Dashboard genereert exact de door Jan handmatig aangepaste opbouw: alleen bruto-staafjes (verkoopprijslijn verwijderd), legenda verborgen, titel "Stroomprijs", prijs-tegels als 2-koloms grid met `state_color` op Inkoopprijs. Golden-file-test (`tests/golden_dashboard.yaml`) verankert: code en gebruikersdashboard lopen niet uit elkaar ||
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
## Versiehistorie

| Versie | Wijziging |
|---|---|
| 1.2.41 | Dashboard genereert exact de door Jan handmatig aangepaste opbouw: alleen bruto-staafjes (verkoopprijslijn verwijderd), legenda verborgen, titel "Stroomprijs", prijs-tegels als 2-koloms grid met `state_color` op Inkoopprijs. Golden-file-test (`tests/golden_dashboard.yaml`) verankert: code en gebruikersdashboard lopen niet uit elkaar ||
| 1.2.40 | Legenda verborgen (`apex_config.legend.show: false`) + fix lege verkoopprijsserie (data_generator riep de Jinja-only `states()` aan in browser-JS → ReferenceError; nu via `hass.states`) ||
| 1.2.39 | Review-ronde: config-flow gerepareerd (ImportError → altijd install_failed); configuration.yaml wordt nooit meer herschreven (read-only status-check + plakinstructie); defaults-krijs krijgt vervolgpogingen (STARTED + 5-min timer) ||
| 1.2.38 | Opbouw-check vergelijkt de grafiekkaart sleutel-op-sleutel met `GRAFIEK_CARD` — stalen dashboards uit oudere versies worden automatisch vervangen, zonder eindeloze herbouw-loop ||
| 1.2.37 | `recorder.exclude` naar de mapping-vorm (HA 2026.x weigert de legacy lijst-vorm); package gevalideerd tegen HA's eigen recorder-schema ||
| 1.2.36 | Validatie vóór mutaties (geen leeg dashboard bij gefaalde guards); bronnen-check warn-only + op domein-niveau; package-sync met sha256 + repair-issue "herstart nodig"; defaults persistent per helper ||
| 1.2.35 | Startup-check thread-safe; blocking I/O naar executor; eenmalige defaults via `set_value`; daglijst uitgesloten van recorder ||
| 1.2.34 | Startup-check in `async_at_started` (geen executor-thread crash); package altijd meegeschreven bij `_dashboard_opslaan` ||
| 1.2.33 | Package herschreven: helpers als `input_number` (box-mode), gecoördineerde template-triggers (HA-validator faalde op per-entity triggers); code + tests meeverhuisd naar `input_number.prijs_*` ||
| 1.2.32 | Fix `input_text`-options (HA wees template+input_text af); nu `pattern` op decimale invoer, gevalideerd tegen het HA-schema ||
| 1.2.31 | packages-include altijd op kolom 0 (ingesprongen onder `default_config:` werd door HA stil genegeerd) ||
| 1.2.30 | Daglijst-attributes als JSON-string + `from_json` in de browser-generators (HA coërceert template-attributes tot string); helperfactoren live via `hass.states` in de grafiek ||
| 1.2.28 | UI-config-flow: integratie toevoegen met één klik plant package + helpers; repair-issues vervangen stiklige foutmeldingen ||
| 1.2.27 | Versie-markering één bron (manifest); HACS-releases + zipball-verificatie in de workflow ||
| 1.2.26 | Dashboard-service normaliseert sectie-views (nieuwe UI-dashboards) naar klassieke card-views vóór injectie — leeg dashboard opgelost ||
| 1.2.25 | Herstart-nodig-issue opgelost zodra de package opnieuw wordt geladen; `handle_status` toont package-actueel-status ||
| 1.2.24 | Dashboard-beleid vastgelegd: de integratie houdt het dashboard niet elke 5 min bij — één check na update/herstart, daarna unsubs de timer ||
| 1.2.23 | `experimental: disable_config_validation` op de grafiekkaart (HA-injecteert zelf UI-keys die de v2.2.3-checker afwijst) ||
| 1.2.22 | Kopwaarden als getekende line-series op een eigen y-as (header-cash kon N/A blijven hangen na herstart) ||
| 1.2.21 | Bron-sensoren: package leest de package-eigen sensoren, niet de integratie-entity-namen (verschillen per installatie) ||
| 1.2.20 | Multi-as-poging (yaxis_id) — teruggezet in 1.2.25 naar de één-asopbouw ||
| 1.2.19 | Grafiek leest de package-sensoren zelf; N/A-koppen nu herkenbaar als bron-availability, geen codebug ||
| 1.2.18 | Herstart-nodig-issue + repair-registry voor package-sync; service-diagnosebalk met cache-status ||
| 1.2.17 | Automatisch onderhoud: dashboard-check bij startup + 5-min interval, idempotent via versie-marker op de view ||
| 1.2.16 | Diagnosebalk in elke dashboard-aanroep (geïnstalleerde versie, helpers, view-type, cards, cache-bijgewerkt) ||
| 1.2.15 | Dashboard vullen via de live LovelaceCache (`LOVELACE_DATA.dashboards[...].async_save`) — frontend ververst direct, geen leeg dashboard ||
| 1.2.30 | Test-suite groen: conftest wint van de plugin-testing-config; manifest-versie gesynchroniseerd ||
| 1.2.29 | Startup-dashboard gefixt (lambda voor het STARTED-event, exception-logging, dashboard-klaar-check) ||
| 1.2.28 | Dashboard pas ná `EVENT_HOMEASSISTANT_STARTED` (5-min timer alleen als back-up) ||
| 1.2.27 | 1-handeling installatie: `install` ruimt oude helpers op, maakt automatisch het dashboard aan ||
| 1.2.26 | Contractinstellingen tijdelijk als `input_text` — later (v1.2.33) definitief `input_number` ||
| 1.2.25 | Nieuwe dashboard-basis: kopwaarden uit de grafiek, losse nu-tegel (inkoop/verkoop), grafiek alleen staafjes + LIVE verkooplijn — terug naar bewezen 1-as-architectuur ||
| 1.2.24 | Dashboard-onderhoud alleen bij update: timer stopt na geslaagde setup-check, versie onthouden in de config-entry ||
| 1.2.23 | `disable_config_validation` — HA 2026.x injecteert een `disabled`-key die apexcharts v2.2.3 als extraneous afwijst (issue #997) ||
| 1.2.22 | `section_mode` en de `'+0.04'`-yaxis-max uit de grafiekkaart (extraneous keys → Configuration error) ||
| 1.2.21 | Versie-tag pas ná aantoonbaar geslaagde opslag + herbouw-detectie op serie-opbouw — stuck-configs worden alsnog vervangen ||
| 1.2.20 | Kopwaarden als getekende prijslijnen op een eigen y-as (header-N/A kan data niet meer verbergen) ||
| 1.2.19 | Bronnen-check kijkt naar de package-sensoren zelf i.p.v. integratie-entity-namen — geen vals alarm meer ||
| 1.2.18 | Dashboard-service meldt expliciet wanneer geen enkele prijsbron werkt — N/A-dashboard wordt benoemd in plaats van getoond ||
| 1.2.17 | Dashboard onderhoudt zich automatisch: bij setup en elke 5 min, idempotent via versie-marker op de view ||
| 1.2.16 | Kaarten via de LIVE LovelaceCache (frontend ververst direct) + diagnostiek in de service-response ||
| 1.2.15 | Rode verkooplijn herberekent LIVE bij saldering/helper-wijziging; daglijst-sensor krijgt state-triggers op alle contract-helpers ||
| 1.2.14 | Dashboard-kaarten overleven HA-updates: opbouw-check + idempotente herbouw van eigen kaarten, andere kaarten intact ||
| 1.2.13 | Grafiekkaart: `data_template`-kopreeksen verwijderd — apexcharts-card v2.x kent die optie niet meer (extraneous key → 'Configuration error') ||
| 1.2.12 | Dashboard-service geeft een duidelijke foutmelding zodra het energie-package (helpers) nog ontbreekt, in plaats van een leeg dashboard achter te laten ||
| 1.2.11 | Dashboard-service volledig op HA-native lovelace-storage + panel-registratie (dashboard verschijnt zonder herstart) ||
| 1.2.10 | Integratietegel toont de services (dynamische sw_version uit manifest + entry-titel); README legt de service-vindroute uit via de integratiepagina ||
| 1.2.9 | Nieuwe service `energyprijs.dashboard` (eigen user-dashboard aanmaken of bijwerken; upgrade-proof, andere kaarten intact) + `energyprijs.cards`: kant-en-klare grafiek- én contractkaart-YAML in één keer opvragen ||
| 1.2.6 | Prijs-sensoren + EnergyZero-bron krijgen state-triggers op de contract-helpers: formules herberekenen direct bij wijziging, geen HA-herstart meer ||
| 1.0.1 | Fixes uit HA-test: `min/max/initial`, mode `restart`, Jinja zonder zip-filter, availability-patroon |
| 1.0.0 | Eerste versie: installer + package |