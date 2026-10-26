# Review-opdracht: Home Assistant Jinja-template (energyprijs v1.8.1)

Je bent een senior Jinja2 / Home Assistant Template-integrator. Beoordeel de onderstaande
YAML/Jinja-fragmenten uit een template-sensor en antwoord in het Nederlands, feitelijk en
beknopt. Geen algemeenheden; wijs alleen concrete fouten/aannames aan met regelverwijzing.

## Context
- Home Assistant template sensor (YAML), attributen `vandaag`, `morgen` en `morgen_prognose`.
- Doelgedrag (v1.8.1):
  - De accu mag alléén laden in de goedkoopste uren van het ROLLENDE venster.
  - Het laadminimum wordt berekend over álle beschikbare kwartieren van vandaag (`ns_mn.wm`)
    plus de eerste ±6 "voorloopuren" van morgen/prognose (`ns_mn.tm`).
  - Drempel: `min_in = [ns_mn.wm, ns_mn.tm] | min`; `drem = min_in × fractie`
    (`fractie` = input_number, default 1.25).
  - Status per interval: `laden` als `in ≤ drem`, `comfort` als `in ≤ drem + 0.08`, verder `ontladen`.
- All-in-formule (identiek overal): `((p + sa + toel + bel) * btw) | round(4)`;
  `toel` = tijdsafhankelijke toeslag via `ftext`-regex of dal/top-uurval.
- Bekende aannames die ik wil laten checken:
  1. Een namespace-update (`{% set ns.x = ... %}`) binnen een for-lus werkt zoals bedoeld.
  2. `state_attr(eid, 'prices_tomorrow')` kan leeg zijn (`[]`) → alle lussen moeten dan veilig draaien.
  3. In `morgen` is zojuist `ns.eid_tm` toegevoegd (zelfde bronkeuze als in `vandaag`) — klopt de volgorde t.o.v. het gebruik?
  4. `timedelta(hours=6)` vanaf `ns_mn.tmin`: telt dat correct de eerste 6 uuren van de morgendata?
  5. Negatieve prijzen: `ns_mn.wm/tm` starten op 9.0 — is er een geval waarin het minimum nooit lager dan 9.0 komt en de drempel daardoor onrealistisch laag blijft?
  6. Rendement-guard `rt_safe = max(rt, 0.01)` — voldoende tegen deling door nul?

## Validatie-checklist (beantwoord per punt: OK / fout + waarom)
A. Variabelen gedefinieerd vóór gebruik in elke lus (met name `ts/dal_u/top_u/ftext/btw/sa/bel/ns_mn`).
B. Elke `{% for %}`/`{% if %}` correct gesloten; YAML-blokscalares (`>`) niet verbroken.
C. `dict(x, s=...)`-patroon: bewaard het alle oorspronkelijke sleutels (`t/e/p/in/uit/rt/rt_uit`)?
D. Zou dit fragment in HA 2025.x renderen zonder TemplateError? Zo nee: exacte foutmelding verwachten.
E. Logische inconsistenties tussen `vandaag`, `morgen` en `morgen_prognose` (dezelfde formule, andere bronkeuze?).
F. Prestaties: dubbele scans over dezelfde lijst — acceptabel of te vermijden?

