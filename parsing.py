"""Inlezen en normaliseren van ERP-exports (.xls en .xlsx).

Bevat gedeelde helpers die zowel door de database-import (stap 1) als door de
nacalculatie (stap 2) worden gebruikt.
"""
import datetime
import os
import re
import unicodedata

import openpyxl
import xlrd

# Trefwoorden om materieel/niet-personen in de planning te herkennen. Wordt
# alleen gebruikt om de "controleren"-lijst rustig te houden; matching op eigen
# medewerkers gebeurt op aanwezigheid in de uren-database. Let op: alleen op het
# resource-/werknemerveld checken, niet op de functie -- een functie als
# "...Hoogwerker" hoort bij een echte persoon die dat materieel bedient.
NIET_PERSOON_KW = [
    "trailer", "bakwagen", "vrachtwagen", "trekker", "aanhanger", "oplegger",
    "bus ", "bus(", "eigen vervoer", "2-inspire", "logistiek",
]


def normaliseer_naam(naam):
    """Naam vergelijkbaar maken: zonder markeringen, accenten of dubbele spaties."""
    if not naam:
        return ""
    s = str(naam)
    s = re.sub(r"\*+\s*$", "", s)  # markeringen * / ** achteraan weghalen
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s


def naam_marker(naam):
    """Geeft de markering achter een naam terug: '' , '*' (ZZP) of '**' (extern)."""
    m = re.search(r"(\*+)\s*$", str(naam or ""))
    return m.group(1) if m else ""


def schoon_naam(naam):
    """Weergavenaam zonder trailing markeringen."""
    return re.sub(r"\*+\s*$", "", str(naam or "")).strip()


def is_verlof(werkgroep, werksoort):
    s = f"{werkgroep or ''} {werksoort or ''}".lower()
    return "verlof" in s


def to_date(value, datemode=0):
    """Diverse datumvormen omzetten naar een datetime.date (of None)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return xlrd.xldate.xldate_as_datetime(value, datemode).date()
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%y", "%d-%m-%Y %H:%M"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def parse_tijd_naar_minuten(value):
    """Tijdsduur of tijdstip omzetten naar hele minuten (of None)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.timedelta):
        return int(round(value.total_seconds() / 60))
    if isinstance(value, datetime.datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, datetime.time):
        return value.hour * 60 + value.minute
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Excel slaat tijd op als fractie van een etmaal.
        return int(round(float(value) * 24 * 60))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        m = re.match(r"^(\d{1,2}):(\d{2})", s)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        try:
            return int(round(float(s.replace(",", ".")) * 60))
        except ValueError:
            return None
    return None


