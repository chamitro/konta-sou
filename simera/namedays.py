"""Greek name days: the common fixed dates plus the movable ones tied to Orthodox Easter.

Indicative, not exhaustive (the full eortologio has thousands of saints); the page says so.
"""
from __future__ import annotations

from datetime import date, timedelta

# month, day -> names (most common spellings first)
FIXED: dict[tuple[int, int], list[str]] = {
    (1, 1): ["Βασίλης", "Βασιλική", "Βάσω"],
    (1, 2): ["Σεραφείμ"],
    (1, 6): ["Φώτης", "Φωτεινή", "Θεοφάνης", "Φανή", "Ουρανία", "Ιορδάνης"],
    (1, 7): ["Γιάννης", "Ιωάννα", "Ιωάννης", "Γιαννούλα"],
    (1, 11): ["Θεοδόσης"],
    (1, 12): ["Τατιάνα"],
    (1, 17): ["Αντώνης", "Αντωνία", "Τόνια"],
    (1, 18): ["Θανάσης", "Αθανασία", "Νάσος", "Κύριλλος"],
    (1, 20): ["Ευθύμης", "Ευθυμία"],
    (1, 22): ["Τιμόθεος", "Αναστάσιος"],
    (1, 25): ["Γρηγόρης"],
    (1, 26): ["Ξενοφών"],
    (1, 27): ["Χρυσόστομος"],
    (2, 1): ["Τρύφωνας"],
    (2, 3): ["Συμεών", "Σταμάτης", "Σταματίνα"],
    (2, 10): ["Χαράλαμπος", "Μπάμπης", "Χαρά", "Χαραλαμπία"],
    (2, 11): ["Βλάσης"],
    (2, 26): ["Φωτεινή", "Πορφύριος"],
    (3, 9): ["Σαράντης"],
    (3, 17): ["Αλέξης"],
    (3, 19): ["Χρύσανθος"],
    (3, 25): ["Ευάγγελος", "Βαγγέλης", "Ευαγγελία", "Εύα"],
    (4, 6): ["Ευτύχιος"],
    (5, 5): ["Ειρήνη"],
    (5, 9): ["Χριστόφορος"],
    (5, 15): ["Αχιλλέας"],
    (5, 21): ["Κωνσταντίνος", "Κώστας", "Ελένη", "Έλενα", "Κωνσταντίνα"],
    (6, 11): ["Βαρθολομαίος", "Βαρνάβας"],
    (6, 29): ["Πέτρος", "Παύλος", "Παυλίνα", "Πέτρα"],
    (6, 30): ["Απόστολος", "Αποστολία"],
    (7, 1): ["Ανάργυρος", "Κοσμάς", "Δαμιανός"],
    (7, 7): ["Κυριακή", "Κική"],
    (7, 11): ["Όλγα", "Ευφημία"],
    (7, 17): ["Μαρίνα"],
    (7, 20): ["Ηλίας", "Λιάνα"],
    (7, 22): ["Μαγδαληνή", "Μαρκέλλα"],
    (7, 24): ["Χριστίνα"],
    (7, 25): ["Άννα"],
    (7, 26): ["Παρασκευή", "Βιβή"],
    (7, 27): ["Παντελής", "Παντελεήμων"],
    (8, 6): ["Σωτήρης", "Σωτηρία"],
    (8, 15): ["Μαρία", "Μάριος", "Παναγιώτης", "Παναγιώτα", "Δέσποινα", "Μαριάννα"],
    (8, 30): ["Αλέξανδρος", "Αλεξάνδρα"],
    (9, 1): ["Συμεών"],
    (9, 14): ["Σταύρος", "Σταυρούλα"],
    (9, 16): ["Ευφημία"],
    (9, 17): ["Σοφία", "Πίστη", "Ελπίδα", "Αγάπη"],
    (9, 20): ["Ευστάθιος", "Στάθης"],
    (9, 24): ["Θέκλα"],
    (10, 3): ["Διονύσης", "Διονυσία"],
    (10, 18): ["Λουκάς"],
    (10, 20): ["Αρτέμης", "Γεράσιμος"],
    (10, 26): ["Δημήτρης", "Δήμητρα", "Μίμης", "Τζίμης"],
    (11, 1): ["Ανάργυρος", "Αργύρης", "Αργυρώ"],
    (11, 8): ["Μιχάλης", "Γαβριήλ", "Άγγελος", "Αγγελική", "Σταμάτης", "Ραφαήλ", "Ταξιάρχης"],
    (11, 9): ["Νεκτάριος", "Νεκταρία"],
    (11, 11): ["Μηνάς", "Βίκτωρας", "Βικτωρία"],
    (11, 14): ["Φίλιππος", "Φιλίππα"],
    (11, 16): ["Ματθαίος"],
    (11, 25): ["Κατερίνα", "Αικατερίνη"],
    (11, 26): ["Στυλιανός", "Στέλιος", "Στέλλα"],
    (11, 30): ["Ανδρέας", "Ανδριάνα"],
    (12, 4): ["Βαρβάρα"],
    (12, 5): ["Σάββας"],
    (12, 6): ["Νικόλαος", "Νίκος", "Νικολέτα", "Νίκη"],
    (12, 12): ["Σπύρος", "Σπυριδούλα"],
    (12, 13): ["Ευστράτιος", "Στρατής", "Λουκία"],
    (12, 15): ["Ελευθέριος", "Λευτέρης", "Ελευθερία"],
    (12, 17): ["Διονύσης"],
    (12, 25): ["Χρήστος", "Χριστίνα", "Χρυσούλα"],
    (12, 26): ["Εμμανουήλ", "Μανώλης", "Εμμανουέλα"],
    (12, 27): ["Στέφανος", "Στεφανία"],
}


