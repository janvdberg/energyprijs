# Energyprijs — stroomprijs-package installer

Eén service-call installeert het complete stroomprijs-package in Home Assistant:

- **3 bronnen** met kruiscontrole: Nord Pool, EnerPrice, EnergyZero
- **Bruto basisprijs** (mediaan van ≥2 verse bronnen, 15-min-klaar)
- **All-in afname/levering** met invoervelden (btw, energiebelasting, opslagen)
- **Kruiscontrole-meldingen** bij bronuitval of afwijking
- **2027-bestendig**: saldering weg? Zet één schakelaar om

## Installatie (3 stappen)

1. **HACS → ⋮ (drie puntjes) → Custom repositories →**
   repository-URL invullen → type **Integration** → **Add**.
2. Zoek **Energyprijs** in HACS → **Download**.
3. **Herstart Home Assistant** (nodig om de integratie te laden).

Daarna:

4. Bel de service (via Developer Tools → YAML → Services):

   ```yaml
   service: energyprijs.install
   data: {}
   ```

   of optioneel met directe herstart:

   ```yaml
   service: energyprijs.install
   data:
     force_restart: true
   ```

5. Controleer het resultaat (Developer Tools → YAML → Services):

   ```yaml
   service: energyprijs.status
   data: {}
   ```

## Wat doet de installer?

| Stap | Actie |
|---|---|
| 1 | `package.yaml` → `/config/packages/energyprijs.yaml` |
| 2 | `configuration.yaml`: voegt `homeassistant: packages: !include_dir_named packages` toe (alleen als die nog ontbreekt) |
| 3 | Meldt of een herstart nodig is (of forceert die met `force_restart: true`) |

Het package zelf is *niet* ingebed in automatiseringen — het levert sensoren,
helpers en waarschuwingsautomatiseringen. Verwijderen = bestand weg + herstart.

## Benodigde integraties

- **Nord Pool** (core)
- **EnerPrice** (HACS) — *extended attributes* aanzetten in de opties
- **EnergyZero** (core)
- Notificatie-service `notify.home` (pas de naam aan in het package als je
  een andere Telegram-notify hebt)

## Na installatie

Zie de comments in `/config/packages/energyprijs.yaml` — daar staat de
controlelijst (entiteiten-check, notify-naam, saldering-schakelaar voor 2027).
