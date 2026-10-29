#!/usr/bin/env python3
"""Redex accent follower: keeps the mouse LEDs in the GNOME accent color.

Runs in the background (systemd user service redex-accent.service). When
org.gnome.desktop.interface accent-color changes, the color is converted the same
way MControlCenter does it for the keyboard (HSV: same hue, saturation x1.15 clamped
to 0.55..1, full value) and written once to the LEDs selected in the config.
No fades: every change is a write to the mouse's memory. If the mouse is asleep or
the dongle is missing, it retries every 30 seconds.

Config: ~/.config/redex/config.json  {"follow_accent": true, "top": true, "bottom": true}
"""
import colorsys, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import redex  # noqa: E402

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "redex")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULTS = {"follow_accent": False, "top": True, "bottom": True, "language": "auto"}

SERVICE = "redex-accent.service"
UNIT_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "systemd", "user")
PACKAGED_UNIT = os.path.join("/usr/lib/systemd/user", SERVICE)   # installed by the pacman package

# libadwaita accent colors (Adw.AccentColor.to_rgba)
ACCENTS = {
    "blue": "3584e4", "teal": "2190a4", "green": "3a944a", "yellow": "c88800", "orange": "ed5b00",
    "red": "e62d42", "pink": "d56199", "purple": "9141ac", "slate": "6f8396",
}
RETRY_SECONDS = 30
DEBOUNCE_MS = 800   # extensions like Auto Accent Colour may change it several times in a row


def led_color(accent_hex):
    """Accent -> LED color, the same formula MControlCenter uses for the keyboard."""
    r, g, b = (int(accent_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, _v = colorsys.rgb_to_hsv(r, g, b)
    s = max(0.55, min(1.0, s * 1.15))
    return bytes(round(x * 255) for x in colorsys.hsv_to_rgb(h, s, 1.0))


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return {**DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(cfg):
    """Merge cfg into the saved config (keys not in cfg are kept)."""
    merged = {**load_config(), **cfg}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(merged, f, indent=2)


def current_accent():
    from gi.repository import Gio
    return Gio.Settings.new("org.gnome.desktop.interface").get_string("accent-color")


def apply_accent(accent, cfg):
    """Write the accent's LED color to the selected LEDs. Raises redex.RedexError."""
    color = led_color(ACCENTS.get(accent, ACCENTS["blue"]))

    def edit(b):
        if cfg["top"]:
            redex.set_top(b, color)
        if cfg["bottom"]:
            redex.set_bottom(b, color)
    redex.modify(edit)   # writes nothing if the mouse already has these colors
    return color


# ---------- service management (used by the GUI) ----------

def unit_text():
    return f"""[Unit]
Description=Redex: mouse LEDs follow the GNOME accent color
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart={sys.executable} {os.path.realpath(__file__)}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical-session.target
"""


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def enable_service():
    user_unit = os.path.join(UNIT_DIR, SERVICE)
    if os.path.exists(PACKAGED_UNIT):
        # Installed as a package: use its unit. A unit written by an earlier, uninstalled
        # copy would shadow it, so drop that one.
        if os.path.exists(user_unit) and "Redex" in open(user_unit).read():
            systemctl("disable", SERVICE)
            os.remove(user_unit)
    else:
        os.makedirs(UNIT_DIR, exist_ok=True)
        with open(user_unit, "w") as f:
            f.write(unit_text())
    systemctl("daemon-reload")
    r = systemctl("enable", SERVICE)
    if r.returncode != 0:
        raise redex.RedexError(f"systemctl enable failed: {r.stderr.strip()}")
    r = systemctl("restart", SERVICE)   # restart = re-read config and apply now
    if r.returncode != 0:
        raise redex.RedexError(f"systemctl restart failed: {r.stderr.strip()}")


def disable_service():
    systemctl("disable", "--now", SERVICE)


# ---------- the service itself ----------

def main():
    from gi.repository import Gio, GLib

    settings = Gio.Settings.new("org.gnome.desktop.interface")
    state = {"pending": None, "retry": None, "debounce": None}

    def try_apply():
        state["retry"] = None
        accent = state["pending"]
        if accent is None:
            return False
        cfg = load_config()
        if not cfg["follow_accent"]:
            print("follow_accent is off in the config, nothing to do", flush=True)
            state["pending"] = None
            return False
        try:
            color = apply_accent(accent, cfg)
            print(f"accent {accent} -> #{color.hex()} (top={cfg['top']}, bottom={cfg['bottom']})", flush=True)
            state["pending"] = None
        except redex.RedexError as e:
            print(f"accent {accent}: {e}; retrying in {RETRY_SECONDS} s", flush=True)
            state["retry"] = GLib.timeout_add_seconds(RETRY_SECONDS, try_apply)
        return False

    def schedule(accent):
        state["pending"] = accent
        for key in ("debounce", "retry"):
            if state[key]:
                GLib.source_remove(state[key])
                state[key] = None

        def fire():
            state["debounce"] = None
            return try_apply()
        state["debounce"] = GLib.timeout_add(DEBOUNCE_MS, fire)

    settings.connect("changed::accent-color", lambda s, k: schedule(s.get_string(k)))
    schedule(settings.get_string("accent-color"))   # apply once at start
    print("redex accent follower running", flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
