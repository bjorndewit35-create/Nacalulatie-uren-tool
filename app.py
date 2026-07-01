"""Flask-webapp voor de nacalculatie-uren-tool (lokaal te draaien)."""
import datetime
import os
import tempfile
import uuid

from flask import (
    Flask, flash, redirect, render_template, request, send_file, url_for,
)

import db
import export
from nacalculatie import _datum_nl, bereken_nacalculatie, zoek_werkelijke_uren
from parsing import (
    min_naar_hhmm, min_naar_uur, normaliseer_naam, parse_planning,
    parse_urenregistratie,
)

BASIS = os.path.dirname(os.path.abspath(__file__))


def _standaard_db_pad():
    return os.path.join(os.path.expanduser("~"), "Nacalculatie-uren-data", "nacalculatie.db")


DB_PATH = os.environ.get("NACALC_DB", _standaard_db_pad())
# Verhuis een oude database (in de app-map) eenmalig naar de vaste locatie.
db.migreer_db(os.path.join(BASIS, "data", "nacalculatie.db"), DB_PATH)
TOEGESTANE_EXT = {".xls", ".xlsx", ".xlsm"}
MAAND_NAMEN = ["jan", "feb", "mrt", "apr", "mei", "jun",
               "jul", "aug", "sep", "okt", "nov", "dec"]

app = Flask(__name__)
app.secret_key = os.environ.get("NACALC_SECRET", "lokale-nacalculatie-tool")

# Resultaten van een nacalculatie tijdelijk bewaren voor de download-knoppen.
# Single-user lokale app, dus een eenvoudige in-memory cache volstaat.
_resultaten = {}
_opzoek_resultaten = {}


def conn():
    return db.get_conn(DB_PATH)


@app.template_filter("hhmm")
def _hhmm(m):
    return min_naar_hhmm(m)


@app.template_filter("uur")
def _uur(m):
    return min_naar_uur(m)


def _ext_ok(naam):
    return os.path.splitext(naam)[1].lower() in TOEGESTANE_EXT


def _verwerk_upload(bestand, parser):
    """Slaat een upload tijdelijk op, parset het en ruimt op."""
    suffix = os.path.splitext(bestand.filename)[1].lower()
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        bestand.save(tmp)
        return parser(tmp)
    finally:
        os.remove(tmp)


@app.route("/")
def index():
    c = conn()
    try:
        return render_template("index.html", status=db.db_status(c), db_pad=DB_PATH)
    finally:
        c.close()


@app.route("/backup")
def backup():
    if not os.path.exists(DB_PATH):
        flash("Nog geen database om te back-uppen.", "fout")
        return redirect(url_for("index"))
    datum = datetime.date.today().isoformat()
    return send_file(
        DB_PATH, as_attachment=True,
        download_name=f"nacalculatie-backup-{datum}.db",
        mimetype="application/octet-stream",
    )


@app.route("/uren", methods=["GET", "POST"])
def uren():
    c = conn()
    try:
        if request.method == "POST":
            bestanden = [b for b in request.files.getlist("bestanden") if b and b.filename]
            if not bestanden:
                flash("Geen bestand gekozen.", "fout")
                return redirect(url_for("uren"))

            totaal_toe = totaal_bij = 0
            verwerkt = []
            for b in bestanden:
                if not _ext_ok(b.filename):
                    flash(f"Overgeslagen (geen Excel-bestand): {b.filename}", "fout")
                    continue
                try:
                    records = _verwerk_upload(b, parse_urenregistratie)
                except Exception as e:  # noqa: BLE001 - gebruiker moet de fout zien
                    flash(f"Fout bij lezen van {b.filename}: {e}", "fout")
                    continue
                if not records:
                    flash(f"Geen urenregels gevonden in {b.filename}.", "fout")
                    continue
                try:
                    toe, bij = db.import_uren(c, records, b.filename)
                except Exception as e:  # noqa: BLE001
                    flash(f"Fout bij opslaan van {b.filename}: {e}", "fout")
                    continue
                mdw_count = len({r["werknemer_norm"] for r in records})
                datums = [r["datum"] for r in records if r["datum"]]
                periode = (
                    f"{_datum_nl(min(datums))} t/m {_datum_nl(max(datums))}"
                    if datums else "geen datums"
                )
                totaal_toe += toe
                totaal_bij += bij
                verwerkt.append(b.filename)
                flash(
                    f"{b.filename}: {mdw_count} medewerker(s), {periode} — "
                    f"{toe} nieuw, {bij} bijgewerkt.",
                    "ok",
                )

            if len(verwerkt) > 1:
                flash(
                    f"Totaal: {totaal_toe} nieuwe regels, {totaal_bij} bijgewerkt "
                    f"(uit {len(verwerkt)} bestanden).",
                    "ok",
                )
            return redirect(url_for("uren"))

        return render_template(
            "upload_uren.html",
            status=db.db_status(c),
            medewerkers=db.medewerker_namen(c),
            uploads=db.uploads_overzicht(c),
        )
    finally:
        c.close()


