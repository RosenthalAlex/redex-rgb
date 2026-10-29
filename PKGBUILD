# Builds from this checkout: run `makepkg -si` in the repository root.
pkgname=redex-rgb
pkgver=0.1.0
pkgrel=1
pkgdesc="RGB lighting control for the Trust GXT 926 Redex II wireless mouse (GTK app, CLI, GNOME accent color sync)"
arch=('any')
url="https://github.com/RosenthalAlex/redex-rgb"
license=('MIT')
depends=('python' 'python-gobject' 'gtk4' 'libadwaita')

package() {
  cd "$startdir"
  install -Dm644 redex.py redex_gui.py redex_accent.py i18n.py -t "$pkgdir/usr/lib/redex/"
  install -Dm755 main.py "$pkgdir/usr/lib/redex/main.py"
  python -m compileall -q -d /usr/lib/redex "$pkgdir/usr/lib/redex"
  install -d "$pkgdir/usr/bin"
  ln -s /usr/lib/redex/main.py "$pkgdir/usr/bin/redex"

  install -Dm644 data/70-redex.rules -t "$pkgdir/usr/lib/udev/rules.d/"
  install -Dm644 data/redex-accent.service -t "$pkgdir/usr/lib/systemd/user/"
  install -Dm644 data/io.github.redex.Control.desktop -t "$pkgdir/usr/share/applications/"
  install -Dm644 LICENSE -t "$pkgdir/usr/share/licenses/$pkgname/"
  install -Dm644 README.md docs/PROTOCOL.md -t "$pkgdir/usr/share/doc/$pkgname/"
}