## Fragment 1 — attribuut `vandaag` (regels 303–438 van package.yaml)
```jinja
          vandaag: >
            {% set btw = 1 + states('input_number.prijs_btw') | float(0.21) %}
            {% set bel = states('input_number.prijs_energiebelasting') | float(0) %}
            {% set sa = states('input_number.prijs_opslag_afname') | float(0) %}
            {% set sl = states('input_number.prijs_opslag_levering') | float(0) %}
            {% set saldering = states('input_boolean.prijs_saldering_energiebelasting_teruggave') == 'on' %}
            {% set ns = namespace(out=[], eid='') %}
            {% for naam, eid in [('enerprice','sensor.prijzen_bron_enerprice'),
                                 ('nordpool','sensor.prijzen_bron_nordpool'),
                                 ('energyzero','sensor.prijzen_bron_energyzero')] %}
              {% if ns.eid == '' and state_attr(eid, 'prices_today') | default([], true) | count > 0 %}{% set ns.eid = eid %}{% endif %}
            {% endfor %}
            {# v1.8.1: bron voOR de voorloop-scan van de minimumbepaling — morgenvoorsprong
               (echte morgenprijzen; anders de prognose-bron) zodat een laag blok straks
               nachts al meetelt in de fractiegrens. #}
            {% set ns.eid_tm = '' %}
            {% for naam, eid in [('enerprice','sensor.prijzen_bron_enerprice'),
                                 ('nordpool','sensor.prijzen_bron_nordpool'),
                                 ('energyzero','sensor.prijzen_bron_energyzero')] %}
              {% if ns.eid_tm == '' and state_attr(eid, 'prices_tomorrow') | default([], true) | count > 0 %}{% set ns.eid_tm = eid %}{% endif %}
            {% endfor %}
            {% if ns.eid_tm == '' %}{% set ns.eid_tm = 'sensor.prijzen_bron_voorspelling' %}{% endif %}
            {# v1.8.1: accumulators voor het vooruitkijkend minimum (zie scan hieronder) #}
            {% set ns_mn = namespace(wm=9.0, tm=9.0, tmin=None) %}
            {% for i in state_attr(ns.eid_tm, 'prices_tomorrow') | default([], true) %}
              {% if i.time is defined and i.price is defined %}
                {% set dtx = (i.time | as_datetime).astimezone() %}
                {% if ns_mn.tmin is none or dtx < ns_mn.tmin %}{% set ns_mn.tmin = dtx %}{% endif %}
              {% endif %}
            {% endfor %}
            {% set ts = states('input_number.prijs_opslag_tijdsafhankelijk') | float(0) %}
            {% set dal_u = states('input_number.prijs_dal_uren') | int(7) %}
            {% set top_u = states('input_number.prijs_top_uren') | int(17) %}
            {% set ftext = states('input_text.prijs_net_blokken') | default('', true) | trim %}
            {% set rt = states('input_number.rendement_roundtrip_pct') | float(70) / 100 %}
            {# v1.6.2: guard tegen deling door 0 (eerste start: helpers even 0) #}
            {% set rt_safe = [rt, 0.01] | max %}
            {# v1.8.1: laagste all-in over álle beschikbare vandaag-kwartieren in ns_mn.wm.
               Doel: laden = goedkoopste uren van het ROLLENDE venster; álle kwartieren
               tellen mee, niet alleen het huidige. Zelfde formule als hoofd-lus hieronder. #}
            {% for x0 in state_attr(ns.eid, 'prices_today') | default([], true) %}
              {% if x0.time is defined and x0.price is defined %}
                {% set h0 = (x0.time | as_datetime).astimezone().hour %}
                {% set mnd0 = (x0.time | as_datetime).astimezone().month %}
                {% set nsb0 = namespace(f=None) %}
                {% if ftext != '' %}
                  {% for mm in ftext | regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)') %}
                    {% set naam = (mm[0] | upper) if mm[0] else '' %}
                    {% set ss = mm[1] | int(-1) %}
                    {% set ee = mm[2] | int(-1) %}
                    {% set fc = mm[3] | replace(',', '.') | float(-1) %}
                    {% set ok_seis = (naam == '') or (naam == 'Z' and 4 <= mnd0 <= 9) or (naam == 'W' and not (4 <= mnd0 <= 9)) %}
                    {% if ok_seis and ss >= 0 and ee >= 0 and fc >= 0 and (ss <= h0 < ee or (ee <= ss and (h0 >= ss or h0 < ee))) %}
                      {% set nsb0.f = fc %}
                    {% endif %}
                  {% endfor %}
                {% else %}
                  {% set nsb0.f = 1.0 if (h0 < dal_u or h0 >= top_u) else 0.0 %}
                {% endif %}
                {% set toel0 = (ts * nsb0.f) if (ts > 0 and nsb0.f is not none) else 0 %}
                {% set a0 = ((x0.price | float(0) + sa + toel0 + bel) * btw) | round(4) %}
                {% if a0 < ns_mn.wm %}{% set ns_mn.wm = a0 %}{% endif %}
              {% endif %}
            {% endfor %}
            {% for i in state_attr(ns.eid, 'prices_today') | default([], true) %}
              {% if i.time is defined and i.price is defined %}
                {% set p = i.price | float(0) %}
                {# ── tariefcontract 2028: toeslag per lokaal uur; vóór 1-1-2028
                   is ts=0 en valt alles terug op de vaste contract-opslagen ── #}
                {% set h = (i.time | as_datetime).astimezone().hour %}
                {# rt = in/η en rt_uit = uit×η: wat de kWh werkelijk kost/oplevert na
                   omzettingsverlies (rendement-contract); handelen loont pas boven spread/η #}
                {% set mnd = (i.time | as_datetime).astimezone().month %}
                {% set nsb = namespace(f=None) %}
                {% if ftext != '' %}
                  {% for mm in ftext | regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)') %}
                    {% set naam = (mm[0] | upper) if mm[0] else '' %}
                    {% set ss = mm[1] | int(-1) %}
                    {% set ee = mm[2] | int(-1) %}
                    {% set fc = mm[3] | replace(',', '.') | float(-1) %}
                    {% set ok_seis = (naam == '') or (naam == 'Z' and 4 <= mnd <= 9) or (naam == 'W' and not (4 <= mnd <= 9)) %}
                    {% if ok_seis and ss >= 0 and ee >= 0 and fc >= 0 and (ss <= h < ee or (ee <= ss and (h >= ss or h < ee))) %}
                      {% set nsb.f = fc %}
                    {% endif %}
                  {% endfor %}
                {% else %}
                  {% set nsb.f = 1.0 if (h < dal_u or h >= top_u) else 0.0 %}
                {% endif %}
                {% set toel = (ts * nsb.f) if (ts > 0 and nsb.f is not none) else 0 %}
                {% set allin = ((p + sa + toel + bel) * btw) | round(4) %}
                {% set ns.out = ns.out + [{'t': i.time, 'e': (i.time | as_datetime).timestamp() | round(0) | int, 'p': p | round(5),
                    'in': allin,
                    'uit': (((p + sl + toel) * btw + (bel * btw if saldering else 0)) | round(4)),
                    'rt': (allin / rt_safe) | round(4),
                    'rt_uit': ((((p + sl + toel) * btw + (bel * btw if saldering else 0))) * rt) | round(4)}] %}
              {% endif %}
            {% endfor %}
            {# v1.8.1: morgen-VOORLOOP — eerste 6 uur van morgen/prognose door dezelfde
               all-in-formule; minimum in ns_mn.tm. Zo telt een laag blok dat straks
               nachts begint al mee in de fractiegrens van vandaag. #}
            {% for i in state_attr(ns.eid_tm, 'prices_tomorrow') | default([], true) %}
              {% if i.time is defined and i.price is defined %}
                {% set dtx = (i.time | as_datetime).astimezone() %}
                {% if ns_mn.tmin is not none and (dtx - ns_mn.tmin) < timedelta(hours=6) %}
                  {% set px = i.price | float(0) %}
                  {% set hx = dtx.hour %}
                  {% set mndx = dtx.month %}
                  {% set nsb2 = namespace(f=None) %}
                  {% if ftext != '' %}
                    {% for mm in ftext | regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)') %}
                      {% set naam = (mm[0] | upper) if mm[0] else '' %}
                      {% set ss = mm[1] | int(-1) %}
                      {% set ee = mm[2] | int(-1) %}
                      {% set fc = mm[3] | replace(',', '.') | float(-1) %}
                      {% set ok_seis = (naam == '') or (naam == 'Z' and 4 <= mndx <= 9) or (naam == 'W' and not (4 <= mndx <= 9)) %}
                      {% if ok_seis and ss >= 0 and ee >= 0 and fc >= 0 and (ss <= hx < ee or (ee <= ss and (hx >= ss or hx < ee))) %}
                        {% set nsb2.f = fc %}
                      {% endif %}
                    {% endfor %}
                  {% else %}
                    {% set nsb2.f = 1.0 if (hx < dal_u or hx >= top_u) else 0.0 %}
                  {% endif %}
                  {% set toelx = (ts * nsb2.f) if (ts > 0 and nsb2.f is not none) else 0 %}
                  {% set allin_x = ((px + sa + toelx + bel) * btw) | round(4) %}
                  {% if allin_x < ns_mn.tm %}{% set ns_mn.tm = allin_x %}{% endif %}
                {% endif %}
              {% endif %}
            {% endfor %}
            {# v1.8.0/1.8.1: laden = goedkoopste uren van het ROLLENDE venster (geen
               vaste drempel): grens = fractie × minimum over alle beschikbare kwartieren
               van vandaag + eerste 6 voorloopuren morgen; comfort-grens blijft +€0,08. #}
            {% set fr = states('input_number.prijs_laad_fractie') | float(1.25) %}
            {% set min_in = [ns_mn.wm, ns_mn.tm] | min %}
            {% set drem = (min_in * fr) | round(4) %}
            {% set ns2 = namespace(fin=[]) %}{% for x in ns.out %}{% set ns2.fin = ns2.fin + [dict(x, s=('laden' if x['in'] <= drem else ('comfort' if x['in'] <= drem + 0.08 else 'ontladen')))] %}{% endfor %}
            {{ ns2.fin }}
```

