"""SQLite-database: schema, idempotente import en queries voor de tool."""
import os
import sqlite3

from parsing import is_verlof

STANDAARD_PLANTIJD_FUNCTIES = ["Chauffeur", "Crew Transport"]


def get_conn(path):
    nieuw = not os.path.exists(path)
    map_ = os.path.dirname(path)
    if map_:
        os.makedirs(map_, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    if nieuw:
        conn.commit()
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS uren (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rij_key TEXT UNIQUE,
            werknemer TEXT,
            werknemer_norm TEXT,
            datum TEXT,
            begintijd TEXT,
            eindtijd TEXT,
            tijd_minuten INTEGER,
            project_nr INTEGER,
            projectnaam TEXT,
            werkgroep TEXT,
            werksoort TEXT,
            werkzaamheden TEXT,
            declaratie_id INTEGER,
            status TEXT,
            bron_bestand TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_uren_norm_datum ON uren (werknemer_norm, datum);

        CREATE TABLE IF NOT EXISTS plantijd_functies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patroon TEXT UNIQUE
        );

        CREATE TABLE IF NOT EXISTS naam_alias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planning_naam_norm TEXT UNIQUE,
            uren_naam_norm TEXT
        );
        """
    )
    if conn.execute("SELECT COUNT(*) FROM plantijd_functies").fetchone()[0] == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO plantijd_functies (patroon) VALUES (?)",
            [(p,) for p in STANDAARD_PLANTIJD_FUNCTIES],
        )


def _rij_key(rec):
    return "|".join([
        rec["werknemer_norm"],
        rec["datum"],
        rec.get("begintijd") or "",
        rec.get("eindtijd") or "",
        rec.get("werksoort") or "",
        str(rec.get("declaratie_id")),
    ])


def import_uren(conn, records, bron_bestand):
    """Voegt records idempotent toe. Geeft (toegevoegd, bijgewerkt)."""
    toegevoegd = bijgewerkt = 0
    for rec in records:
        key = _rij_key(rec)
        bestaat = conn.execute(
            "SELECT 1 FROM uren WHERE rij_key = ?", (key,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO uren (rij_key, werknemer, werknemer_norm, datum, begintijd,
                eindtijd, tijd_minuten, project_nr, projectnaam, werkgroep,
                werksoort, werkzaamheden, declaratie_id, status, bron_bestand)
            VALUES (:rij_key, :werknemer, :werknemer_norm, :datum, :begintijd,
                :eindtijd, :tijd_minuten, :project_nr, :projectnaam, :werkgroep,
                :werksoort, :werkzaamheden, :declaratie_id, :status, :bron_bestand)
            ON CONFLICT(rij_key) DO UPDATE SET
                werknemer=excluded.werknemer,
                tijd_minuten=excluded.tijd_minuten,
                project_nr=excluded.project_nr,
                projectnaam=excluded.projectnaam,
                werkgroep=excluded.werkgroep,
                werksoort=excluded.werksoort,
                werkzaamheden=excluded.werkzaamheden,
                status=excluded.status,
                bron_bestand=excluded.bron_bestand
            """,
            {**rec, "rij_key": key, "bron_bestand": bron_bestand},
        )
        if bestaat:
            bijgewerkt += 1
        else:
            toegevoegd += 1
    conn.commit()
    return toegevoegd, bijgewerkt


def db_status(conn):
    row = conn.execute(
        """
        SELECT COUNT(*) AS regels,
               COUNT(DISTINCT werknemer_norm) AS medewerkers,
               MIN(datum) AS van, MAX(datum) AS tot
        FROM uren
        """
    ).fetchone()
    return {
        "regels": row["regels"],
        "medewerkers": row["medewerkers"],
        "van": row["van"],
        "tot": row["tot"],
    }


def medewerker_namen(conn):
    rows = conn.execute(
        "SELECT werknemer_norm, MAX(werknemer) AS naam FROM uren GROUP BY werknemer_norm ORDER BY naam"
    ).fetchall()
    return [(r["werknemer_norm"], r["naam"]) for r in rows]


def beschikbare_jaren(conn):
    rows = conn.execute(
        "SELECT DISTINCT substr(datum,1,4) AS jaar FROM uren "
        "WHERE datum IS NOT NULL AND datum != '' ORDER BY jaar DESC"
    ).fetchall()
    return [r["jaar"] for r in rows]


