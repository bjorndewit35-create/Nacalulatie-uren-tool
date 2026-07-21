# Nacalculatie-uren-tool

Een lokale webtool om project-nacalculaties te maken voor Hoevenaars Licht Geluid Video.

- **Stap 1 — Uren bijhouden:** upload maandelijks de urenregistratie-export(s) uit het ERP. Eén bestand met alle medewerkers (elk op een eigen tabblad) mag ook — de tool leest alle tabbladen in één keer. De database groeit per maand; hetzelfde bestand opnieuw uploaden is veilig (geen dubbele regels).
- **Stap 2 — Nacalculatie:** upload de personeelsplanning van één project. De tool zoekt welke **eigen** medewerkers gepland staan, zoekt hun werkelijk gemaakte uren per dag op in de database en geeft een overzicht. Voor korte/deel-functies (bv. *Chauffeur*) wordt de **plantijd** aangehouden in plaats van de hele gewerkte dag.

## Starten

**Windows:** dubbelklik op `run.bat`
**Mac/Linux:** dubbelklik op `run.sh` (of `./run.sh` in een terminal)

De eerste keer installeert het script automatisch alles. Daarna opent de tool op
<http://127.0.0.1:5000>. Open die link in je browser.

> Vereiste: Python 3.10 of nieuwer ([python.org/downloads](https://www.python.org/downloads/),
> op Windows tijdens installatie "Add Python to PATH" aanvinken).

## Hoe het werkt

### Eigen medewerkers herkennen
Een planningregel telt als "eigen medewerker" zodra die naam in de uren-database voorkomt.
Materieel (trailers, bussen) en externen (namen met `*` of `**`) vallen daardoor vanzelf af.
Verschilt een naam tussen planning en uren? Koppel ze via **Instellingen → Naam-aliassen**.

### Uren toekennen
Per planningregel van een eigen medewerker:
- **Plantijd-functie** (instelbaar, standaard *Chauffeur* en *Crew Transport*) → de **plantijd**
  telt, maar **alleen als de geplande shift korter is dan 4 uur**. Is de geplande shift 4 uur of
  langer, dan tellen de werkelijk gewerkte uren van die dag (zoals bij overige functies).
- **Overige functies** → de **werkelijk gewerkte uren** van die dag (kolom `Tijd` uit de
  urenregistratie, pauzes er al af), één keer per medewerker per dag geteld.
- **Korte rit én productiewerk op dezelfde dag** → dan telt alleen de volle gewerkte dag; de
  rit valt daarbinnen en wordt niet apart bijgeteld (voorkomt dubbeltelling in het projecttotaal).

Afwezigheid telt niet mee als gewerkte uren: verlof, ziekte/ziek en dokter/tandarts worden herkend en
uitgesloten (ze blijven wel zichtbaar als opmerking). Het overzicht toont per regel zowel de plantijd,
de werkelijke dag-uren als de toegekende uren, plus opmerkingen, zodat je alles kunt controleren.
Zijn er nog **niet-geaccordeerde** uren meegeteld, dan verschijnt bovenaan een waarschuwing —
die uren kunnen immers nog wijzigen. Exporteer naar Excel of CSV met de knoppen bovenaan het resultaat.

### Uren opzoeken
Wil je alleen per planningregel de werkelijke dag-uren naast elkaar zien (zonder plantijd-correctie)?
Gebruik **Uren opzoeken**. Het resultaat is nu ook te downloaden als Excel of CSV, zodat je het
rechtstreeks in je ERP kunt overnemen zonder overtypen.

### Verkeerd bestand geüpload?
Na een upload zie je per bestand hoeveel medewerkers en welke periode erin zaten, zodat een
verkeerde export meteen opvalt. Onderaan **Stap 1** staat een lijst van geüploade bestanden met een
knop **Verwijderen** waarmee je alle regels van dat bestand in één keer uit de database haalt.

## Gegevens & back-up
Alle data staat lokaal in één SQLite-bestand in je thuismap: `Nacalculatie-uren-data/nacalculatie.db`
(op Windows bijv. `C:\Users\<naam>\Nacalculatie-uren-data\nacalculatie.db`). Dit staat bewust
**buiten** de tool-map, zodat een update of het opnieuw downloaden van de tool je data nooit raakt.
Een oude database in de tool-map (`data/nacalculatie.db`, van eerdere versies) wordt bij de eerste
start automatisch naar de nieuwe locatie gekopieerd.

Een back-up maken kan via de knop **Back-up downloaden** op het dashboard, of kopieer het
database-bestand zelf naar een veilige plek (USB of cloud). Dat ene bestand is je complete database.

## Online gebruiken (zonder lokaal opstarten)
Wil je de tool als een **online link** gebruiken in plaats van hem telkens op je pc te starten? Zie
**[HOSTING.md](HOSTING.md)** voor een gratis stap-voor-stap uitleg (via PythonAnywhere). De link komt
achter een wachtwoord te staan en je database blijft veilig bewaard.

De tool leest hiervoor drie omgevingsvariabelen (allemaal optioneel; lokaal hoef je niets in te stellen):
- `NACALC_DB` — pad naar het databasebestand.
- `NACALC_SECRET` — geheime sleutel voor de sessie.
- `NACALC_USER` + `NACALC_PW` — inlognaam en wachtwoord voor de online link. Alleen als **beide** gezet
  zijn, wordt om een wachtwoord gevraagd; zonder deze twee (lokaal gebruik) is er geen login.

## Ondersteunde bestanden
Zowel `.xls` (oud Excel-formaat, zoals de planning-export) als `.xlsx` worden gelezen, voor beide stappen.

## Voor ontwikkelaars
```
pip install -r requirements.txt pytest
pytest                 # logica-tests
python app.py          # start de server
```
Modules: `parsing.py` (inlezen/normaliseren), `db.py` (SQLite), `nacalculatie.py` (matching/toekenning),
`export.py` (Excel/CSV), `app.py` (Flask-routes).