@app.route("/uren/verwijder", methods=["POST"])
def uren_verwijder():
    bron = request.form.get("bron_bestand")
    if not bron:
        flash("Geen bestand opgegeven.", "fout")
        return redirect(url_for("uren"))
    c = conn()
    try:
        aantal = db.verwijder_upload(c, bron)
        if aantal:
            flash(f"{aantal} regels van '{bron}' verwijderd.", "ok")
        else:
            flash(f"Niets gevonden voor '{bron}'.", "fout")
    finally:
        c.close()
    return redirect(url_for("uren"))


@app.route("/uren/overzicht")
def uren_overzicht():
    c = conn()
    try:
        werknemer_norm = request.args.get("medewerker") or None
        van = request.args.get("van") or None
        tot = request.args.get("tot") or None
        regels = db.uren_overzicht(c, werknemer_norm, van, tot)
        totaal_min = sum(r["tijd_minuten"] or 0 for r in regels)
        return render_template(
            "uren_overzicht.html",
            regels=regels,
            medewerkers=db.medewerker_namen(c),
            geselecteerd=werknemer_norm,
            van=van or "",
            tot=tot or "",
            totaal_min=totaal_min,
            status=db.db_status(c),
        )
    finally:
        c.close()


@app.route("/maandoverzicht")
def maandoverzicht():
    c = conn()
    try:
        jaren = db.beschikbare_jaren(c)
        huidig = str(datetime.date.today().year)
        gekozen = request.args.get("jaar") or (
            huidig if huidig in jaren else (jaren[0] if jaren else huidig))
        return render_template(
            "maandoverzicht.html",
            jaren=jaren, gekozen=gekozen,
            rijen=db.maand_dekking(c, gekozen),
            maand_namen=MAAND_NAMEN, status=db.db_status(c),
        )
    finally:
        c.close()


@app.route("/uren-opzoeken", methods=["GET", "POST"])
def uren_opzoeken():
    c = conn()
    try:
        if request.method == "POST":
            bestand = request.files.get("planning")
            if not bestand or not bestand.filename:
                flash("Geen bestand gekozen.", "fout")
                return redirect(url_for("uren_opzoeken"))
            if not _ext_ok(bestand.filename):
                flash("Kies een .xls of .xlsx bestand.", "fout")
                return redirect(url_for("uren_opzoeken"))
            try:
                regels = _verwerk_upload(bestand, parse_planning)
            except Exception as e:  # noqa: BLE001
                flash(f"Fout bij lezen van het bestand: {e}", "fout")
                return redirect(url_for("uren_opzoeken"))
            if not regels:
                flash("Geen regels gevonden in dit bestand.", "fout")
                return redirect(url_for("uren_opzoeken"))
            resultaat = zoek_werkelijke_uren(c, regels)
            token = uuid.uuid4().hex
            _opzoek_resultaten[token] = resultaat
            return render_template(
                "uren_opzoeken.html", resultaat=resultaat, token=token,
                status=db.db_status(c),
            )
        return render_template(
            "uren_opzoeken.html", resultaat=None, token=None, status=db.db_status(c)
        )
    finally:
        c.close()