def orthodox_easter(year: int) -> date:
    """Orthodox Easter Sunday in the Gregorian calendar (Meeus' Julian algorithm + 13 days, valid 1900–2099)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return date(year, month, day + 1) + timedelta(days=13)


def movable(year: int) -> dict[date, list[str]]:
    easter = orthodox_easter(year)
    out: dict[date, list[str]] = {
        easter - timedelta(days=43): ["Θεόδωρος", "Θοδωρής", "Θεοδώρα", "Δώρα"],   # Saturday of the first week of Lent
        easter: ["Αναστάσιος", "Αναστασία", "Τάσος", "Νατάσα", "Λάμπρος", "Λαμπρινή", "Πασχάλης", "Πασχαλιά"],
        easter + timedelta(days=5): ["Ζωή", "Πηγή"],                                  # Ζωοδόχου Πηγής
        easter + timedelta(days=7): ["Θωμάς", "Θωμαή"],                                # Thomas Sunday
        easter + timedelta(days=56): ["Αγάπη", "Παντελής"],                            # All Saints: a few who have no other day
    }
    # Saint George moves to Easter Monday when 23 April falls in Lent or Holy Week
    george = date(year, 4, 23)
    out.setdefault(george if george > easter else easter + timedelta(days=1), []).extend(["Γιώργος", "Γεωργία", "Γωγώ"])
    mark = date(year, 4, 25)
    out.setdefault(mark if mark > easter + timedelta(days=1) else easter + timedelta(days=2), []).extend(["Μάρκος"])
    return out


def names_for(day: date) -> list[str]:
    names = list(FIXED.get((day.month, day.day), []))
    for n in movable(day.year).get(day, []):
        if n not in names:
            names.append(n)
    return names


HOLIDAYS_FIXED = {(1, 1): "Πρωτοχρονιά", (1, 6): "Θεοφάνια", (3, 25): "Ευαγγελισμός · Εθνική εορτή", (5, 1): "Πρωτομαγιά",
                  (8, 15): "Κοίμηση της Θεοτόκου", (10, 28): "Επέτειος του «Όχι» · Εθνική εορτή", (12, 25): "Χριστούγεννα", (12, 26): "Σύναξη της Θεοτόκου"}


def holiday(day: date) -> str | None:
    """Public holiday name for the day, if any (fixed plus the Easter-based ones)."""
    if (day.month, day.day) in HOLIDAYS_FIXED:
        return HOLIDAYS_FIXED[(day.month, day.day)]
    easter = orthodox_easter(day.year)
    return {easter - timedelta(days=48): "Καθαρά Δευτέρα", easter - timedelta(days=2): "Μεγάλη Παρασκευή", easter: "Πάσχα",
            easter + timedelta(days=1): "Δευτέρα του Πάσχα", easter + timedelta(days=50): "Αγίου Πνεύματος"}.get(day)


def next_nameday(after: date, limit: int = 60) -> tuple[date, list[str]] | None:
    """The first day after `after` with names in the list."""
    for i in range(1, limit + 1):
        d = after + timedelta(days=i)
        if names := names_for(d):
            return d, names
    return None
