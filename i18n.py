"""Tiny translation layer: English is the source language, Hungarian is built in.

The language comes from ~/.config/redex/config.json ("language": "auto" | "en" | "hu"),
and with "auto" from the usual locale variables (LANGUAGE, LC_ALL, LC_MESSAGES, LANG).
"""
import json, os

CONFIG_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                           "redex", "config.json")

HU = {
    # window
    "Reload": "Újraolvasás",
    "The mouse is not available": "Az egér nem érhető el",
    "Try again": "Újrapróbálás",
    "Error: {msg}": "Hiba: {msg}",
    # accent group
    "GNOME accent color": "GNOME kiemelőszín",
    "Like the keyboard: the LED takes the system accent color and changes with it.":
        "Mint a billentyűzet: a LED a rendszer kiemelőszínét veszi fel, és vele együtt vált.",
    "Follow the accent color": "Kövesse a kiemelőszínt",
    "Top LED": "Felső LED",
    "Bottom LED": "Alsó LED",
    "Set by the accent color": "A kiemelőszín vezérli",
    "The LEDs follow the accent color": "A LED-ek a kiemelőszínt követik",
    "Accent color following turned off": "Kiemelőszín követése kikapcsolva",
    # top LED
    "Same color on every DPI level.": "Minden DPI-szinten ugyanezzel a színnel világít.",
    "Color": "Szín",
    "DPI level colors": "DPI-szintek színei",
    "(active: {n})": "(aktív: {n})",
    "Top LED: #{hex}": "Felső LED: #{hex}",
    # bottom LED
    "Effect": "Effekt",
    "Switches to the “Static color” effect": "Kiválasztáskor „Statikus szín” effektre vált",
    "Bottom LED: #{hex}": "Alsó LED: #{hex}",
    "Bottom LED: {label}": "Alsó LED: {label}",
    "Off": "Kikapcsolva",
    "Static color": "Statikus szín",
    "Rainbow wave": "Szivárvány hullám",
    "Rainbow cycle": "Szivárvány körforgás",
    "Color fade": "Átmenetes színváltás",
    "Breathing": "Lélegző",
    "Multi-color, static": "Többszínű, statikus",
    "Two alternating colors": "Váltakozó két szín",
    "Random colors": "Véletlen színek",
    "Random color wave": "Hullámzó véletlen színek",
    # restore
    "Restore original settings": "Eredeti beállítás visszaállítása",
    "Restore?": "Visszaállítás?",
    "The mouse gets back the settings it had before the first change made on Linux.":
        "Az egér visszakapja azt a beállítást, ami az első Linuxos módosítás előtt volt rajta.",
    "Cancel": "Mégse",
    "Restore": "Visszaállítás",
    "Original settings restored": "Eredeti beállítás visszaállítva",
    # language
    "General": "Általános",
    "Language": "Nyelv",
    "Automatic": "Automatikus",
    "Takes effect when the app is restarted": "A program újraindítása után érvényes",
    # errors from redex.py
    "mouse dongle not found (145F:0320)": "nem található az egér dongle-ja (145F:0320)",
    "the mouse is not online (move it to wake it up)": "az egér nem elérhető (mozdítsd meg, hogy felébredjen)",
    "the mouse did not return the new values after writing":
        "írás után az egér nem a beírt értékeket adta vissza",
}


def configured_language():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f).get("language", "auto")
    except (OSError, ValueError, AttributeError):
        return "auto"


def detect():
    lang = configured_language()
    if lang in ("en", "hu"):
        return lang
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "hu" if value.split(":")[0].lower().startswith("hu") else "en"
    return "en"


LANG = detect()


def _(text, **kw):
    s = HU.get(text, text) if LANG == "hu" else text
    return s.format(**kw) if kw else s
