#!/usr/bin/env python3
"""Redex - graphical RGB control for the Trust GXT 926 Redex II mouse (GTK4 + libadwaita).

All mouse I/O is in redex.py (the same code the `redex` command uses).
"""
import os, sys, threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import redex  # noqa: E402
import redex_accent  # noqa: E402
from i18n import _  # noqa: E402

APP_ID = "io.github.redex.Control"

# Bottom LED effects in drop-down order: (effect number, label)
EFFECT_LABELS = [
    (0, "Off"),
    (2, "Static color"),
    (1, "Rainbow wave"),
    (4, "Rainbow cycle"),
    (5, "Color fade"),
    (3, "Breathing"),
    (6, "Multi-color, static"),
    (7, "Two alternating colors"),
    (8, "Random colors"),
    (9, "Random color wave"),
]
LANGUAGES = [("auto", "Automatic"), ("en", "English"), ("hu", "Magyar")]


def rgba_from_bytes(b):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = b[0] / 255, b[1] / 255, b[2] / 255, 1.0
    return c


def bytes_from_rgba(c):
    return bytes(max(0, min(255, round(v * 255))) for v in (c.red, c.green, c.blue))


class RedexWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Redex", default_width=460, default_height=640)
        self.block = None
        self.updating = False   # True while widgets are set from the mouse state

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Reload"))
        self.refresh_btn.connect("clicked", lambda *_a: self.load())
        header.pack_start(self.refresh_btn)
        self.spinner = Adw.Spinner(visible=False)
        header.pack_end(self.spinner)
        view.add_top_bar(header)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        view.set_content(self.stack)

        # --- error page ---
        self.error_page = Adw.StatusPage(icon_name="input-mouse-symbolic", title=_("The mouse is not available"))
        retry = Gtk.Button(label=_("Try again"), halign=Gtk.Align.CENTER)
        retry.add_css_class("pill")
        retry.add_css_class("suggested-action")
        retry.connect("clicked", lambda *_a: self.load())
        self.error_page.set_child(retry)
        self.stack.add_named(self.error_page, "error")

        # --- settings page ---
        page = Adw.PreferencesPage()
        self.stack.add_named(page, "settings")

        self.cfg = redex_accent.load_config()
        accent = Adw.PreferencesGroup(
            title=_("GNOME accent color"),
            description=_("Like the keyboard: the LED takes the system accent color and changes with it."))
        self.follow_row = Adw.SwitchRow(title=_("Follow the accent color"), active=self.cfg["follow_accent"])
        self.follow_top = Adw.SwitchRow(title=_("Top LED"), active=self.cfg["top"])
        self.follow_bottom = Adw.SwitchRow(title=_("Bottom LED"), active=self.cfg["bottom"])
        for r in (self.follow_row, self.follow_top, self.follow_bottom):
            accent.add(r)
            r.connect("notify::active", self.on_follow_changed)
        page.add(accent)

        top = Adw.PreferencesGroup(title=_("Top LED"), description=_("Same color on every DPI level."))
        self.top_color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                               valign=Gtk.Align.CENTER)
        self.top_color.connect("notify::rgba", self.on_top_color)
        self.top_row = Adw.ActionRow(title=_("Color"))
        self.top_row.add_suffix(self.top_color)
        self.top_row.set_activatable_widget(self.top_color)
        top.add(self.top_row)
        self.top_levels = Adw.ActionRow(title=_("DPI level colors"), subtitle="")
        self.top_levels.add_css_class("property")
        top.add(self.top_levels)
        page.add(top)

        bottom = Adw.PreferencesGroup(title=_("Bottom LED"))
        self.effect_row = Adw.ComboRow(title=_("Effect"),
                                       model=Gtk.StringList.new([_(lbl) for _n, lbl in EFFECT_LABELS]))
        self.effect_row.connect("notify::selected", self.on_effect)
        bottom.add(self.effect_row)
        self.bottom_color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                                  valign=Gtk.Align.CENTER)
        self.bottom_color.connect("notify::rgba", self.on_bottom_color)
        self.bottom_row = Adw.ActionRow(title=_("Color"))
        self.bottom_row.add_suffix(self.bottom_color)
        self.bottom_row.set_activatable_widget(self.bottom_color)
        bottom.add(self.bottom_row)
        page.add(bottom)

        self.update_follow_ui()

        reset = Adw.PreferencesGroup()
        restore = Adw.ButtonRow(title=_("Restore original settings"))
        restore.add_css_class("destructive-action")
        restore.connect("activated", self.on_restore)
        reset.add(restore)
        page.add(reset)

        general = Adw.PreferencesGroup(title=_("General"))
        self.lang_row = Adw.ComboRow(title=_("Language"),
                                     model=Gtk.StringList.new([_(lbl) for _c, lbl in LANGUAGES]))
        current = self.cfg.get("language", "auto")
        self.lang_row.set_selected(next((i for i, (c, _l) in enumerate(LANGUAGES) if c == current), 0))
        self.lang_row.connect("notify::selected", self.on_language)
        general.add(self.lang_row)
        page.add(general)

        self.load()

    # ---------- background work ----------

    def run(self, work, done):
        """Run work() in a thread (HID calls block), then done(result) or an error toast."""
        self.set_busy(True)

        def worker():
            try:
                res, err = work(), None
            except redex.RedexError as e:
                res, err = None, _(str(e))
            except Exception as e:  # unexpected: still tell the user
                res, err = None, f"{type(e).__name__}: {e}"
            GLib.idle_add(finish, res, err)

        def finish(res, err):
            self.set_busy(False)
            if err is None:
                done(res)
            else:
                self.on_error(err)
            return False

        threading.Thread(target=worker, daemon=True).start()

    def set_busy(self, busy):
        self.spinner.set_visible(busy)
        self.refresh_btn.set_sensitive(not busy)
        self.stack.get_child_by_name("settings").set_sensitive(not busy)

    def on_error(self, msg):
        if self.block is None:
            self.error_page.set_description(msg)
            self.stack.set_visible_child_name("error")
        else:
            self.toasts.add_toast(Adw.Toast(title=_("Error: {msg}", msg=msg), timeout=6))
            self.show_block(self.block)   # put the widgets back to the real state

    # ---------- state <-> widgets ----------

    def load(self):
        self.run(lambda: redex.read_state(), self.show_block)

    def show_block(self, block):
        self.block = block
        self.updating = True
        try:
            active, count = block[redex.DPI_LEVEL] >> 4, block[redex.DPI_LEVEL] & 0x0F
            colors = [block[redex.DPI_COLORS + 3 * i:redex.DPI_COLORS + 3 * i + 3] for i in range(count)]
            if 1 <= active <= count:
                self.top_color.set_rgba(rgba_from_bytes(colors[active - 1]))
            self.top_levels.set_subtitle("  ".join(f"{i + 1}: #{c.hex()}" for i, c in enumerate(colors))
                                         + "   " + _("(active: {n})", n=active))
            eff = block[redex.EFFECT]
            idx = next((i for i, (n, _l) in enumerate(EFFECT_LABELS) if n == eff), None)
            if idx is not None:
                self.effect_row.set_selected(idx)
            self.bottom_color.set_rgba(rgba_from_bytes(block[redex.STATIC_COLOR:redex.STATIC_COLOR + 3]))
        finally:
            self.updating = False
        self.stack.set_visible_child_name("settings")

    def apply(self, edit, message):
        def done(block):
            self.show_block(block)
            self.toasts.add_toast(Adw.Toast(title=message, timeout=2))
        self.run(lambda: redex.modify(edit), done)

    # ---------- accent following ----------

    def update_follow_ui(self):
        on = self.follow_row.get_active()
        self.follow_top.set_sensitive(on)
        self.follow_bottom.set_sensitive(on)
        top_auto = on and self.follow_top.get_active()
        bottom_auto = on and self.follow_bottom.get_active()
        self.top_row.set_sensitive(not top_auto)
        self.top_row.set_subtitle(_("Set by the accent color") if top_auto else "")
        self.effect_row.set_sensitive(not bottom_auto)
        self.bottom_row.set_sensitive(not bottom_auto)
        self.bottom_row.set_subtitle(_("Set by the accent color") if bottom_auto
                                     else _("Switches to the “Static color” effect"))

    def on_follow_changed(self, *_a):
        if self.updating:
            return
        self.cfg.update(follow_accent=self.follow_row.get_active(),
                        top=self.follow_top.get_active(), bottom=self.follow_bottom.get_active())
        redex_accent.save_config(self.cfg)
        self.update_follow_ui()
        follow = self.cfg["follow_accent"] and (self.cfg["top"] or self.cfg["bottom"])

        def work():
            if follow:
                redex_accent.enable_service()
                GLib.usleep(2_500_000)   # the service applies after a short debounce
            else:
                redex_accent.disable_service()
            return redex.read_state()

        def done(block):
            self.show_block(block)
            self.toasts.add_toast(Adw.Toast(
                title=_("The LEDs follow the accent color") if follow else _("Accent color following turned off"),
                timeout=2))
        self.run(work, done)

    # ---------- handlers ----------

    def on_top_color(self, btn, _pspec):
        if self.updating:
            return
        color = bytes_from_rgba(btn.get_rgba())
        self.apply(lambda b: redex.set_top(b, color), _("Top LED: #{hex}", hex=color.hex()))

    def on_bottom_color(self, btn, _pspec):
        if self.updating:
            return
        color = bytes_from_rgba(btn.get_rgba())
        self.apply(lambda b: redex.set_bottom(b, color), _("Bottom LED: #{hex}", hex=color.hex()))

    def on_effect(self, row, _pspec):
        if self.updating:
            return
        num, label = EFFECT_LABELS[row.get_selected()]

        def edit(b):
            b[redex.EFFECT] = num
        self.apply(edit, _("Bottom LED: {label}", label=_(label)))

    def on_language(self, row, _pspec):
        self.cfg["language"] = LANGUAGES[row.get_selected()][0]
        redex_accent.save_config(self.cfg)
        self.toasts.add_toast(Adw.Toast(title=_("Takes effect when the app is restarted"), timeout=4))

    def on_restore(self, *_a):
        dlg = Adw.AlertDialog(
            heading=_("Restore?"),
            body=_("The mouse gets back the settings it had before the first change made on Linux."))
        dlg.add_response("cancel", _("Cancel"))
        dlg.add_response("restore", _("Restore"))
        dlg.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)

        def chosen(_dlg, response):
            if response == "restore":
                def edit(b):
                    b[:] = redex.load_backup()
                self.apply(edit, _("Original settings restored"))
        dlg.connect("response", chosen)
        dlg.present(self)


class RedexApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or RedexWindow(self)
        win.present()


def main(argv=None):
    return RedexApp().run(argv if argv is not None else [sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