@app.route("/uren-opzoeken/export/<token>.<fmt>")
def opzoek_export(token, fmt):
    resultaat = _opzoek_resultaten.get(token)
    if not resultaat:
        flash("Resultaat verlopen, zoek de uren opnieuw op.", "fout")
        return redirect(url_for("uren_opzoeken"))
    if fmt == "xlsx":
        return send_file(
            export.plat_naar_xlsx(resultaat), as_attachment=True,
            download_name="uren-opzoeken.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "csv":
        return send_file(
            export.plat_naar_csv(resultaat), as_attachment=True,
            download_name="uren-opzoeken.csv", mimetype="text/csv",
        )
    flash("Onbekend exportformaat.", "fout")
    return redirect(url_for("uren_opzoeken"))


@app.route("/nacalculatie", methods=["GET", "POST"])
def nacalculatie():
    c = conn()
    try:
        if request.method == "POST":
            bestand = request.files.get("planning")
            projectnaam = (request.form.get("projectnaam") or "").strip()
            if not bestand or not bestand.filename:
                flash("Geen planningbestand gekozen.", "fout")
                return redirect(url_for("nacalculatie"))
            if not _ext_ok(bestand.filename):
                flash("Kies een .xls of .xlsx bestand.", "fout")
                return redirect(url_for("nacalculatie"))

            try:
                regels = _verwerk_upload(bestand, parse_planning)
            except Exception as e:  # noqa: BLE001
                flash(f"Fout bij lezen van de planning: {e}", "fout")
                return redirect(url_for("nacalculatie"))

            if not regels:
                flash("Geen planningregels gevonden in dit bestand.", "fout")
                return redirect(url_for("nacalculatie"))

            resultaat = bereken_nacalculatie(c, regels, projectnaam)
            token = uuid.uuid4().hex
            _resultaten[token] = resultaat
            return render_template(
                "nacalculatie.html", resultaat=resultaat, token=token,
                status=db.db_status(c),
            )

        return render_template("nacalculatie.html", resultaat=None, status=db.db_status(c))
    finally:
        c.close()


@app.route("/export/<token>.<fmt>")
def exporteer(token, fmt):
    resultaat = _resultaten.get(token)
    if not resultaat:
        flash("Resultaat verlopen, draai de nacalculatie opnieuw.", "fout")
        return redirect(url_for("nacalculatie"))

    naam = (resultaat.get("projectnaam") or "nacalculatie").replace(" ", "_")[:60]
    if fmt == "xlsx":
        return send_file(
            export.naar_xlsx(resultaat), as_attachment=True,
            download_name=f"{naam}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "csv":
        return send_file(
            export.naar_csv(resultaat), as_attachment=True,
            download_name=f"{naam}.csv", mimetype="text/csv",
        )
    flash("Onbekend exportformaat.", "fout")
    return redirect(url_for("nacalculatie"))


@app.route("/instellingen", methods=["GET", "POST"])
def instellingen():
    c = conn()
    try:
        if request.method == "POST":
            actie = request.form.get("actie")
            if actie == "plantijd_toe":
                db.voeg_plantijd_patroon_toe(c, request.form.get("patroon"))
            elif actie == "plantijd_weg":
                db.verwijder_plantijd_patroon(c, request.form.get("patroon"))
            elif actie == "alias_toe":
                db.voeg_alias_toe(
                    c,
                    normaliseer_naam(request.form.get("planning_naam")),
                    normaliseer_naam(request.form.get("uren_naam")),
                )
            elif actie == "alias_weg":
                db.verwijder_alias(c, request.form.get("planning_naam_norm"))
            return redirect(url_for("instellingen"))

        return render_template(
            "instellingen.html",
            patronen=db.plantijd_patronen(c),
            aliassen=db.alias_lijst(c),
            medewerkers=db.medewerker_namen(c),
        )
    finally:
        c.close()


if __name__ == "__main__":
    import threading
    import webbrowser

    url = "http://127.0.0.1:5000"
    print(f"Database: {DB_PATH}")
    print(f"De tool opent automatisch in je browser. Lukt dat niet? Ga naar {url}")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
