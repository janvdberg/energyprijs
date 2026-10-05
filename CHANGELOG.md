# Changelog

Incident-/reviewvermeldingen die eerder als commentaar in de code stonden ("les
live-log 3 okt", "review 4 okt", …). De code bevat alleen nog het *waarom*; de
*wanneer/welke-review* staat hier.

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