def tijd_str(value):
    """Tijdstip als 'HH:MM' (voor weergave/opslag), of None."""
    if value is None or value == "":
        return None
    if isinstance(value, (datetime.datetime, datetime.time)):
        return f"{value.hour:02d}:{value.minute:02d}"
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        m = int(round(float(value) * 24 * 60)) % (24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"
    return None


def min_naar_hhmm(m):
    if m is None or m == "":
        return ""
    m = int(round(m))
    neg = m < 0
    m = abs(m)
    return f"{'-' if neg else ''}{m // 60:02d}:{m % 60:02d}"


def min_naar_uur(m):
    if m is None or m == "":
        return ""
    return round(m / 60.0, 2)


def _clean_str(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _iter_sheets(path):
    """Levert (sheetnaam, rijen, datemode) voor zowel .xlsx als .xls."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            for ws in wb.worksheets:
                rows = [list(r) for r in ws.iter_rows(values_only=True)]
                yield ws.title, rows, 0
        finally:
            wb.close()
    elif ext == ".xls":
        book = xlrd.open_workbook(path)
        for sh in book.sheets():
            rows = [sh.row_values(r) for r in range(sh.nrows)]
            yield sh.name, rows, book.datemode
    else:
        raise ValueError(f"Niet-ondersteund bestandstype: {ext} (gebruik .xls of .xlsx)")


def _vind_kop(rows, verplicht):
    """Zoekt de kopregel die alle 'verplicht' kolomnamen bevat. Geeft (index, kolommen)."""
    for i, row in enumerate(rows[:25]):
        low = [str(c).strip().lower() if c is not None else "" for c in row]
        if all(v in low for v in verplicht):
            return i, low
    return None, None


def parse_urenregistratie(path):
    """Leest een urenregistratie-export. Geeft een lijst records (dicts)."""
    records = []
    for _sheet, rows, datemode in _iter_sheets(path):
        idx_kop, cols = _vind_kop(rows, ["werknemer", "datum"])
        if idx_kop is None or "tijd" not in cols:
            continue

        def col(*names):
            for n in names:
                if n in cols:
                    return cols.index(n)
            return None

        ci = {
            "werknemer": col("werknemer"),
            "datum": col("datum"),
            "begintijd": col("begintijd"),
            "eindtijd": col("eindtijd"),
            "tijd": col("tijd"),
            "project": col("project"),
            "projectnaam": col("projectnaam"),
            "werkgroep": col("werkgroep"),
            "werksoort": col("werksoort"),
            "werkzaamheden": col("werkzaamheden"),
            "declaratie_id": col("declaratie id", "declaratie-id", "declaratieid"),
            "status": col("status"),
        }

        for row in rows[idx_kop + 1:]:
            def g(key):
                j = ci.get(key)
                return row[j] if j is not None and j < len(row) else None

            werknemer = g("werknemer")
            datum = to_date(g("datum"), datemode)
            if not werknemer or datum is None:
                continue

            records.append({
                "werknemer": str(werknemer).strip(),
                "werknemer_norm": normaliseer_naam(werknemer),
                "datum": datum.isoformat(),
                "begintijd": tijd_str(g("begintijd")),
                "eindtijd": tijd_str(g("eindtijd")),
                "tijd_minuten": parse_tijd_naar_minuten(g("tijd")) or 0,
                "project_nr": _to_int(g("project")),
                "projectnaam": _clean_str(g("projectnaam")),
                "werkgroep": _clean_str(g("werkgroep")),
                "werksoort": _clean_str(g("werksoort")),
                "werkzaamheden": _clean_str(g("werkzaamheden")),
                "declaratie_id": _to_int(g("declaratie_id")),
                "status": _clean_str(g("status")),
            })
    return records


def parse_planning(path):
    """Leest een planning-export van één project. Geeft een lijst regels (dicts)."""
    regels = []
    for _sheet, rows, datemode in _iter_sheets(path):
        idx_kop, cols = _vind_kop(rows, ["functie", "werknemer"])
        if idx_kop is None:
            continue

        def col(*names):
            for n in names:
                if n in cols:
                    return cols.index(n)
            return None

        ci = {
            "datum": col("datum"),
            "functie": col("functie"),
            "begintijd": col("begintijd"),
            "eindtijd": col("eindtijd"),
            "doorlooptijd": col("doorlooptijd"),
            "werknemer": col("werknemer"),
        }

        for row in rows[idx_kop + 1:]:
            def g(key):
                j = ci.get(key)
                return row[j] if j is not None and j < len(row) else None

            werknemer_raw = g("werknemer")
            datum = to_date(g("datum"), datemode)
            if not werknemer_raw or datum is None:
                continue

            regels.append({
                "datum": datum.isoformat(),
                "functie": (str(g("functie")).strip() if g("functie") else ""),
                "begintijd": tijd_str(g("begintijd")),
                "eindtijd": tijd_str(g("eindtijd")),
                "doorlooptijd_min": parse_tijd_naar_minuten(g("doorlooptijd")) or 0,
                "werknemer": schoon_naam(werknemer_raw),
                "werknemer_norm": normaliseer_naam(werknemer_raw),
                "marker": naam_marker(werknemer_raw),
            })
    return regels


def lijkt_materieel(werknemer, functie=None):
    s = f" {werknemer or ''} ".lower()
    return any(k in s for k in NIET_PERSOON_KW)
