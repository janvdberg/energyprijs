# Changelog

Incident-/reviewvermeldingen die eerder als commentaar in de code stonden ("les
live-log 3 okt", "review 4 okt", …). De code bevat alleen nog het *waarom*; de
*wanneer/welke-review* staat hier.

## 2026-10-21 — v1.7.3: status COMFORT was misleidend → 'COMFORT (verkoop)'

Symptoom (live, 21 okt '26): de user zag status COMFORT terwijl de accu
verkoopt, en vond de naam misleidend. We hadden op 2026-10-05 de
statusnamen alvast voor het *eigen* systeem vastgesteld
(`/opt/data/roi-monitor/accu_statusnamen.md`): daar heet de verkoop-band
'Ontladen' en is 'Comfort' óf 'Neutraal' of 'Spaar' — nooit verkoop.
ShadowPIES' COMFORT = verkoop (uit > verkoop-eis) klopt dus functioneel,
maar de naam overlap met het oude Comfort-gebruik misleidt.

Fix (minimaal, repo-versie): card-text in `cards.py` (SHADOW_CARD):
`COMFORT (verkoop) — accu → net, prijs boven verkoop-eis` + commentaar in
`shadow.yaml`. De state-waarde 'COMFORT' blijft (veranderd = alle
toetreden/hysteresis-logica opnieuw testen); alleen de weergave verandert.
Overtoelassing naar de eigen banden + de openstaande eis-formule
(h/η_rt i.p.v. h/η_laad → eis €0,3632 i.p.v. €0,3309) staat in
`/opt/data/roi-monitor/shadow_statusnamen.md`.

## 2026-10-21 — v1.7.2: placeholder-bronnen droegen string '[]' → morgen_prognose leeg

Symptoom (live, 21 okt '26): de grijze prognose-reeks in de stroomprijs-kaart
bleef leeg terwijl `sensor.prijzen_bron_voorspelling.prices_tomorrow` 24
geldige punten voor morgen had.

Oorzaak: de placeholder-bronnen Nordpool en EnergyZero definieerden
`prices_today`/`prices_tomorrow` als de YAML-string `"[]"`. In Jinja is `[]`
een sequence van 2 tekens, dus `state_attr(eid, 'prices_tomorrow') |
default([], true) | count > 0` was waar (count=2). De echte-morgen-check in
`morgen_prognose` vond daardoor een 'echte' bron en rendert `{{ [] }}` — de
grijze balken kwamen nooit.

Fix (minimaal, repo-versie — installer.py schrijft het package bij een
update terug):
1. `prices_today: "{{ [] }}"` / `prices_tomorrow: "{{ [] }}"` bij Nordpool
   en EnergyZero (renderen een echte lege lijst).
2. Robuuster: de echte-morgen-check is nu lijst-bewust
   (`is sequence and is not string and count > 0`), dus ook een string-'[]'
   zou niet meer door de check slippen.
3. Regresie-test `tests/test_pkg_placeholders.py`: de attribute-templates
   renderen een lege lijst + geen string-'[]' meer in het package + de
   lijst-bewuste check staat er.

## 2026-10-21 — v1.6.2: Claude-review round 2 (verificatie + correcties)

**Crash-voorkoming:**
1. `from` + `not_from` samen in de shadow-trigger (shadow.yaml r.375-382): HA's schema gebruikt `vol.Exclusive(CONF_FROM, CONF_FROM)` voor beide keys (state.py r.55-56), dus ze sluiten elkaar uit. De trigger laadt niet → de automation is onbeschikbaar. Fix: alleen `to` + `not_from: [unavailable, unknown]`.
2. `continue_on_error` vangt wél `ServiceNotFound` af (script.py r.576 in de `continue_on_error`-except-lijst). De v1.5.9-comment was onjuist. De notify-guard is nu correct.
3. `notify.persistent_notification` is wél een geldige notify-service (notify/const.py r.29: `SERVICE_PERSISTENT_NOTIFICATION = "persistent_notification"`). De v1.5.9-comment was onjuist.

**Correctheid:**
4. η voor roundtrip-transacties: de oude η_gem = (77+90)/200 = 0.835 (gemiddelde per been) → η_rt = 77×90/10000 = 0.693 (hele roundtrip). Dit beïnvloedt de V-grens (shadow.yaml r.146) en de verkoop-eis (r.237). De oude V-grens lag ~17% te laag; de nieuwe is correct.
5. Dode code verwijderd: `ns3`-lus, `pv_eis` en `SOC2` in de shadow-status-sensor (r.270-290) werden berekend maar nooit gebruikt.
6. Doel-SOC availability: `states(...) is not none` → `has_value(...)` (r.123). De oude check is altijd waar; een uitgevallen PV-bron gaf S=0 en doel-SOC=100.
7. Deling door 0 guard: `allin / rt` in de daglijst (package.yaml r.331, r.386) → `allin / rt_safe` met `rt_safe = [rt, 0.01] | max`. Bij de eerste start zijn de rendementshelpers even 0.
8. Toeslag-sensor in de afname/levering-triggerlijst (package.yaml r.404): vóór deze fix kon afname/levering op een uurgrens tot 5 min met de oude toeslag rekenen.

**Afgekeurde punten (met reden):**
- **astimezone() → as_local**: de review stelde dit voor, maar in HA OS is de systeemzone = HA-zone, dus `astimezone()` zonder argument is correct. `as_local` zou hetzelfde resultaat geven. (De repo is publiek, maar de primaire use-case is HA OS.)
- **Parser-hoist** (regex_findall vóór de for-lus): haalbaar maar risicovol — de regex in YAML/Jinja2-escaping is al een keer misgegaan in een eerdere macro-poging. De 3 inline parser-bommen blijven staan voor nu.
- **File split**: breekt het "één bestand, één deploy"-principe.
- **Geheugenknop trigger**: de `input_text.shadow_vorige_status` wordt inderdaad niet in de triggers vermeld, maar de comment "HA triggert op de write" klopt niet — de trigger is de status-sensor zelf. Dit is een comment-clarification, geen code-fix.

**Open (voor volgend review):**
- Parser-hoist (prestatie-optimalisatie, ~192 regex-runs/herberekening besparen)
- `0.08` hardcoded in de 's'-kolom (package.yaml r.327, r.380)
- PV-herlaadvenster mist morgenochtend-zonuren als zon nu boven horizon staat
- `shadow_capaciteit` en `shadow_soc_min` dupliceren `accu_capaciteit_kwh` en `accu_reserve_pct` (tweede bron van waarheid)

## 2026-10-19 — v1.6.1: Claude-review P2 (prestaties) + P3 (onderhoudbaarheid)

**P2 — prestaties:**
1. `time_pattern /5` verwijderd uit de shadow-triggers (shadow.yaml r.91-92). De daglijst-kwartier-cyclus (time_pattern /5 in het package) drijft de shadow al mee via `sensor.stroomprijs_daglijst`. Een eigen time_pattern in de shadow forceerde per 5 min een herschrijving van de beslissings-log — onnodige log-bloat.
2. Macro-optimalisatie (nettoeslag-parser → macro) **teruggedraaid**: de macro breekt de pytest-omgeving (`macros` is undefined in de testcontext). De 3 inline parser-bommen blijven staan — correctheid gaat voor.

**P3 — onderhoudbaarheid:**
1. **File split afgekeurd**: de review stelde voor het package op te splitsen in meerdere YAML-bestanden. Dit breekt het "één bestand, één deploy"-principe en voegt complexiteit toe (meerdere bestanden moeten samenhangend bijgewerkt worden). Het 829-regels-probleem lost het ook niet op — de code blijft complex.
2. **Dode code**: geen daadwerkelijke dode code gevonden. De commentaarregels zijn documentatie (het *waarom*), niet dode code.
3. **Versie-informatie**: al verplaatst naar de CHANGELOG (v1.2.33 en v1.5.5 header-commentaar blijven staan als context, maar de versiegeschiedenis staat nu in de CHANGELOG).

**Afgekeurde P2-punten (met reden):**
- `now()` throttle in de toeslag-sensor: de sensor wordt al gedreven door de daglijst-kwartier-cyclus. Een eigen uurgrens-trigger zou de sensor uit het state-based blok moeten halen (grote verplaatsing, geen winst).
- `astimezone()` → `as_local`: de review markeerde dit als probleem, maar in HA OS is de systeemzone = HA-zone, dus `astimezone()` zonder argument is correct. `as_local` zou hetzelfde resultaat geven.

**Verantwoording:**
- Review uitgevoerd door Claude (Sonnet) op 19 okt 2026. Alle punten geverifieerd: P0/P1 volledig geïmplementeerd (v1.6.0), P2 deels geïmplementeerd (time_pattern /5 uit shadow), P3 deels afgekeurd (file split).
- Review-document: `roi-monitor/claudereview_v159.md`.

## 2026-10-19 — v1.6.0: Claude-review P0+P1 (crash-voorkoming + correctheid)

**P0 — crash-voorkoming:**
1. `from_is_not` (ongeldige key) → `not_from` in de shadow-log-automation (shadow.yaml r.377). De HA-state-trigger kent alleen `from`/`to`/`not_from`/`not_to` (gecontroleerd in de HA-broncode `homeassistant/components/homeassistant/triggers/state.py`). De oude key maakte de automation onbeschikbaar.
2. `input_text.prijs_net_blokken max: 1024` → `255` (HA-statecap is 255 tekens; package.yaml r.738).
3. `| max` op mogelijk-lege lijst in `accu_reserve_kwh` availability → `| list | max(default=-1)` (package.yaml r.485-489).

**P1 — correctheid:**
4. Epoch-vergelijking in shadow: `e.t >= now().isoformat()` (string-vergelijking, UTC vs lokaal) → `e.e >= nu_epoch` (integer-epoch). Daglijst-entries krijgen nu een `e`-veld (epoch-seconden) mee in package.yaml (vandaag + morgen).
5. η-consistentie: de LADEN-grens gebruikte η_gem (gemiddelde van beide benen, 0.835) in plaats van η_laad (0.77). Nu: `(nu2.in_nu / eta_laad) + w + m` in de LADEN-beslissing (shadow.yaml r.316-317). De V-grens en PV-herlaad-kant blijven op η_gem (per been) — dat is de juiste keus voor die formules.
6. `nu2._t` (underscore-variabele, stilistisch onhandig) → `nu2.t_nu` + epoch-vergelijking in plaats van `as_datetime` per entry (shadow.yaml r.290-299).

**Verantwoording:**
- Review uitgevoerd door Claude (Sonnet) op 19 okt 2026; ik heb elk punt met `(?)` geverifieerd tegen de HA-broncode en onze code. Twee punten van Claude waren onjuist: (a) `continue_on_error` vangt ServiceNotFound wél af (de v1.5.9-fix was al correct); (b) `from_is_not` is niet overbodig — de `from`-lijst sluit `unavailable` niet uit, dus `not_from` is nodig.
- P2 (prestaties: parser-uitbrenging, time_pattern /5 in shadow) en P3 (onderhoudbaarheid: splitsen, dode code) staan nog open; zie `roi-monitor/claudereview_v159.md`.

## 2026-10-19 — v1.5.9 (deel 2): ACM-netblokken-parser herschreven + input_text gedefinieerd

**Problemen in de eerste netblokken-implementatie (v1.5.9, package.yaml):**
1. `input_text.prijs_net_blokken` werd in 9 sjabloonregels referenced maar was
   níét gedefinieerd → entity ontbreekt na installatie.
2. De parser splitte op `,` én `;`; de komma is ook het decimaalteken
   (`0,65`), dus winterprofielen werden vermalen.
3. Seizoen-prefix `W|0-1` brak de uur-splitting (prefix zat in het bereik).
4. HA-specifieke `matches`-operator en Python-methode `.trim()` in Jinja2 —
   niet-portabel en ongetest.

**Fix:**
- `input_text.prijs_net_blokken` toegevoegd: max **1024** tekens (volledig
  jaarprofiel past niet in 255), icon `mdi:grid`.
- Alle 3 de parser-lussen (teller-sensor + 2× daglijst) vervangen door een
  regex-parser via `regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)')`:
  puntkomma's scheiden blokken, komma = decimaal, prefixloos = beide seizoenen,
  rond-middernacht-blokken ondersteund, ongeregeld tekst genegeerd.
- Formaatdocumentatie in package.yaml aangescherpt.
- `matches` → `is match()` (3×), `.trim()` → `| trim` (15×), ss/ee-extractie
  via `(rng.split('|')[-1])`.

**Geverifieerd:** YAML parse OK; 32 Jinja2-sjablonen syntax-check OK (incl.
automations); parser-getest met exacte package.yaml-code in een nagebootste
HA-Jinja2-omgeving (regex_findall per HA-docs: list van tuples bij meerdere
capture-groeps, sinds HA 0.7): 12 seizoens-/uurcases ✓ + 7 randgevallen (leeg,
rommel, seizoenloos, rond-middernacht, net buiten blok, komma-gescheiden) ✓.

## 2026-10-19 — v1.5.9 (deel 1): shadow-log-automation hersteld

**Incident:** de log-automation "Shadow handel — log elke statusbeslissing"
stond van de dag-18-herstart tot nu op `unavailable` en had NUL runs — de
shadow-test (sinds 18 okt) liep dus zonder beslissingslog. Root cause: de
actie `notify.persistent_notification` verwijst naar een notify-service die
bestaat pas als Jan een naam in `input_text.prijs_notify_doel` zet; zonder die
service is de automation bij het laden onbeschikbaar. De service-calls
`notify.persistent_notification` (HTTP 200, direct aanroepen) en
`persistent_notification.create` werken wél — alleen de *referentie* in de
automation breekt.

**Fix (shadow.yaml, component-versie):**
1. De log-rij wordt een `variables`-block (`shadow_log_rij`) — één template,
   één keer gerenderd.
2. Nieuwe action `event: energyprijs_shadow_statusbeslissing` met
   timestamp/status/from/in/uit/V/eis/R/doelSOC/SOC — persistente
   beslissingslog in het event-log (onafhankelijk van elke notify-service;
   de maandrapport-lectie kan deze events lezen).
3. De meldactie volgt nu het hoofdpackage-patroon:
   `{{ 'notify.' ~ (states('input_text.prijs_notify_doel') or 'persistent_notification') }}`
   + `continue_on_error: true` — ontbreekt de service, dan mislukt alleen de
   melding, niet de hele automation.
4. `persistent_notification.create` (laatste actie) blijft ongewijzigd.

**Naverkenning:** het losse `shadow/energyprijs_shadow.yaml` in de repo is
sinds v1.5.2 verouderd (168 diff-regels t.o.v. de ingebedde
`custom_components/energyprijs/shadow/shadow.yaml` die de installer synct).
Wie die map handmatig installeert krijgt de oude kwartier-index-bug +
`initial:`-overschrijvingsbug. De ingebedde versie is de enige
gezagshebbende; de losse map hoort te verdwijnen bij de volgende opruiming.

**Teststatus na deze fix:** de eerste 12 dagen shadow-test gelden niet als
beslissingsdata (alleen de sensoren zelf draaiden correct: doel-SOC, V, R,
status; de overnames-schakel — de log — ontbrak). Na HACS-update + herstart
met v1.5.9 start de beslissingslog pas; 14 dagen vanaf herstart tellen.

## 2026-10-12 — CONTRACT_CARD als vertical-stack (v1.5.8)

Zelfde root-cause als v1.5.7, maar Jan wil de groepskoppen terug: "Verplaats
de geneste kaarten uit de entities:-lijst en maak ze losse kaarten in één
vertical-stack." De buitenste contractkaart blijft een platte entities-kaart
(5 rijen), gevolgd door zelfstandige kaarten "Rendement accu" (rendement_* +
shadow_eta, icon mdi:battery-sync) en "Tariefcontract 2028" (prijs_dal_uren,
prijs_top_uren, prijs_opslag_tijdsafhankelijk, icon mdi:clock-alert-outline).
Alle namen/iconen/entity-id's behouden; `color: state` komt nergens voor —
dat is géén entities-key; het equivalent is `state_color: true` op de kaart
zelf en staat dus gewoon zo. Elke subkaart is nu apart in de visuele editor
te bewerken zonder configuratiefout.

## 2026-10-12 — geneste groepen verwijderd uit CONTRACT_CARD (v1.5.7)

Jan stuurde een screenshot: de visuele editor van HA markeerde de kaart met
"Required key entities.5.entity is missing / provided value ... expected
(string) but received JSON object". Oorzaak: `type: entities` subkaarten als
ROW binnen een entities-kaart zijn geen geldige row-configuratie — de
front-end-editor (superstruct `entitiesRowConfigStruct`) kent alleen strings,
`{entity,name,icon}` en de vaste row-types (divider/section/weblink/...).
De kaarten renderen wel, maar elke UI-bewerking slaat mis.
- Oplossing: helpers plat in de lijst als gewone `{entity, name}`-rijen, met
  naamvoorzetsels "Rendement: ..." / "Tarief 2028: ...". Zichtbaarheid uit
  v1.5.6 blijft; de config is nu ook editor-compatibel.

## 2026-10-12 — rendements- en 2028-helpers zichtbaar op dashboard (v1.5.6)

Jan: "de helpers voor accu-efficiëntie ook op het dashboard terugzien".
De v1.5.5-helpers bestonden al (installer zette defaults) maar waren nergens
zichtbaar. Eerste poging gebruikte `custom:expandable-entities-card` — een
HACS-kaart die hier niet geïnstalleerd is; rood kaartje gegarandeerd.
- Oplossing: native Lovelace-uitklapgroepen (`type: entities` + `name:` —
  geneste groepen vouwen vanzelf uit, geen extra installatie nodig).
- Twee groepen in de ACCUCONTRACT_CARD: "Rendement accu — gemeten aug→okt '26"
  (rendement_laad/ontlaad/roundtrip_pct + shadow_eta) en "Tariefcontract 2028 —
  tijdsafhankelijke opslag" (prijs_dal_uren, prijs_top_uren,
  prijs_opslag_tijdsafhankelijk).
- shadow_eta hernoemd naar "η solvermodel (×) — gewogen laad/ontlaad, géén
  meting": het is de modelwaarde ≈0,835, niet de gemeten roundtrip 0,70.
- Versie 1.5.5 → 1.5.6 (dashboard herbouwt zich via de dashboard_versie-marker).

## 2026-10-12 — gemeten rendement als aparte invulvelden (v1.5.5)

Jan: "handelen met verlies is dom". De meting aug-okt '26 (`accu_verlies_meten.py`)
geeft laden ~77% / ontladen ~90% → roundtrip ~70%; de solver-rekenkunde ging uit
van 0,83 (vóór-meting-aanname).
- Nieuwe helpers: `rendement_laad_pct` (77), `rendement_ontlaad_pct` (90),
  `rendement_roundtrip_pct` (70). De formules in package.yaml en shadow.yaml
  lezen deze VÓÓR `shadow_eta` via een rend_ok-check; ontbreken de helpers →
  terugval op `shadow_eta`.
- η per been = gemiddelde(77,90)/100 ≈ 0,835 — in de solver-formules; rt =
  0,77×0,90 ≈ 0,70 — in de rt/rt_uit-kolommen van de daglijst (werkelijke
  inkoop-/verkoopkosten per kWh).
- Bewuste bevoring: `shadow_eta` blijft 0,83 tot Jan verzet; bij uitzetten van
  de rendements-helpers valt de solver terug op het optimistische getal —
  markeringscommentaar in installer.py en shadow.yaml wijst erop.
- Effect op G-banden (η=0,70): break-even verkoopprijs = G1/0,70 ≈ €0,45 bij
  G1=0,315; daaronder kruist het model en handelt het niet meer — precies de
  gewenste "nooit met verlies"-gedrag.
- Tests: `pytest tests/test_shadow_package.py tests/test_shadow_yaml_valid.py`
  → 8 passed. Gepubliceerd op GitHub (master én main, commit 52440b6).

## 2026-10-10 — daglijst pakt eerste beschikbare bron + verifiëren (v1.5.3)

Jan (2 u 's nachts): "we hebben nog geen prijzen voor morgen terwijl de
prijzen al wél bekend zijn." Oorzaak: de daglijst (`sensor.stroomprijs_daglijst`)
las uitsluitend van EnerPrice (`prices_today`/`prices_tomorrow`). Om die tijd
had EnerPrice de D+1-prijzen nog niet opgehaald → `morgen` leeg, terwijl de
D+1-prijzen al op de markt stonden.

Fix: de daglijst kiest nu de **eerste bron (vaste volgorde EnerPrice →
Nord Pool → EnergyZero) met een levende daglijst** — "eerste pakken,
latere verifiëren":
- `attributes.bron` op `sensor.stroomprijs_daglijst` toont welke bron de
  daglijst nu levert (enerprice / nordpool / energyzero / leeg = géén).
- `vandaag` en `morgen` worden per dag apart gekozen: de eerste bron met
  prijs voor DIE dag. Een bron die alleen vandaag levert, is dus geen
  bron voor morgen.
- Alle drie de bron-sensoren (Nord Pool, EnergyZero) dragen nu lege
  `prices_today`/`prices_tomorrow`-attributes, zodat het selectie-mechanisme
  overal dezelfde structuur ziet.
- **Verifiëren**: de bestaande momentprijs-kruiscontrole
  (`binary_sensor.prijzen_kruiscontrole_afwijking`) checkt dat de drie
  bronnen op het momentprijs overeenkomen; de 15:15-melding noemt nu
  expliciet welke bron de daglijst levert én welke momentprijs-bronnen
  actief zijn.
- De daglijst-sensor zelf heeft géén availability-afhankelijkheid op één
  bron: zolang er ÉÉN daglijst is, staat de sensor.

Nieuwe tests: `tests/test_daglijst_bron_fallback.py` (3 e2e-scenario's:
EnerPrice-voorkeur, Nord Pool-fallback, EnergyZero-fallback).

Installatie: HACS-update + herstart. De bron-fallback werkt direct; de
15:15-melding en `attributes.bron` verschijnen na de herstart.

## 2026-10-10 — anti-knippering voor de shadow-status (v1.5.2)

Jan: "de energyprijs schakelt wel heel vaak van laden naar spaar."
Diagnose: de shadow-status (`sensor.shadow_status`) tikte elk kwartier tussen
de statussen — twee oorzaken, beide gefixt:

1. **Kwartier-index-gap.** De oude `nu2`-index (`ts ≤ nu < ts+15m`) rendeert
   LEEG in het laatste moment vóór het kwartierpunt, zodra de daglijst
   herberekend is (time_pattern /5 min) en het lopende kwartier nog niet in de
   lijst staat. De sensor ging dan even `unavailable` en de log-automation
   (`not: "unavailable"`) telde die onbekend→bekend-overgangen mee als
   "statuswijziging" → elke 15 min een melding.
   **Fix:** `nu` = laatste entry met `t ≤ nu` (deterministisch, geen gap).
   Dit is ook wat de rest van het dashboard al doet (grafiek + tegels).
   De log-automation-trigger vereist nu een *veelekeer* veranderde status
   (`from` + `to` + `from_is_not: "unavailable"`) — de oude `not`-vorm is
   deprecated en telt onbekend→bekend mee.

2. **Hysterese aan de prijsgrens (tactiek §5).** Het oude gedrag schakelde
   puur op de momentprijs: bij een vlakke prijsspel rond de LADEN-grens
   (`in+w+m ≈ V`) of rond de verkoop-eis (`uit ≈ eis`) tikte de status elk
   kwartier. Nu:
   - **LADEN** ↔ NEUTRAAL: band ±H rond V (H = `input_number.shadow_hysteresis`,
     default 0,005 €/kWh). IN als `in+w+m < V−H`, UIT pas als `in+w+m ≥ V+H`.
   - **COMFORT**: band ±H rond `v_eis` (verkoop-eis = herlaadkosten/η+w+m,
     tactiek rev 3 §stap 6). IN als `uit > v_eis−H`, UIT pas als `uit ≤ v_eis+H`.
     (v1.5.1 gebruikte hier `pv_eis` = min(uit)-zonuren: die drempel is
     gevoeliger en maakt COMFORT afwisselend actief/inactief. De tactiek zegt:
     herlaadkosten (net MIN PV) → v_eis. De pv_eis-loop blijft als S-
     capaciteitsgrens voor de ruimtetak, niet als statusdrempel.)
   - **SPAAR** ↔ LADEN: de R-tak is een SOC-afwijking, geen prijsgrens —
     de hysterese-band is hier de 0-overgang zelf: IN als R2 > 0, UIT pas
     als R2 < 0 (SOC daadwerkelijk onder doel-SOC).
   - **Geheugenknop** `input_text.shadow_vorige_status` (door de log-automation
     gezet na elke wijziging) levert de "vorige status" die de band nodig
     heeft. De sensor leest hem via `states()` tijdens renderen; HA triggert
     op de write → de sensor herberekent ééns met de nieuwe prev.
   - H=0 gedraagt zich als vóór 1.5.2 (alleen de nu2-index-fix is dan nog
     van kracht). Instelbaar via `input_number.shadow_hysteresis` (0–0,05,
     step 0,001, default 0,005).

Nieuwe tests: `test_shadow_yaml_valid.py` (HA-validatie van input_number/
input_text/template + de from/to/from_is_not-combinatie op de log-automation)
en een e2e-scenario in `test_shadow_package.py::test_shadow_hysterese_en_
kwartierindex` dat de hysterese-band (P1→P4: NEUTRAAL→LADEN→LADEN-blijft→
uit-LADEN) en de kwartier-index (in_nu op de juiste entry) nameten.

Installatie: HACS-update + herstart. Het shadow-package wordt door de
installer gesynct (`_sync_shadow_package_sync`); de nieuwe helpers
(`shadow_hysteresis`, `shadow_vorige_status`) verschijnen na de herstart.

## 2026-10-07 — shadow-mode voor de nieuwe accu-handelregel (v1.5.0)
- Nieuw optioneel package `shadow/energyprijs_shadow.yaml` (revisie 3 van
  `roi-monitor/stroomhandel_tactiek.md`):
  - Doel-SOC = 100% − (vandaag_zon + morgen_zon) / capaciteit, geklem 20–100%
  - Ruimetak: SOC boven doel → R; afvoer eerst naar huis (SPAAR), verkoop alleen
    als de verkoop-eis bereikt is (COMFORT), verkoopbaar deel begrensd door min(R,S)
  - V = η × gemiddelde van de N duurste in-prijzen (N=12 default, instelbaar)
  - Laden alleen als in(t) + w + m < V
  - Verkoop-eis over venster t+24u: min(net-herlaad, PV-overschot-herlaad) / η + w + m
  - Vijf bestaande statussen als output: LADEN / OP HET NET / NEUTRAAL / SPAAR / COMFORT
    (incl. "COMFORT (curtail)" bij negatieve uit)
  - Zes input_number-helpers: shadow_eta (0,83), shadow_w (0,025), shadow_m (0,015),
    shadow_n_top (12), shadow_capaciteit (92), shadow_soc_min (20)
- E2E-test in HA-fixture: helpers + sensoren bestaan, doel-SOC-rekening (61,9% op
  S=35/C=92), en vier beslis-scenario's (neutraal / COMFORT bij avondpiek met
  PV-herlaad / SPAAR bij ruimtegebrek zonder marge / curtail bij negatieve uit).
- SHADOW: geen schrijfnaar-omvormer; de automatiek logt alleen via
  persistent_notification. Overname pas na min. 2 weken naast elkaar.
- Installatie (handmatig): `cp shadow/energyprijs_shadow.yaml /config/packages/` +
  herstart. Ziet de oude G1–G4-logica er anders uit na overname? Dat is de bedoeling —
  de nieuwe regel vervangt de vier grenzensensoren door de zes shadow-sensoren.

## 2026-10-07 — verkooplijn volgt saldering direct, structureel (v1.4.3)
- Review van Jan vastgesteld via apexcharts-card-broncode: `set hass()` ververst data
  alléén als er GEEN `update_interval` in de config staat; met "5min" negeerde de kaart
  elke sensor-update tot de timer tikte. Eerdere diagnose ("cached 'uit' loopt achter")
  was onjuist: het daglijst-blok in package.yaml heeft alle contracthelpers al als
  state-trigger en herberekent direct.
- Fix: `update_interval` uit GRAFIEK_CARD (verversing ≈1,5 s na sensor-update),
  verkoop-generator terug naar `e.uit` (één formulebron: package.yaml — de JS-nabouw
  uit 1.4.2 is dubbel boekhouden en terugdraaid), en `time_pattern minutes: /5` in het
  daglijst-triggerblok zodat de state (now().strftime('%H:%M')) periodiek verandert en
  de "nu"-markering blijft lopen.
- Opbouw-check (sleutel-op-sleutel met GRAFIEK_CARD) herkent de nieuwe kaart automatisch
  → bestaande dashboards worden bij de volgende update exact één keer herbouwd.
- Tests: 48 — o.a. geen update_interval, generator zonder hass.states, time_pattern +
  helper-triggers aanwezig.

## 2026-10-07 — verkoop-lijn volgt saldering live (v1.4.2)
- Jan: togglede saldering maar de rode verkoop-lijn bewoog niet. Oorzaak: de data_generator
  las het **cached** `uit`-attribuut van sensor.stroomprijs_daglijst; dat attribuut herberekent
  wel bij helper-wijziging, maar liep bij Jan achter (sensor last_changed ≠ attribute-inhoud).
  Fix: de verkoop-generator nabouwt nu de package-formule `(e.p + sl) × btw + saldering ? bel×btw : 0`
  rechtstreeks tegen `hass.states['input_number.…']`/`input_boolean.…` — browser-JS, live, geen
  Jinja (`states()` bestaat daar níét, skill-regel 1.2.39). Formule in node namegemeten met Jans
  eigen HA-data: off = 0,2779 / on = 0,3888, exact gelijk aan package. Balkjes (inkoop) blijven
  uit cached `in` — die is saldering-onafhankelijk en loopt dus niet achter.

## 2026-10-07 — grafiek op echte prijzen (v1.4.1)
- Jan: "de gebruiker moet altijd zelf rekenen voor de echte prijzen". Balkjes tekenen nu
  de **inkoopprijs all-in** (`e.in`) i.p.v. bruto (`e.p`); eronder een **dun rood lijntje**
  met de verkoopprijs (`e.uit`). Beide series delen één y-as via `yaxis_id: prijzen` —
  géén losse `yas`-configs, want apexcharts v2.2.3's strikte checker + de valkuil uit
  1.2.20-1.2.24 (multi-as-spook) blijven geldig; `disable_config_validation` staat al aan.
- Golden file + beide reeks-tests bijgewerkt (series == 2). Opbouw-check is sleutel-op-
  sleutel met GRAFIEK_CARD → elk bestaand dashboard herbouwt automatisch na de update.

## 2026-10-05 — review v1.3.2 (punten 1–6)
- **Punt 1**: view-selectie was `views[0]` → eigen eerste view van de gebruiker
  kon overschreven of platgeslagen worden. Nu: herkenning op `path == "energie"`,
  legacy één-padloze-view wordt geërfd, anders een nieuwe view achteraan.
- **Punt 2**: `_dashboard_opslaan()` schreef via twee LovelaceStorage-instanties
  op dezelfde storage-key (store + live) → dubbel `lovelace_updated`-event en
  cache-race. Nu één schrijver: live wint, store is terugval; teruglezen gebeurt
  via dezelfde schrijver.
- **Punt 3**: `dashboard_bestaat()` gaf bij een leesfout `False` → elke 5 min een
  herbouw bij een blijvende storage-fout. Nu `True/False/None`; `None` (check
  onuitvoerbaar) slaat over met INFO (max 1×/uur). Timer daalt na succes naar 1 uur.
- **Punt 4**: ongebruikte imports (`asyncio`, `json`, `_cards`), dode variabele
  `totaal`, en — gevonden door ruff — een bestaande crasher: `restart_needed` was
  undefined in `handle_install` (elke install-call met force_restart crashte op
  NameError). Nieuw: GitHub Actions CI met ruff + HA-matrix.
- **Punt 6**: canary-test `test_canary_private_api.py` verifieert dat
  `DashboardsCollection.store` / `_data_to_save` / `async_delay_save(save_func,
  delay)` bestaan en dat create_item + flush door de echte storage-machinery
  roundtript; gedraaid tegen nieuwste én minimum HA uit hacs.json.

## 2026-10-05 — review "verwijderd dashboard" (v1.3.2 eerdere ronde)
- Bestaanscheck uitsluitend op de versie-marker → UI-verwijdering werd nooit
  hersteld. Nu marker + itemcheck op disk, marker-reset bij verwijdering.
- Dashboard werd niet in de LIVE LovelaceData geregistreerd (onze tweede
  collectie heeft geen listeners; HA's `storage_dashboard_changed` draait niet) →
  websocket `config_not_found` tot een herstart. Nu expliciete registratie à la
  core, plus repair-issue `dashboard_live_registratie` als terugval.
- Beslissingen loggen op INFO (startup + timer), diagnose-velden in de services
  (`dashboard_bestaat`, `live_geregistreerd`, `cache_bijgewerkt`, `schrijver`).

## 2026-10-04 — live-log 17:52 (v1.2.x→1.3.0 periode)
- Validaties stonden ná create_item + panel-registratie → gefaalde guard liet een
  leeg dashboard achter. Check nu vóór elke mutatie.
- Event-started races: template-sensoren unknown bij STARTED → bronnen-check is
  warn-only, structuur wordt op domein-niveau getoetst.
- Startup-callback via lambda + async_create_task vanuit executor-thread gaf
  RuntimeError/'coroutine never awaited' → vervangen door `async_at_started`.

## 2026-10-04 — review P2/K3 (config & versie)
- configuration.yaml werd ge-patched met een losse `homeassistant:`-blok onder
  bestaande sleutels (duplicate key, PyYAML zwijgt) → read-only made, de
  install-service schrijft daar niet meer.
- Versiebestanden deden aan eigen nummering → één bron: `const.VERSION` uit
  manifest.
- Verouderde helper `input_number.accu_handmatig_pct` bleef als "niet meer
  beschikbaar" achter → VEROUDERDE_HELPERS-opschoning bij setup.

## 2026-10-04 — accu-contract (v1.2.42/43)
- Triggers-blok op input_* voor de accu-snelkoppeling volgde de SOC-wijziging
  niet (bron-entiteit ontbrak in de trigger) → state-based templates volgen
  dynamisch gelezen entiteiten; triggers-blok alleen voor prijsformules.
- "waarde exact 0" als "nog nooit gezet"-nuance bij defaults; regels voor
  eenmalige default-zetting vastgelegd.