def maand_dekking(conn, jaar):
    """Per medewerker de set maandnummers (1-12) met data in dit jaar.
    Geeft [{"naam": str, "maanden": set[int]}, ...] gesorteerd op naam."""
    rows = conn.execute(
        "SELECT werknemer_norm, MAX(werknemer) AS naam, "
        "CAST(substr(datum,6,2) AS INTEGER) AS maand "
        "FROM uren WHERE substr(datum,1,4) = ? "
        "GROUP BY werknemer_norm, maand",
        (jaar,),
    ).fetchall()
    per_mdw = {}
    for r in rows:
        d = per_mdw.setdefault(r["werknemer_norm"], {"naam": r["naam"], "maanden": set()})
        if r["maand"]:
            d["maanden"].add(r["maand"])
    return sorted(per_mdw.values(), key=lambda d: d["naam"].lower())


def eigen_medewerkers_norm(conn):
    rows = conn.execute("SELECT DISTINCT werknemer_norm FROM uren").fetchall()
    return {r["werknemer_norm"] for r in rows}


def naam_display_map(conn):
    rows = conn.execute(
        "SELECT werknemer_norm, MAX(werknemer) AS naam FROM uren GROUP BY werknemer_norm"
    ).fetchall()
    return {r["werknemer_norm"]: r["naam"] for r in rows}


def uren_overzicht(conn, werknemer_norm=None, van=None, tot=None):
    """Alle urenregels, optioneel gefilterd op medewerker en/of datumperiode."""
    sql = (
        "SELECT werknemer, datum, begintijd, eindtijd, tijd_minuten, "
        "werkgroep, werksoort, werkzaamheden, status, bron_bestand "
        "FROM uren WHERE 1=1"
    )
    params = []
    if werknemer_norm:
        sql += " AND werknemer_norm = ?"
        params.append(werknemer_norm)
    if van:
        sql += " AND datum >= ?"
        params.append(van)
    if tot:
        sql += " AND datum <= ?"
        params.append(tot)
    sql += " ORDER BY datum, werknemer, begintijd"
    return conn.execute(sql, params).fetchall()


def gewerkt_op_dag(conn, werknemer_norm, datum):
    """Werkelijk gewerkte minuten (excl. verlof) van één medewerker op één dag."""
    rows = conn.execute(
        "SELECT tijd_minuten, werkgroep, werksoort, status FROM uren "
        "WHERE werknemer_norm = ? AND datum = ?",
        (werknemer_norm, datum),
    ).fetchall()
    totaal = 0
    statuses = set()
    verlof = False
    for r in rows:
        if is_verlof(r["werkgroep"], r["werksoort"]):
            verlof = True
            continue
        totaal += r["tijd_minuten"] or 0
        if r["status"]:
            statuses.add(r["status"])
    return {
        "minuten": totaal,
        "statuses": statuses,
        "verlof": verlof,
        "gevonden": bool(rows),
    }


# --- Instellingen: plantijd-functies ---

def plantijd_patronen(conn):
    return [r["patroon"] for r in conn.execute(
        "SELECT patroon FROM plantijd_functies ORDER BY patroon"
    ).fetchall()]


def voeg_plantijd_patroon_toe(conn, patroon):
    patroon = (patroon or "").strip()
    if patroon:
        conn.execute(
            "INSERT OR IGNORE INTO plantijd_functies (patroon) VALUES (?)", (patroon,)
        )
        conn.commit()


def verwijder_plantijd_patroon(conn, patroon):
    conn.execute("DELETE FROM plantijd_functies WHERE patroon = ?", (patroon,))
    conn.commit()


# --- Instellingen: naam-aliassen ---

def alias_map(conn):
    return {
        r["planning_naam_norm"]: r["uren_naam_norm"]
        for r in conn.execute(
            "SELECT planning_naam_norm, uren_naam_norm FROM naam_alias"
        ).fetchall()
    }


def alias_lijst(conn):
    return conn.execute(
        "SELECT planning_naam_norm, uren_naam_norm FROM naam_alias ORDER BY planning_naam_norm"
    ).fetchall()


def voeg_alias_toe(conn, planning_norm, uren_norm):
    planning_norm = (planning_norm or "").strip()
    uren_norm = (uren_norm or "").strip()
    if planning_norm and uren_norm:
        conn.execute(
            "INSERT INTO naam_alias (planning_naam_norm, uren_naam_norm) VALUES (?, ?) "
            "ON CONFLICT(planning_naam_norm) DO UPDATE SET uren_naam_norm=excluded.uren_naam_norm",
            (planning_norm, uren_norm),
        )
        conn.commit()


def verwijder_alias(conn, planning_norm):
    conn.execute("DELETE FROM naam_alias WHERE planning_naam_norm = ?", (planning_norm,))
    conn.commit()
