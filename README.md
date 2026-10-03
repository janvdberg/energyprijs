![HA](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue?logo=homeassistant)
![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-orange?logo=hackthebox)
![license](https://img.shields.io/badge/license-MIT-green)

# ⚡ Energyprijs

**Eén service-call plant het complete dynamische-stroomprijs-package in Home Assistant.**

| Wat je krijgt | Details |
|---|---|
| 🔀 3 bronnen, kruiscontrole | Nord Pool · EnerPrice · EnergyZero — basisprijs faalt als <2 bronnen vers zijn |
| 📊 Bruto daglijst (15 min) | Direct grafiekklaar voor ApexCharts-card, vandaag + morgen |
| 💶 All-in formules | Afname/levering via instelbare velden: btw, energiebelasting, opslagen |
| 🔔 Meldingen | Automatisch bij bronuitval, spreiding of ontbrekende morgenprijzen |
| 🗓️ 2027-bestendig | Saldering vervalt 1-1-2027 → één schakelaar om, formules passen zichzelf aan |

## Installatie

### Stap 1 — HACS
1. **HACS → ⋮ → Custom repositories → Add repository**
   - Repository: `jouw-naam/energyprijs` (of de URL van deze repo)
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
| 1 | Package schrijven naar `/config/packages/energyprijs.yaml` | Overschrijft alleen dit bestand |
| 2 | `packages: !include_dir_named packages` toevoegen aan configuration.yaml | Alleen als afwezig; nooit dubbel |
| 3 | Melden dat herstart nodig is | Forceert niets — jij kiest het moment |

Optioneel: `force_restart: true` meesturen als je de herstart meteen wilt.

### Stap 3 — Controleren

```yaml
action: energyprijs.status
```

Toont of package + include aanwezig zijn.

## Voorwaarden

De package gebruikt sensoren van integraties die al geïnstalleerd moeten zijn:

- **Nord Pool** (core-integratie)

> **Minstens één van deze drie bronnen is vereist.** Zonder prijsbron blijven
de sensoren `unavailable` en toont het dashboard N/A; kruiscontrole vraagt er zelfs
*twee* voor een betrouwbare basisprijs. Heb je alleen Zonneplan-forecast draaien?
Voeg dan Nord Pool óf EnergyZero toe (beide core-integraties, twee klikken).
- **EnerPrice** (HACS: `LenFaki/home-assistant-nl-day-ahead-prices`) — zet *extended attributes* aan in de opties
- **EnergyZero** (core-integratie)
- Een notify-service genaamd `notify.home` (anders de naam in het package aanpassen)

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

✅ **Volledig dynamisch:** de prijs-sensoren hebben state-triggers op hun contract-helpers. Verzet btw, energiebelasting, een opslag of zet saldering om — `sensor.stroomprijs_afname` / `_levering` (en de EnergyZero-bron) herberekenen **direct**, zonder herstart en zonder package-reload. De grafiek-koppen en de Entities-tegel lopen binnen een paar tellen mee.

## Installeren via de UI (sinds v1.2.x)

De integratie heeft een **UI-config-flow**: ga naar **Instellingen → Apparaten en
services → Integratie toevoegen → "Energyprijs"** en bevestig met één klik — het
package + de helpers worden dan automatisch neergezet, zonder service-aanroep.
(Developer Tools → Actions → `energyprijs.install` werkt nog steeds, voor wie dat
prefererent.) Na installatie is één HA-herstart nodig om de packages te laden; daarna
zijn alle sensoren en helpers aanwezig.

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
- **bestaat het dashboard niet** → er wordt een nieuw **user dashboard "Energie — stroomprijs"**
  aangemaakt, direct met de 24-uur-prijsgrafiek én de contractinvulvelden-tegel. Het
  verschijnt in je dashboardmenu;
- **bestaat het dashboard al** → alleen de energyprijs-kaarten worden bijgewerkt naar de
  huidige versie. **Andere kaarten in het dashboard blijven 100% intact** (er wordt alleen
  tussen de eigen gemarkeerde blokken geschreven).

Bij een HACS-upgrade roep je `energyprijs.dashboard` opnieuw aan — de kaarten springen
mee naar de nieuwste versie, zonder dat iets anders raakt.

### Weg 2: handmatig — kaarten in je bestaande dashboard

Liever zelf bepalen waar de kaarten komen? Roep **`energyprijs.cards`** aan
(Developer Tools → Actions, Response data aan) en plak de twee YAML-blokken
(`grafiek` + `contract`) via **Add card → Show code editor** in je eigen dashboard.
De grafiek vereist HACS-kaart `apexcharts-card`; de contract-tegel is pure core.

## Zo ziet je dashboard er daarna uit

![Voorbeeldgrafiek](docs/voorbeeld-grafiek.png)

*15-min staafjes van de bruto spotprijs; groen < €0,10 · lichtgroen < €0,25 · geel < €0,40 · rood ≥ €0,40. De gestippelde lijn is 'nu'. Dit is een nabouwing met echte data van vandaag — in HA tekent ApexCharts-card exact dit beeld, inclusief hover-waarden per kwartier.*

## Grafiek (optioneel)

Plak deze kaart in een dashboard (vereist `custom:apexcharts-card` via HACS):

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
  title: Stroomprijs — bruto · in · uit (EUR/kWh)
  show_states: true
  colorize_states: true
series:
  # ── kopwaarden 'NU' bovenin: de entiteit zelf is live, dus de knipt mee zodra een
  #    helper of sensor wijzigt (alleen header, niet getekend) ──
  - entity: sensor.stroomprijs_basis
    name: bruto nu
    float_precision: 3
    show:
      in_chart: false
  - entity: sensor.stroomprijs_afname
    name: inkoopprijs
    float_precision: 3
    show:
      in_chart: false
  - entity: sensor.stroomprijs_levering
    name: verkoopprijs
    float_precision: 3
    show:
      in_chart: false
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
  xaxis:
    # as loopt een halve kolom verder dan de dag → eerste/laatste staafje volledig zichtbaar
    min: EVAL:new Date(new Date().setHours(0,0,0,0)).getTime() - 450000
    max: EVAL:new Date(new Date().setHours(23,59,59,999)).getTime() + 450000
yaxis:
  - decimals: 3
    min: 0
    # zachte bovengrens: 4 cent boven de hoogste waarde die in beeld is
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

Bij de **nu**-lijn tonen de kopwaarden bovenin de actuele prijzen — ze knipperen mee zodra je een contract-helper verzet:
bruto · **inkoopprijs** · **verkoopprijs**. Hover je over een staafje,
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

Map `custom_components/energyprijs` verwijderen + het package-bestand uit `/config/packages/` halen + herstart. De installer liet verder niets achter in configuration.yaml behalve de (optioneel te laten staan) packages-include.

## Versiehistorie

| Versie | Wijziging |
|---|---|
| 1.2.13 | Grafiekkaart: `data_template`-kopreeksen verwijderd — apexcharts-card v2.x kent die optie niet meer (extraneous key → 'Configuration error'). Kopwaarden blijven live via de entiteit zelf ||
| 1.2.12 | Dashboard-service geeft een duidelijke foutmeldt zodra het energie-package (helpers) nog ontbreekt, in plaats van een leeg dashboard achter te laten ||
| 1.2.11 | Dashboard-service volledig op HA-native lovelace-storage + panel-registratie (dashboard verschijnt zonder herstart) ||
| 1.2.10 | Integratietegel toont de services (dynamische sw_version uit manifest + entry-titel); README legt de service-vindroute uit via de integratiepagina || 1.2.9 | Nieuwe service `energyprijs.dashboard` (eigen user-dashboard aanmaken of bijwerken; upgrade-proof, andere kaarten intact) + `energyprijs.cards`: haalt de kant-en-klare grafiek- én contractkaart-YAML in één keer op — geen handmatig plakwerk meer vanuit de repo || 1.2.7 | Dashboardkaart: kopwaarden live in de grafiekheader (lopen direct mee met helper-wijzigingen) en y-as met vaste ondergrens 0 + zachte bovengrens; README-tekst aangepast || 1.2.6 | Prijs-sensoren + EnergyZero-bron krijgen state-triggers op de contract-helpers: formules herberekenen direct bij wijziging, geen HA-herstart meer |
| 1.0.1 | Fixes uit HA-test: `min/max/initial`, mode `restart`, Jinja zonder zip-filter, availability-patroon |
| 1.0.0 | Eerste versie: installer + package |