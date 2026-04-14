"""
Gesetzliche Feiertage in Bayern OHNE katholische Feiertage.

Ausgeschlossen: Heilige Drei Könige (6.1.), Fronleichnam,
Mariä Himmelfahrt (15.8.), Allerheiligen (1.11.)
"""
from datetime import date, timedelta


def easter(year):
    """Ostersonntag nach Gauss-Algorithmus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_holidays(year):
    """
    Gibt dict {date: name} zurück mit allen gesetzlichen Feiertagen
    in Bayern OHNE die rein katholischen Feiertage.
    """
    os = easter(year)
    holidays = {
        date(year, 1, 1): 'Neujahr',
        os - timedelta(days=2): 'Karfreitag',
        os + timedelta(days=1): 'Ostermontag',
        date(year, 5, 1): 'Tag der Arbeit',
        os + timedelta(days=39): 'Christi Himmelfahrt',
        os + timedelta(days=50): 'Pfingstmontag',
        date(year, 10, 3): 'Tag der Deutschen Einheit',
        date(year, 12, 25): '1. Weihnachtstag',
        date(year, 12, 26): '2. Weihnachtstag',
    }
    return holidays


def is_holiday(d):
    """Prüft ob ein Datum ein Feiertag ist."""
    return d in get_holidays(d.year)


def get_holiday_name(d):
    """Gibt den Feiertagsnamen zurück oder None."""
    return get_holidays(d.year).get(d)
