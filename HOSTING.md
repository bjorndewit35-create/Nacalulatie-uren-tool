# De tool online zetten (gratis, via PythonAnywhere)

Zo maak je van de tool een online link — dan hoef je niets meer op je eigen pc op te starten.
Je gaat naar `https://<jouwnaam>.pythonanywhere.com`, logt in met een wachtwoord, en gebruikt
de tool precies zoals lokaal. Je database blijft veilig bewaard, ook na updates.

> **Kosten:** gratis. Enige "gedoe": PythonAnywhere stuurt je ~1× per maand een mailtje met een
> knop om de app te verlengen. Klik je die, dan blijft hij live. Wil je dat niet, dan haalt hun
> **Hacker-plan (~$5/mnd)** die verlengknop weg.

---

## Stap 1 — Account aanmaken
1. Ga naar **[www.pythonanywhere.com](https://www.pythonanywhere.com)** → **Pricing & signup** →
   **Create a Beginner account** (gratis).
2. Kies een gebruikersnaam — die wordt je webadres: `https://<gebruikersnaam>.pythonanywhere.com`.

## Stap 2 — De tool ophalen
1. Op het **Dashboard** → open een **Bash console** (onder "New console" → *Bash*).
2. Typ (of plak) en druk Enter:
   ```
   git clone https://github.com/bjorndewit35-create/nacalulatie-uren-tool.git
   ```

## Stap 3 — Benodigdheden installeren
Nog steeds in dezelfde Bash-console:
```
mkvirtualenv --python=python3.11 nacalc
pip install -r nacalulatie-uren-tool/requirements.txt
```
Dit duurt een halve minuut. Onthoud de naam **nacalc** (dat is je "virtualenv").

## Stap 4 — De webapp aanmaken
1. Ga bovenaan naar de **Web**-tab → **Add a new web app** → **Next**.
2. Kies **Manual configuration** (NIET "Flask") → **Python 3.11** → **Next**.
3. Je komt op de configuratiepagina van je web-app.
4. Zoek het kopje **Virtualenv** en vul in:
   ```
   /home/<gebruikersnaam>/.virtualenvs/nacalc
   ```
   (vervang `<gebruikersnaam>` door de jouwe.)

## Stap 5 — De instellingen invullen (WSGI-bestand)
1. Op diezelfde Web-pagina, onder **Code**, staat een link naar het **WSGI configuration file**
   (iets als `/var/www/<gebruikersnaam>_pythonanywhere_com_wsgi.py`). Klik erop.
2. **Wis de volledige inhoud** en zet er dit voor in de plaats (pas de vier waarden aan):
   ```python
   import os
   os.environ["NACALC_DB"] = "/home/<gebruikersnaam>/Nacalculatie-uren-data/nacalculatie.db"
   os.environ["NACALC_SECRET"] = "verzin-hier-een-lange-willekeurige-tekst"
   os.environ["NACALC_USER"] = "kies-een-inlognaam"
   os.environ["NACALC_PW"] = "kies-een-sterk-wachtwoord"

   import sys
   pad = "/home/<gebruikersnaam>/nacalulatie-uren-tool"
   if pad not in sys.path:
       sys.path.insert(0, pad)

   from app import app as application
   ```
   - `NACALC_USER` + `NACALC_PW` zijn je **inlognaam en wachtwoord** voor de online link.
     Zonder deze twee zou de link voor iedereen open staan — vul ze dus altijd in.
   - `NACALC_SECRET` mag elke lange willekeurige tekst zijn (gewoon wat toetsaanslagen).
3. Klik **Save** (rechtsboven).

## Stap 6 — Starten
1. Ga terug naar de **Web**-tab → klik de grote groene knop **Reload**.
2. Open **`https://<gebruikersnaam>.pythonanywhere.com`** → je krijgt een inlogvenster →
   vul je `NACALC_USER` en `NACALC_PW` in → de tool verschijnt. Klaar! 🎉

---

## Je bestaande gegevens meenemen
Heb je lokaal al uren ingevoerd? Neem ze in één keer mee:
1. Op je pc staat je database in de map **`Nacalculatie-uren-data`** in je thuismap
   (het bestand `nacalculatie.db`).
2. In PythonAnywhere → **Files**-tab → maak (indien nodig) de map `Nacalculatie-uren-data` aan →
   **Upload a file** → kies je `nacalculatie.db`.
3. **Reload** op de Web-tab. Al je uren staan nu online.

Geen zin in uploaden? Je kunt ook gewoon je maand-Excelbestanden opnieuw uploaden in de online tool —
dubbele regels ontstaan niet (de import is idempotent).

## Een update ophalen (als de tool verbeterd wordt)
1. **Bash console** →
   ```
   cd nacalulatie-uren-tool
   git pull
   ```
2. **Web**-tab → **Reload**.

Je database staat buiten de projectmap, dus een update raakt je gegevens nooit.

## Veelgestelde vragen
- **Is mijn data veilig?** De link zit achter een wachtwoord en draait over HTTPS. Het gaat om
  werknemersgegevens, dus deel het wachtwoord alleen met wie het nodig heeft en kies een sterk wachtwoord.
- **De app is "verlopen".** PythonAnywhere mailt je ~maandelijks; klik de verlengknop in die mail
  (of op de Web-tab) en klik **Reload**. Het Hacker-plan (~$5/mnd) haalt dit weg.
- **Back-up.** De back-up-knop op het dashboard werkt ook online: je downloadt dan je complete
  database als één bestand. Doe dat af en toe voor de zekerheid.
