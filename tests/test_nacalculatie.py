"""Logica-tests voor parsing, import en uren-toekenning."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from nacalculatie import bereken_nacalculatie  # noqa: E402
from parsing import (  # noqa: E402
    naam_marker, normaliseer_naam, parse_tijd_naar_minuten,
)


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    db.init_db(c)
    return c


def _uur(rec, **kw):
    basis = {
        "werknemer": "Jan Jansen", "datum": "2026-04-25",
        "begintijd": "08:00", "eindtijd": "18:00", "tijd_minuten": 600,
        "project_nr": None, "projectnaam": None, "werkgroep": "1.Werkvloer",
        "werksoort": "1. Ingeklokt", "werkzaamheden": None, "declaratie_id": 1,
        "status": "Geaccordeerd",
    }
    basis.update(kw)
    basis["werknemer_norm"] = normaliseer_naam(basis["werknemer"])
    return basis


def _plan(naam, functie, datum="2026-04-25", duur_min=120):
    return {
        "datum": datum, "functie": functie, "begintijd": "10:30",
        "eindtijd": "12:30", "doorlooptijd_min": duur_min,
        "werknemer": naam.rstrip(" *"), "werknemer_norm": normaliseer_naam(naam),
        "marker": naam_marker(naam),
    }


# --- helpers ---

def test_parse_tijd():
    assert parse_tijd_naar_minuten("08:15") == 495
    assert parse_tijd_naar_minuten("02:00") == 120
    assert parse_tijd_naar_minuten(None) is None
    import datetime
    assert parse_tijd_naar_minuten(datetime.time(8, 30)) == 510
    assert parse_tijd_naar_minuten(datetime.timedelta(hours=12)) == 720


def test_normaliseer_en_marker():
    assert normaliseer_naam("Janus Smits *") == "janus smits"
    assert normaliseer_naam("Joël  van  Westrenen") == "joel van westrenen"
    assert naam_marker("NTS Logistiek **") == "**"
    assert naam_marker("Arno Weijs") == ""


# --- import idempotent ---

def test_import_idempotent():
    c = _conn()
    recs = [_uur({})]
    toe, bij = db.import_uren(c, recs, "test.xlsx")
    assert (toe, bij) == (1, 0)
    toe, bij = db.import_uren(c, recs, "test.xlsx")
    assert (toe, bij) == (0, 1)
    assert c.execute("SELECT COUNT(*) FROM uren").fetchone()[0] == 1


# --- toekenningslogica ---

def test_chauffeur_gebruikt_plantijd():
    c = _conn()
    # Werkte 10 uur, maar gepland als chauffeur voor 2 uur -> plantijd telt.
    db.import_uren(c, [_uur({}, werknemer="Alex Bakker", tijd_minuten=600)], "u.xlsx")
    res = bereken_nacalculatie(c, [_plan("Alex Bakker", "1.4 Chauffeur CE", duur_min=120)])
    regel = res["medewerkers"][0]["regels"][0]
    assert regel["bron"] == "plantijd"
    assert regel["toegekend_min"] == 120
    assert res["project_totaal_min"] == 120


def test_productiefunctie_gebruikt_werkelijke_uren():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Bram Klaassen", tijd_minuten=585)], "u.xlsx")
    res = bereken_nacalculatie(c, [_plan("Bram Klaassen", "Lichttech (De) Montage", duur_min=600)])
    regel = res["medewerkers"][0]["regels"][0]
    assert regel["bron"] == "werkelijk"
    assert regel["toegekend_min"] == 585


def test_werkelijke_uren_niet_dubbel_per_dag():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Cor de Vries", tijd_minuten=480)], "u.xlsx")
    # Twee productieregels op dezelfde dag -> werkelijke uren maar één keer.
    regels = [
        _plan("Cor de Vries", "Lichttech Montage", duur_min=600),
        _plan("Cor de Vries", "Audiotech Montage", duur_min=600),
    ]
    res = bereken_nacalculatie(c, regels)
    assert res["medewerkers"][0]["totaal_min"] == 480


def test_materieel_en_externen_genegeerd():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Dirk Smit")], "u.xlsx")
    regels = [
        _plan("Dirk Smit", "Projectleider", duur_min=600),         # eigen
        _plan("Trailer OPL-01 OS-02-DS", "Trailer 50 m3"),         # materieel
        _plan("Janus Smits *", "Chauffeur C"),                     # ZZP
        _plan("NTS Logistiek **", "1.4 Chauffeur CE"),             # extern
    ]
    res = bereken_nacalculatie(c, regels)
    assert len(res["medewerkers"]) == 1
    assert res["medewerkers"][0]["naam"] == "Dirk Smit"
    # Geen van de niet-eigen regels mag in "ongematcht" belanden.
    assert res["ongematcht"] == []


def test_onbekende_persoon_wordt_gemarkeerd():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Eva Bos")], "u.xlsx")
    regels = [_plan("Onbekende Naam", "Projectleider")]
    res = bereken_nacalculatie(c, regels)
    assert res["medewerkers"] == []
    assert len(res["ongematcht"]) == 1
    assert res["ongematcht"][0]["werknemer"] == "Onbekende Naam"


def test_alias_koppelt_afwijkende_naam():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Frank de Wit")], "u.xlsx")
    db.voeg_alias_toe(c, normaliseer_naam("F. de Wit"), normaliseer_naam("Frank de Wit"))
    res = bereken_nacalculatie(c, [_plan("F. de Wit", "Lichttech Montage", duur_min=600)])
    assert len(res["medewerkers"]) == 1
    assert res["medewerkers"][0]["naam"] == "Frank de Wit"
