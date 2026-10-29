# Redex RGB

RGB lighting control for the **Trust GXT 926 Redex II** wireless mouse on Linux
(USB dongle `145F:0320`, Sino Wealth chip). The vendor software is Windows-only and
does not work under Wine.

- **GTK4 / libadwaita app**: top LED color, bottom LED effect and color, restore.
- **GNOME accent color sync**: the LEDs follow the system accent color, the same way
  MControlCenter does it for MSI keyboards (a background user service).
- **Command line**: `redex top purple`, `redex bottom 0000ff`, `redex effect rainbow-wave`, …
- English and Hungarian interface.

> Not affiliated with Trust. Tested with one Redex II on CachyOS / GNOME 51.
> Use at your own risk; the protocol was reverse engineered.

## Install (Arch / CachyOS / Manjaro)

```sh
git clone https://github.com/RosenthalAlex/redex-rgb.git
cd redex-rgb
makepkg -si
```

Unplug and replug the dongle once (or run
`sudo udevadm trigger --subsystem-match=hidraw`), so the udev rule gives your user access.

Then open **Redex RGB** from the app grid.

## Usage

| Command | What it does |
|---|---|
| `redex` | open the window |
| `redex status` | show the current settings |
| `redex top purple` | top LED: one color on every DPI level |
| `redex top ff8000 --level 3` | top LED color of DPI level 3 |
| `redex bottom 0000ff` | bottom LED: static color |
| `redex effect rainbow-wave` | bottom LED effect (`redex effects` lists them) |
| `redex restore` | write back the settings the mouse had before the first change |
| `redex -n …` | dry run: show the changes, write nothing |

Colors are `RRGGBB` or a name: red, green, blue, yellow, cyan, purple, orange, pink, white, off.

The **top LED** always shows the color of the active DPI level, so a single static color
means every DPI level gets the same color. The **bottom LED** runs the effect.

### Accent color

Turn on *Follow the accent color* in the app. It enables `redex-accent.service`
(a systemd user service, starts with every graphical login). The accent color is made
LED-friendly like MControlCenter does it (same hue, saturation ×1.15, full brightness),
so the mouse matches an MSI keyboard. There is no fade: every change is written to the
mouse's memory, so it is written once.

```sh
journalctl --user -u redex-accent.service -f   # watch it
```

## How it works

The mouse is configured through HID feature reports on the dongle's interface 1: a
read command on report 5 (`05 21 …`), then the 146-byte config block on report 8, and a
single write `08 21 00 92 00 00 00 00 + block`. Every change is read–modify–write and is
read back. Details: [docs/PROTOCOL.md](docs/PROTOCOL.md).

The first run saves the original block to `~/.local/share/redex/backup_mode2.bin`;
`redex restore` writes it back.

`tools/` has the scripts used for reverse engineering (dump, single-field writes,
effect scan). They are not installed.

---

## Magyarul

Linuxos RGB-vezérlő a **Trust GXT 926 Redex II** vezeték nélküli egérhez. Grafikus
program (felső LED színe, alsó LED effektje és színe, visszaállítás), a GNOME
kiemelőszín követése (mint az MSI billentyűzeteknél az MControlCenter), és parancssor.

**Telepítés:** `git clone`, majd a mappában `makepkg -si`. Utána egyszer húzd ki és dugd
vissza a dongle-t. A program az alkalmazások között **Redex RGB** néven található.

**Nyelv:** a program a rendszer nyelvét követi; a *Nyelv* menüben magyarra is állítható.

**Kiemelőszín:** a programban a *Kövesse a kiemelőszínt* kapcsolóval. Ez bekapcsolja a
`redex-accent.service` felhasználói szolgáltatást, ami minden bejelentkezéskor elindul.

A protokoll leírása: [docs/PROTOCOL.md](docs/PROTOCOL.md) (magyarul).

## License

MIT
