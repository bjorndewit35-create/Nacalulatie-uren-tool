"""Kern: koppelt planningregels aan de uren-database en kent uren toe."""
from collections import Counter

import db
from parsing import lijkt_materieel

# Plantijd-functies (bv. chauffeur) houden alleen de plantijd aan zolang de
# geplande shift korter is dan deze grens. Bij 4 uur of langer tellen de
# werkelijk gewerkte uren van die dag.
DREMPEL_PLANTIJD_MIN = 240  # 4 uur


def bereken_nacalculatie(conn, planning_regels, projectnaam=""):
    eigen = db.eigen_medewerkers_norm(conn)
    namen = db.naam_display_map(conn)
    alias = db.alias_map(conn)
    patronen = [p.lower() for p in db.plantijd_patronen(conn)]

    per_mdw = {}
    werkelijk_geteld = set()  # (uren_norm, datum) -> werkelijke uren maar één keer tellen
    ongematcht = []

    for pr in planning_regels:
        pnorm = pr["werknemer_norm"]
        unorm = alias.get(pnorm, pnorm)

        if unorm not in eigen:
            if not pr["marker"] and not lijkt_materieel(pr["werknemer"], pr["functie"]):
                ongematcht.append(pr)
            continue

        functie_low = pr["functie"].lower()
        is_plantijd_functie = any(p in functie_low for p in patronen if p)
        datum = pr["datum"]
        plan_min = pr["doorlooptijd_min"] or 0
        gebruik_plantijd = is_plantijd_functie and plan_min < DREMPEL_PLANTIJD_MIN
        dag = db.gewerkt_op_dag(conn, unorm, datum)
        opmerkingen = []

        if gebruik_plantijd:
            toegekend = plan_min
            bron = "plantijd"
            if not dag["gevonden"]:
                opmerkingen.append("geen uren in database (plantijd aangehouden)")
        else:
            if is_plantijd_functie:
                opmerkingen.append("plantijd-functie ≥ 4u → werkelijke uren")
            if (unorm, datum) in werkelijk_geteld:
                toegekend = 0
                bron = "werkelijk (al geteld)"
                opmerkingen.append("werkelijke dag-uren al geteld op deze dag")
            elif not dag["gevonden"]:
                toegekend = 0
                bron = "werkelijk"
                opmerkingen.append("geen uren in database")
            else:
                toegekend = dag["minuten"]
                bron = "werkelijk"
                werkelijk_geteld.add((unorm, datum))
                if dag["verlof"]:
                    opmerkingen.append("let op: ook verlof op deze dag")

        status_txt = ", ".join(sorted(dag["statuses"])) if dag["statuses"] else ""
        if status_txt and status_txt != "Geaccordeerd":
            opmerkingen.append(f"status: {status_txt}")

        regel = {
            "datum": datum,
            "functie": pr["functie"],
            "begintijd": pr["begintijd"],
            "eindtijd": pr["eindtijd"],
            "plantijd_min": plan_min,
            "werkelijk_dag_min": dag["minuten"] if dag["gevonden"] else None,
            "toegekend_min": toegekend,
            "bron": bron,
            "status": status_txt,
            "opmerking": "; ".join(opmerkingen),
        }

        mdw = per_mdw.setdefault(unorm, {
            "naam": namen.get(unorm, pr["werknemer"]),
            "norm": unorm,
            "regels": [],
            "totaal_min": 0,
        })
        mdw["regels"].append(regel)
        mdw["totaal_min"] += toegekend

    medewerkers = sorted(per_mdw.values(), key=lambda m: m["naam"].lower())
    for m in medewerkers:
        m["regels"].sort(key=lambda r: (r["datum"], r["functie"]))

    project_totaal = sum(m["totaal_min"] for m in medewerkers)

    return {
        "projectnaam": projectnaam,
        "medewerkers": medewerkers,
        "project_totaal_min": project_totaal,
        "ongematcht": ongematcht,
        "aantal_planningregels": len(planning_regels),
    }


def _datum_nl(iso):
    """ISO-datum 'YYYY-MM-DD' naar 'DD-MM-YYYY' voor weergave."""
    delen = (iso or "").split("-")
    return f"{delen[2]}-{delen[1]}-{delen[0]}" if len(delen) == 3 else iso


def zoek_werkelijke_uren(conn, planning_regels):
    """Platte per-regel lijst met de werkelijke gewerkte dag-uren erbij.

    In bestandsvolgorde, materieel overgeslagen, géén plantijd-attributie.
    """
    eigen = db.eigen_medewerkers_norm(conn)
    namen = db.naam_display_map(conn)
    alias = db.alias_map(conn)

    voorbereid = []
    voorkomen = Counter()
    for pr in planning_regels:
        if lijkt_materieel(pr["werknemer"]):
            continue
        unorm = alias.get(pr["werknemer_norm"], pr["werknemer_norm"])
        voorkomen[(unorm, pr["datum"])] += 1
        voorbereid.append((pr, unorm))

    rijen = []
    dag_geteld = set()
    totaal_min = 0
    aantal_gevonden = 0
    for pr, unorm in voorbereid:
        opmerkingen = []
        if unorm not in eigen:
            werkelijk_min = None
            opmerkingen.append("niet in urenregistratie")
        else:
            dag = db.gewerkt_op_dag(conn, unorm, pr["datum"])
            if not dag["gevonden"]:
                werkelijk_min = None
                opmerkingen.append("geen uren op deze dag")
            else:
                werkelijk_min = dag["minuten"]
                aantal_gevonden += 1
                if (unorm, pr["datum"]) not in dag_geteld:
                    totaal_min += dag["minuten"]
                    dag_geteld.add((unorm, pr["datum"]))
                if voorkomen[(unorm, pr["datum"])] > 1:
                    opmerkingen.append("zelfde persoon meerdere regels deze dag — uren niet optellen")
                if dag["verlof"]:
                    opmerkingen.append("ook verlof deze dag")
                status_txt = ", ".join(sorted(dag["statuses"]))
                if status_txt and status_txt != "Geaccordeerd":
                    opmerkingen.append(f"status: {status_txt}")

        rijen.append({
            "naam": namen.get(unorm, pr["werknemer"]),
            "marker": pr["marker"],
            "datum": pr["datum"],
            "datum_nl": _datum_nl(pr["datum"]),
            "functie": pr["functie"],
            "begintijd": pr["begintijd"],
            "eindtijd": pr["eindtijd"],
            "werkelijk_min": werkelijk_min,
            "opmerking": "; ".join(opmerkingen),
        })

    return {
        "rijen": rijen,
        "totaal_min": totaal_min,
        "aantal_regels": len(rijen),
        "aantal_gevonden": aantal_gevonden,
    }