## Fragment 2 — attributen `morgen` + `morgen_prognose` (regels 439–632)
```jinja
          morgen: >
            {% set btw = 1 + states('input_number.prijs_btw') | float(0.21) %}
            {% set bel = states('input_number.prijs_energiebelasting') | float(0) %}
            {% set sa = states('input_number.prijs_opslag_afname') | float(0) %}
            {% set sl = states('input_number.prijs_opslag_levering') | float(0) %}
            {% set saldering = states('input_boolean.prijs_saldering_energiebelasting_teruggave') == 'on' %}
            {% set ns = namespace(out=[], eid='') %}
            {% for naam, eid in [('enerprice','sensor.prijzen_bron_enerprice'),
                                 ('nordpool','sensor.prijzen_bron_nordpool'),
                                 ('energyzero','sensor.prijzen_bron_energyzero')] %}
              {% if ns.eid == '' and state_attr(eid, 'prices_tomorrow') | default([], true) | count > 0 %}{% set ns.eid = eid %}{% endif %}
            {% endfor %}
            {# v1.8.1: eid_tm voor de VOORLOOP-scan hieronder — zelfde bronkeuze als
               in 'vandaag': echte morgenprijzen; anders de prognose-bron. #}
            {% set ns.eid_tm = '' %}
            {% for naam, eid in [('enerprice','sensor.prijzen_bron_enerprice'),
                                 ('nordpool','sensor.prijzen_bron_nordpool'),
                                 ('energyzero','sensor.prijzen_bron_energyzero')] %}
              {% if ns.eid_tm == '' and state_attr(eid, 'prices_tomorrow') | default([], true) | count > 0 %}{% set ns.eid_tm = eid %}{% endif %}
            {% endfor %}
            {% if ns.eid_tm == '' %}{% set ns.eid_tm = 'sensor.prijzen_bron_voorspelling' %}{% endif %}
            {% set ts = states('input_number.prijs_opslag_tijdsafhankelijk') | float(0) %}
            {% set dal_u = states('input_number.prijs_dal_uren') | int(7) %}
            {% set top_u = states('input_number.prijs_top_uren') | int(17) %}
            {% set ftext = states('input_text.prijs_net_blokken') | default('', true) | trim %}
            {% set rt = states('input_number.rendement_roundtrip_pct') | float(70) / 100 %}
            {# v1.6.2: guard tegen deling door 0 (eerste start: helpers even 0) #}
            {% set rt_safe = [rt, 0.01] | max %}
            {% for i in state_attr(ns.eid, 'prices_tomorrow') | default([], true) %}
              {% if i.time is defined and i.price is defined %}
                {% set p = i.price | float(0) %}
                {# ── tariefcontract 2028: toeslag per lokaal uur; vóór 1-1-2028
                   is ts=0 en valt alles terug op de vaste contract-opslagen ── #}
                {% set h = (i.time | as_datetime).astimezone().hour %}
                {# rt = in/η en rt_uit = uit×η: wat de kWh werkelijk kost/oplevert na
                   omzettingsverlies (rendement-contract); handelen loont pas boven spread/η #}
                {% set mnd = (i.time | as_datetime).astimezone().month %}
                {% set nsb = namespace(f=None) %}
                {% if ftext != '' %}
                  {% for mm in ftext | regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)') %}
                    {% set naam = (mm[0] | upper) if mm[0] else '' %}
                    {% set ss = mm[1] | int(-1) %}
                    {% set ee = mm[2] | int(-1) %}
                    {% set fc = mm[3] | replace(',', '.') | float(-1) %}
                    {% set ok_seis = (naam == '') or (naam == 'Z' and 4 <= mnd <= 9) or (naam == 'W' and not (4 <= mnd <= 9)) %}
                    {% if ok_seis and ss >= 0 and ee >= 0 and fc >= 0 and (ss <= h < ee or (ee <= ss and (h >= ss or h < ee))) %}
                      {% set nsb.f = fc %}
                    {% endif %}
                  {% endfor %}
                {% else %}
                  {% set nsb.f = 1.0 if (h < dal_u or h >= top_u) else 0.0 %}
                {% endif %}
                {% set toel = (ts * nsb.f) if (ts > 0 and nsb.f is not none) else 0 %}
                {% set allin = ((p + sa + toel + bel) * btw) | round(4) %}
                {% set ns.out = ns.out + [{'t': i.time, 'e': (i.time | as_datetime).timestamp() | round(0) | int, 'p': p | round(5),
                    'in': allin,
                    'uit': (((p + sl + toel) * btw + (bel * btw if saldering else 0)) | round(4)),
                    'rt': (allin / rt_safe) | round(4),
                    'rt_uit': ((((p + sl + toel) * btw + (bel * btw if saldering else 0))) * rt) | round(4)}] %}
              {% endif %}
            {% endfor %}
            {# v1.8.1: morgen-VOORLOOP — eerste 6 uur van morgen/prognose door dezelfde
               all-in-formule; minimum in ns_mn.tm. Zo telt een laag blok dat straks
               nachts begint al mee in de fractiegrens van vandaag. #}
            {% for i in state_attr(ns.eid_tm, 'prices_tomorrow') | default([], true) %}
              {% if i.time is defined and i.price is defined %}
                {% set dtx = (i.time | as_datetime).astimezone() %}
                {% if ns_mn.tmin is not none and (dtx - ns_mn.tmin) < timedelta(hours=6) %}
                  {% set px = i.price | float(0) %}
                  {% set hx = dtx.hour %}
                  {% set mndx = dtx.month %}
                  {% set nsb2 = namespace(f=None) %}
                  {% if ftext != '' %}
                    {% for mm in ftext | regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)') %}
                      {% set naam = (mm[0] | upper) if mm[0] else '' %}
                      {% set ss = mm[1] | int(-1) %}
                      {% set ee = mm[2] | int(-1) %}
                      {% set fc = mm[3] | replace(',', '.') | float(-1) %}
                      {% set ok_seis = (naam == '') or (naam == 'Z' and 4 <= mndx <= 9) or (naam == 'W' and not (4 <= mndx <= 9)) %}
                      {% if ok_seis and ss >= 0 and ee >= 0 and fc >= 0 and (ss <= hx < ee or (ee <= ss and (hx >= ss or hx < ee))) %}
                        {% set nsb2.f = fc %}
                      {% endif %}
                    {% endfor %}
                  {% else %}
                    {% set nsb2.f = 1.0 if (hx < dal_u or hx >= top_u) else 0.0 %}
                  {% endif %}
                  {% set toelx = (ts * nsb2.f) if (ts > 0 and nsb2.f is not none) else 0 %}
                  {% set allin_x = ((px + sa + toelx + bel) * btw) | round(4) %}
                  {% if allin_x < ns_mn.tm %}{% set ns_mn.tm = allin_x %}{% endif %}
                {% endif %}
              {% endif %}
            {% endfor %}
            {# v1.8.0/1.8.1: laden = goedkoopste uren van het ROLLENDE venster (geen
               vaste drempel): grens = fractie × minimum over alle beschikbare kwartieren
               van vandaag + eerste 6 voorloopuren morgen; comfort-grens blijft +€0,08. #}
            {% set fr = states('input_number.prijs_laad_fractie') | float(1.25) %}
            {% set min_in = [ns_mn.wm, ns_mn.tm] | min %}
            {% set drem = (min_in * fr) | round(4) %}
            {% set ns2 = namespace(fin=[]) %}{% for x in ns.out %}{% set ns2.fin = ns2.fin + [dict(x, s=('laden' if x['in'] <= drem else ('comfort' if x['in'] <= drem + 0.08 else 'ontladen')))] %}{% endfor %}
            {{ ns2.fin }}
          # ── v1.7.0 MORGEN_PROGNOSE: INFORMATIEFE vervanger voor het EPEX-gat ──
          #    (±00:00–14:10). Bewust een APART attribuut: 'morgen' blijft alleen
          #    echte prijzen, dus elke beslissingslezer (shadowPIES) en de
          #    15:15-melding blijven blind voor de prognose. Formules identiek aan
          #    'morgen'; bron = de ECHTE bron-sensoren (EnerPrice/NordPool/
          #    EnergyZero), zelfstandig herberekend — géén eigen 'morgen'-attribuut
          #    (dat zou een 1-5 min vertraging geven rond 15:15). Leeg als er al
          #    echte morgenprijzen zijn → de kaart tekent dan geen grijze balken.
          morgen_prognose: >
            {# v1.7.0 (review pass 2): lees de VOORSPELLING-bron (prognose),
               niet de eigen 'morgen'-attribuut. De "is er al echte morgen?"
               test checkt de ECHTE bronnen (EnerPrice/NordPool/EnergyZero)
               zelfstandig — géén 1-5 min overlap rond 15:15. Als een echte
               bron AL morgen-prijzen heeft → leeg (geen grijze balken). #}
            {% set btw = 1 + states('input_number.prijs_btw') | float(0.21) %}
            {% set bel = states('input_number.prijs_energiebelasting') | float(0) %}
            {% set sa = states('input_number.prijs_opslag_afname') | float(0) %}
            {% set sl = states('input_number.prijs_opslag_levering') | float(0) %}
            {% set saldering = states('input_boolean.prijs_saldering_energiebelasting_teruggave') == 'on' %}
            {% set ts = states('input_number.prijs_opslag_tijdsafhankelijk') | float(0) %}
            {% set dal_u = states('input_number.prijs_dal_uren') | int(7) %}
            {% set top_u = states('input_number.prijs_top_uren') | int(17) %}
            {% set ftext = states('input_text.prijs_net_blokken') | default('', true) | trim %}
            {% set rt = states('input_number.rendement_roundtrip_pct') | float(70) / 100 %}
            {% set rt_safe = [rt, 0.01] | max %}
            {# "Is er al echte morgen?" — check de ECHTE bronnen direct, niet
               het eigen 'morgen'-attribuut (dat zou 1-5 min vertraging geven). #}
            {% set echte_ns = namespace(echte_eid='') %}
            {# v1.7.2: lijst-bewuste check — de placeholder-bronnen (Nordpool/
               EnergyZero) droegen de STRING '[]' als attribute; die is een
               sequence van 2 tekens, dus | count > 0 was waar → echte-eid
               vond de string-bron, morgen_prognose rendert '[]'. is sequence
               + not string sloopt de string-check. #}
            {% for naam, eid in [('enerprice','sensor.prijzen_bron_enerprice'),
                                 ('nordpool','sensor.prijzen_bron_nordpool'),
                                 ('energyzero','sensor.prijzen_bron_energyzero')] %}
              {% set pt = state_attr(eid, 'prices_tomorrow') | default([], true) %}
              {% if echte_ns.echte_eid == '' and pt is sequence and pt is not string and pt | count > 0 %}{% set echte_ns.echte_eid = eid %}{% endif %}
            {% endfor %}
            {% if echte_ns.echte_eid != '' %}
            {{ [] }}
            {% else %}
            {% set ns = namespace(out=[]) %}
            {# v1.7.0 datumfilter: alleen punten van MORGEN (lokaal) renderen —
               voorkomt dat een oude dag's prognose onder "vandaag" wordt getekend. #}
            {% set morgen_datum = (now() + timedelta(days=1)).date() %}
            {% for i in state_attr('sensor.prijzen_bron_voorspelling', 'prices_tomorrow')
                       | default([], true) %}
              {% if i.time is defined and i.price is defined %}
                {% set dt = i.time | as_datetime %}
                {% set _skip = morgen_datum is not none and dt.date() != morgen_datum %}
                {# Ruwe datum van het punt (offset behouden — as_datetime
                   slaat HA's lokale tz af) vergelijken met de lokaal-berekende
                   morgen. .astimezone() mag hier NIET: die convert naar HA's
                   lokale tz en sloop in NL de eerste/laatste uurtjes weg. #}
                {% if not _skip %}
                {% set p = i.price | float(0) %}
                {% set h = dt.hour %}
                {% set mnd = dt.month %}
                {% set nsb = namespace(f=None) %}
                {% if ftext != '' %}
                  {% for mm in ftext | regex_findall('([WZ])?\|?(\d{1,2})\s*-\s*(\d{1,2})\s*:\s*(\d+(?:[.,]\d+)?)') %}
                    {% set naam = (mm[0] | upper) if mm[0] else '' %}
                    {% set ss = mm[1] | int(-1) %}
                    {% set ee = mm[2] | int(-1) %}
                    {% set fc = mm[3] | replace(',', '.') | float(-1) %}
                    {% set ok_seis = (naam == '') or (naam == 'Z' and 4 <= mnd <= 9) or (naam == 'W' and not (4 <= mnd <= 9)) %}
                    {% if ok_seis and ss >= 0 and ee >= 0 and fc >= 0 and (ss <= h < ee or (ee <= ss and (h >= ss or h < ee))) %}
                      {% set nsb.f = fc %}
                    {% endif %}
                  {% endfor %}
                {% else %}
                  {% set nsb.f = 1.0 if (h < dal_u or h >= top_u) else 0.0 %}
                {% endif %}
                {% set toel = (ts * nsb.f) if (ts > 0 and nsb.f is not none) else 0 %}
                {% set allin = ((p + sa + toel + bel) * btw) | round(4) %}
                {% set ns.out = ns.out + [{'t': i.time, 'e': dt.timestamp() | round(0) | int, 'p': p | round(5),
                    'in': allin,
                    'uit': (((p + sl + toel) * btw + (bel * btw if saldering else 0)) | round(4)),
                    'rt': (allin / rt_safe) | round(4),
                    'rt_uit': ((((p + sl + toel) * btw + (bel * btw if saldering else 0))) * rt) | round(4)}] %}
                {% endif %}
              {% endif %}
            {% endfor %}
            {# v1.8.0: ook de prognose kent geen vaste drempel: laden = ≤ fractie ×
               laagste VOORSPELDE all-in-uur. Default hier wat ruimer (1,40), want
               het minimum is in deze lijst zelf nog een schatting. #}
            {% set fr = states('input_number.prijs_laad_fractie') | float(1.4) %}
            {% set min_in = ns.out | map(attribute='in') | sort | first | default(9) %}
            {% set drem = (min_in * fr) | round(4) %}
            {% set ns2 = namespace(fin=[]) %}{% for x in ns.out %}{% set ns2.fin = ns2.fin + [dict(x, s=('laden' if x['in'] <= drem else ('comfort' if x['in'] <= drem + 0.08 else 'ontladen')))] %}{% endfor %}
            {{ ns2.fin }}
            {% endif %}
```

## Outputformat
1. Per checklistpunt A–F één regel bevinding.
2. Daarna: prioriteitslijst van echte bugs (als die er zijn), elk met minimaal voorstel tot fix.
3. Tot slot: één zin advies of het ontwerp "laden = goedkoopste uren van het rollende venster"
   met deze structuur robuust genoeg is, of dat er een eenvoudiger patroon bestaat binnen HA-template-sensoren.

Geen credentials/API's in dit bestand; alle entity-IDs zijn lokaal gegenereerde namen.
