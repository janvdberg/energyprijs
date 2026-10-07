# Changelog

Incident-/reviewvermeldingen die eerder als commentaar in de code stonden ("les
live-log 3 okt", "review 4 okt", …). De code bevat alleen nog het *waarom*; de
*wanneer/welke-review* staat hier.

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
