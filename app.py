"""Flask-webapp voor de nacalculatie-uren-tool (lokaal te draaien)."""
import os
import tempfile
import uuid

from flask import (
    Flask, flash, redirect, render_template, request, send_file, url_for,
)

import db
import export
from nacalculatie import bereken_nacalculatie
from parsing import (
    min_naar_hhmm, min_naar_uur, normaliseer_naam, parse_planning,
    parse_urenregistratie,
)

BASIS = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("NACALC_DB", os.path.join(BASIS, "data", "nacalculatie.db"))
TOEGESTANE_EXT = {".xls", ".xlsx", ".xlsm"}

app = Flask(__name__)
app.secret_key = os.environ.get("NACALC_SECRET", "lokale-nacalculatie-tool")

# Resultaten van een nacalculatie tijdelijk bewaren voor de download-knoppen.
# Single-user lokale app, dus een eenvoudige in-memory cache volstaat.
_resultaten = {}


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
        return render_template("index.html", status=db.db_status(c))
    finally:
        c.close()


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
                toe, bij = db.import_uren(c, records, b.filename)
                totaal_toe += toe
                totaal_bij += bij
                verwerkt.append((b.filename, toe, bij))

            if verwerkt:
                flash(
                    f"Verwerkt: {totaal_toe} nieuwe regels, {totaal_bij} bijgewerkt "
                    f"(uit {len(verwerkt)} bestand(en)).",
                    "ok",
                )
            return redirect(url_for("uren"))

        return render_template(
            "upload_uren.html",
            status=db.db_status(c),
            medewerkers=db.medewerker_namen(c),
        )
    finally:
        c.close()


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
    print(f"Database: {DB_PATH}")
    app.run(host="127.0.0.1", port=5000, debug=True)
