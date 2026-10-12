# Changelog

Incident-/reviewvermeldingen die eerder als commentaar in de code stonden ("les
live-log 3 okt", "review 4 okt", …). De code bevat alleen nog het *waarom*; de
*wanneer/welke-review* staat hier.

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
