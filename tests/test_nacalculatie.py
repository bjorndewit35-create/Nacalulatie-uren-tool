"""Logica-tests voor parsing, import en uren-toekenning."""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from nacalculatie import bereken_nacalculatie, zoek_werkelijke_uren  # noqa: E402
from parsing import (  # noqa: E402
    afwezigheid_soort, lijkt_materieel, naam_marker, normaliseer_naam,
    parse_tijd_naar_minuten,
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


# --- migratie van database naar nieuwe locatie ---

def test_migreer_db_kopieert_eenmalig(tmp_path):
    oud = tmp_path / "data" / "nacalculatie.db"
    oud.parent.mkdir()
    oud.write_bytes(b"oude-inhoud")
    nieuw = tmp_path / "thuis" / "nacalculatie.db"

    assert db.migreer_db(str(oud), str(nieuw)) is True
    assert nieuw.read_bytes() == b"oude-inhoud"
    assert oud.exists()  # origineel blijft staan

    # Tweede keer: nieuw bestaat al -> niet opnieuw kopiëren.
    nieuw.write_bytes(b"nieuwere-inhoud")
    assert db.migreer_db(str(oud), str(nieuw)) is False
    assert nieuw.read_bytes() == b"nieuwere-inhoud"


def test_migreer_db_zonder_oude_db(tmp_path):
    oud = tmp_path / "bestaat-niet.db"
    nieuw = tmp_path / "nieuw.db"
    assert db.migreer_db(str(oud), str(nieuw)) is False
    assert not nieuw.exists()


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


def test_lange_chauffeurshift_gebruikt_werkelijke_uren():
    c = _conn()
    # Gepland als chauffeur voor 5 uur (>= 4u) en 8 uur geklokt -> werkelijke uren.
    db.import_uren(c, [_uur({}, werknemer="Alex Bakker", tijd_minuten=480)], "u.xlsx")
    res = bereken_nacalculatie(c, [_plan("Alex Bakker", "Chauffeur CE", duur_min=300)])
    regel = res["medewerkers"][0]["regels"][0]
    assert regel["bron"] == "werkelijk"
    assert regel["toegekend_min"] == 480
    assert "4u" in regel["opmerking"]


def test_chauffeurshift_exact_4uur_gebruikt_werkelijke_uren():
    c = _conn()
    # Grens: 4 uur (240 min) telt al als "lang" -> werkelijke uren.
    db.import_uren(c, [_uur({}, werknemer="Alex Bakker", tijd_minuten=450)], "u.xlsx")
    res = bereken_nacalculatie(c, [_plan("Alex Bakker", "Chauffeur C", duur_min=240)])
    regel = res["medewerkers"][0]["regels"][0]
    assert regel["bron"] == "werkelijk"
    assert regel["toegekend_min"] == 450


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


# --- uren opzoeken (platte lijst) ---

def test_opzoeken_vindt_werkelijke_uren():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Gerrit Jong", tijd_minuten=540)], "u.xlsx")
    res = zoek_werkelijke_uren(c, [_plan("Gerrit Jong", "Licht Stagehand", duur_min=600)])
    assert res["aantal_regels"] == 1
    rij = res["rijen"][0]
    assert rij["werkelijk_min"] == 540
    assert rij["datum_nl"] == "25-04-2026"
    assert res["totaal_min"] == 540


def test_opzoeken_onbekende_naam_niet_gevonden():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Hans Bakker")], "u.xlsx")
    res = zoek_werkelijke_uren(c, [_plan("Onbekend Persoon *", "Audio Operator")])
    rij = res["rijen"][0]
    assert rij["werkelijk_min"] is None
    assert "niet in urenregistratie" in rij["opmerking"]
    assert res["totaal_min"] == 0


def test_opzoeken_slaat_materieel_over():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Ivo Vos")], "u.xlsx")
    regels = [
        _plan("Ivo Vos", "Licht Stagehand"),
        _plan("Bus B-01 (Caddy) VL-173-F", "Crew Transport"),
        _plan("Vrachtwagen VR-02 99-BKV-8", "Bakwagen 35 m3"),
    ]
    res = zoek_werkelijke_uren(c, regels)
    assert res["aantal_regels"] == 1
    assert res["rijen"][0]["naam"] == "Ivo Vos"


def test_opzoeken_dubbele_dag_telt_uren_een_keer():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Joost Kerk", tijd_minuten=480)], "u.xlsx")
    regels = [
        _plan("Joost Kerk", "Licht Stagehand"),
        _plan("Joost Kerk", "Audio Stagehand"),
    ]
    res = zoek_werkelijke_uren(c, regels)
    assert res["aantal_regels"] == 2
    assert all(r["werkelijk_min"] == 480 for r in res["rijen"])
    assert "niet optellen" in res["rijen"][0]["opmerking"]
    assert res["totaal_min"] == 480  # dag maar één keer geteld


# --- #1: plantijd niet dubbel bovenop de gewerkte dag ---

def test_plantijd_niet_dubbel_op_productiedag():
    c = _conn()
    # Zelfde persoon: korte chauffeursrit (2u, plantijd) én productie op dezelfde dag.
    db.import_uren(c, [_uur({}, werknemer="Karel Mol", tijd_minuten=480)], "u.xlsx")
    regels = [
        _plan("Karel Mol", "1.4 Chauffeur CE", duur_min=120),   # plantijd-functie <4u
        _plan("Karel Mol", "Lichttech Montage", duur_min=600),  # productie
    ]
    res = bereken_nacalculatie(c, regels)
    m = res["medewerkers"][0]
    # Alleen de volle gewerkte dag telt; de rit valt daarbinnen -> geen 600.
    assert m["totaal_min"] == 480
    chauf = [r for r in m["regels"] if "Chauffeur" in r["functie"]][0]
    assert chauf["toegekend_min"] == 0
    assert "binnen de werkelijke dag" in chauf["opmerking"]
    # Uitkomst is onafhankelijk van de volgorde van de planningregels.
    res2 = bereken_nacalculatie(c, list(reversed(regels)))
    assert res2["medewerkers"][0]["totaal_min"] == 480


def test_plantijd_blijft_op_dag_zonder_productie():
    c = _conn()
    # Alleen een korte rit die dag -> plantijd blijft gelden (geen productie).
    db.import_uren(c, [_uur({}, werknemer="Karel Mol", tijd_minuten=480)], "u.xlsx")
    res = bereken_nacalculatie(c, [_plan("Karel Mol", "Chauffeur C", duur_min=120)])
    m = res["medewerkers"][0]
    assert m["totaal_min"] == 120
    assert m["regels"][0]["bron"] == "plantijd"


def test_niet_geaccordeerd_waarschuwing():
    c = _conn()
    db.import_uren(
        c, [_uur({}, werknemer="Otto Reis", tijd_minuten=480, status="Ingediend")], "u.xlsx"
    )
    res = bereken_nacalculatie(c, [_plan("Otto Reis", "Lichttech Montage", duur_min=600)])
    ng = res["niet_geaccordeerd"]
    assert ng["regels"] == 1
    assert ng["totaal_regels"] == 1
    assert ng["minuten"] == 480


# --- #2: materieel-herkenning zonder false positives ---

def test_lijkt_materieel_geen_false_positive_op_personen():
    # Echte medewerkers met een materieel-woord in de naam blijven personen.
    assert lijkt_materieel("Kees Bus") is False
    assert lijkt_materieel("Anke Trekker") is False
    assert lijkt_materieel("Jan Vrachtwagen") is False
    # Echt materieel blijft herkend (begint met type of heeft kenteken/frase).
    assert lijkt_materieel("Bus B-01 (Caddy) VL-173-F") is True
    assert lijkt_materieel("Vrachtwagen VR-02 99-BKV-8") is True
    assert lijkt_materieel("Trailer OPL-01 OS-02-DS") is True
    assert lijkt_materieel("Eigen Vervoer") is True


def test_opzoeken_persoon_met_materieelwoord_in_naam():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Kees Bus", tijd_minuten=480)], "u.xlsx")
    res = zoek_werkelijke_uren(c, [_plan("Kees Bus", "Licht Stagehand")])
    assert res["aantal_regels"] == 1
    assert res["rijen"][0]["werkelijk_min"] == 480


# --- #3: import zonder declaratie-id verliest geen uren ---

def test_import_zonder_declaratie_id_behoudt_regels():
    c = _conn()
    r1 = _uur({}, werknemer="Lot Prins", begintijd=None, eindtijd=None,
              werksoort="Montage", declaratie_id=None, tijd_minuten=240)
    r2 = _uur({}, werknemer="Lot Prins", begintijd=None, eindtijd=None,
              werksoort="Montage", declaratie_id=None, tijd_minuten=180)
    toe, bij = db.import_uren(c, [r1, r2], "geen-id.xlsx")
    assert (toe, bij) == (2, 0)
    tot = c.execute(
        "SELECT SUM(tijd_minuten) FROM uren WHERE werknemer_norm = ?",
        (normaliseer_naam("Lot Prins"),),
    ).fetchone()[0]
    assert tot == 420  # beide regels bewaard, niets overschreven
    # Her-upload van hetzelfde bestand blijft idempotent.
    toe2, _ = db.import_uren(c, [r1, r2], "geen-id.xlsx")
    assert toe2 == 0


def test_import_zonder_declaratie_id_identieke_regels():
    c = _conn()
    # Twee volledig identieke regels zonder id -> beide bewaard via volgnummer.
    r = _uur({}, werknemer="Pim Das", begintijd=None, eindtijd=None,
             werksoort="Montage", declaratie_id=None, tijd_minuten=240)
    toe, _ = db.import_uren(c, [dict(r), dict(r)], "geen-id.xlsx")
    assert toe == 2
    assert c.execute("SELECT COUNT(*) FROM uren").fetchone()[0] == 2


# --- upload verwijderen ---

def test_verwijder_upload():
    c = _conn()
    db.import_uren(c, [_uur({}, werknemer="Mira Fen")], "bestand-a.xlsx")
    db.import_uren(
        c, [_uur({}, werknemer="Nout Aal", datum="2026-05-01")], "bestand-b.xlsx"
    )
    assert db.verwijder_upload(c, "bestand-a.xlsx") == 1
    namen = [n for _, n in db.medewerker_namen(c)]
    assert namen == ["Nout Aal"]
    ups = db.uploads_overzicht(c)
    assert len(ups) == 1
    assert ups[0]["bron_bestand"] == "bestand-b.xlsx"


# --- wachtwoordbeveiliging voor de gehoste link ---

def _app_client(monkeypatch, tmp_path, user=None, pw=None):
    import importlib
    monkeypatch.setenv("NACALC_DB", str(tmp_path / "t.db"))
    import app as appmod
    importlib.reload(appmod)
    appmod._AUTH_USER = user
    appmod._AUTH_PW = pw
    return appmod.app.test_client()


def test_geen_login_zonder_env(monkeypatch, tmp_path):
    client = _app_client(monkeypatch, tmp_path)
    assert client.get("/").status_code == 200


def test_login_vereist_met_env(monkeypatch, tmp_path):
    import base64
    client = _app_client(monkeypatch, tmp_path, user="baas", pw="geheim")
    assert client.get("/").status_code == 401  # zonder inlog geweigerd
    goed = base64.b64encode(b"baas:geheim").decode()
    assert client.get("/", headers={"Authorization": f"Basic {goed}"}).status_code == 200
    fout = base64.b64encode(b"baas:verkeerd").decode()
    assert client.get("/", headers={"Authorization": f"Basic {fout}"}).status_code == 401


# --- afwezigheid (verlof / ziek / dokter-tandarts) telt niet als gewerkte uren ---

def test_afwezigheid_soort():
    assert afwezigheid_soort("Bijzonder Verlof", "Bijzonder verlof") == "verlof"
    assert afwezigheid_soort("Ouderschapsverlof", "Ouderschapsverlof") == "verlof"
    assert afwezigheid_soort("Ziekte", "Ziek") == "ziek"
    assert afwezigheid_soort("Dokter / Tandarts", "Dokter / Tandarts") == "dokter/tandarts"
    assert afwezigheid_soort("1.Werkvloer", "1. Ingeklokt") is None
    assert afwezigheid_soort("Ingeklokt", "Tijd klokken") is None


def test_dokterbezoek_telt_niet_mee_op_werkdag():
    c = _conn()
    # Zelfde dag: 6u gewerkt + 35 min dokter -> alleen de 6u telt.
    db.import_uren(c, [
        _uur({}, werknemer="Tom Vos", tijd_minuten=360),
        _uur({}, werknemer="Tom Vos", tijd_minuten=35, begintijd="00:00", eindtijd="00:00",
             werkgroep="Dokter / Tandarts", werksoort="Dokter / Tandarts", declaratie_id=2),
    ], "u.xlsx")
    dag = db.gewerkt_op_dag(c, normaliseer_naam("Tom Vos"), "2026-04-25")
    assert dag["minuten"] == 360
    assert dag["afwezigheid"] == {"dokter/tandarts"}


def test_ziektedag_geeft_nul_werkuren_met_opmerking():
    c = _conn()
    db.import_uren(c, [_uur(
        {}, werknemer="Zieke Piet", tijd_minuten=480, begintijd="00:00", eindtijd="00:00",
        werkgroep="Ziekte", werksoort="Ziek",
    )], "u.xlsx")
    dag = db.gewerkt_op_dag(c, normaliseer_naam("Zieke Piet"), "2026-04-25")
    assert dag["minuten"] == 0
    assert dag["afwezigheid"] == {"ziek"}
    # In een nacalculatie: 0 toegekend, met een duidelijke opmerking.
    res = bereken_nacalculatie(c, [_plan("Zieke Piet", "Lichttech Montage", duur_min=600)])
    regel = res["medewerkers"][0]["regels"][0]
    assert regel["toegekend_min"] == 0
    assert "ziek" in regel["opmerking"]


# --- back-up terugzetten ---

def test_is_geldige_db(tmp_path):
    goed = tmp_path / "goed.db"
    c = db.get_conn(str(goed))
    c.close()
    assert db.is_geldige_db(str(goed)) is True
    slecht = tmp_path / "slecht.db"
    slecht.write_text("dit is geen database")
    assert db.is_geldige_db(str(slecht)) is False


def test_herstel_db_geldig(tmp_path):
    bron = tmp_path / "backup.db"
    bc = db.get_conn(str(bron))
    db.import_uren(bc, [_uur({}, werknemer="Rik Zwart")], "u.xlsx")
    bc.close()

    doel = tmp_path / "live.db"
    dc = db.get_conn(str(doel))  # bestaand doel met andere data
    db.import_uren(dc, [_uur({}, werknemer="Oude Data")], "oud.xlsx")
    dc.close()

    veilig = tmp_path / "veilig.db"
    status = db.herstel_db(str(bron), str(doel), str(veilig))
    assert status["medewerkers"] == 1
    assert status["regels"] == 1
    # Doel bevat nu de back-up-data, niet meer de oude.
    namen = [n for _, n in db.medewerker_namen(db.get_conn(str(doel)))]
    assert namen == ["Rik Zwart"]
    # De oude data is als veiligheidskopie bewaard.
    assert veilig.exists()
    oude = [n for _, n in db.medewerker_namen(db.get_conn(str(veilig)))]
    assert oude == ["Oude Data"]


def test_herstel_db_ongeldig_laat_doel_ongemoeid(tmp_path):
    doel = tmp_path / "live.db"
    dc = db.get_conn(str(doel))
    db.import_uren(dc, [_uur({}, werknemer="Blijf Staan")], "u.xlsx")
    dc.close()

    junk = tmp_path / "geen.db"
    junk.write_text("zomaar wat tekst")
    try:
        db.herstel_db(str(junk), str(doel))
        assert False, "verwachtte ValueError"
    except ValueError:
        pass
    # Doel is niet aangeraakt.
    namen = [n for _, n in db.medewerker_namen(db.get_conn(str(doel)))]
    assert namen == ["Blijf Staan"]


def test_herstel_route(monkeypatch, tmp_path):
    import importlib
    import io
    monkeypatch.setenv("NACALC_DB", str(tmp_path / "live.db"))
    import app as appmod
    importlib.reload(appmod)
    appmod._AUTH_USER = None
    appmod._AUTH_PW = None
    client = appmod.app.test_client()

    # Bouw een geldig back-upbestand met bekende data.
    bron = tmp_path / "backup.db"
    bc = db.get_conn(str(bron))
    db.import_uren(bc, [_uur({}, werknemer="Sanne Web")], "u.xlsx")
    bc.close()

    live = str(tmp_path / "live.db")
    data = {"backup": (io.BytesIO(bron.read_bytes()), "nacalculatie-backup.db")}
    r = client.post("/herstel", data=data, content_type="multipart/form-data",
                    follow_redirects=True)
    assert r.status_code == 200
    assert "Back-up teruggezet" in r.get_data(as_text=True)
    # De live database bevat nu de teruggezette data.
    assert [n for _, n in db.medewerker_namen(db.get_conn(live))] == ["Sanne Web"]

    # Junk-bestand verandert niets aan de live database.
    junk = {"backup": (io.BytesIO(b"geen database"), "kapot.db")}
    r2 = client.post("/herstel", data=junk, content_type="multipart/form-data",
                     follow_redirects=True)
    assert "geen geldig back-upbestand" in r2.get_data(as_text=True)
    assert [n for _, n in db.medewerker_namen(db.get_conn(live))] == ["Sanne Web"]
