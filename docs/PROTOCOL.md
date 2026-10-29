# Trust GXT 926 Redex II – protokoll

Forrás: a Trust telepítő (`TurstSetup.exe`, Inno Setup 5.3.3) → `innoextract` → `app/OemDrv.exe`
(natív MFC, i386, nem packelt, `CDev24G` osztály). A címek az OemDrv.exe-ben értendők.
Minden, ami „élőben igazolva” jelzésű, a valódi egéren lett kipróbálva (2026-10-29).

## Eszköz

- USB `145F:0320` (dongle), HID név `SINO WEALTH Trust REDEX V2 Wireless`.
- Az 1-es interfész hidraw node-ja hordozza a gyártói reportokat:

| Report | Típus | Hossz (ID-vel) | Szerep |
|---|---|---|---|
| 5 | feature (ff00) | 8 | parancs (`SendCmd` / `GetCmd`) |
| 6 | feature (ff01) | 8 | – (csak egy másik eszközváltozatnál adatcsatorna) |
| 7 | input | 8 | értesítések |
| 8 | feature (ff00) | 520 | konfigurációs blokk (`SendData` / `GetData`) |

## Alapműveletek

| Név (debug string) | Cím | Művelet |
|---|---|---|
| `SendCmd` | 0x4125c0 | SET_FEATURE report 5: `05 c0 c1 c2 c3 c4 00 00` |
| `GetCmd`  | 0x4126b0 | GET_FEATURE report 5 → az [1] a parancs visszhangja, utána a válasz |
| `SendData`| 0x4127c0 | SET_FEATURE report 8, 520 bájt |
| `GetData` | 0x412890 | GET_FEATURE report 8 → a blokk a 8. bájttól |

A szoftver minden hívást 3-szor próbál, 200 ms szünettel.

## Mode (nem profil!)

A `11 / 21 / 31` bájt a „mode”-ot választja (`FindHIDDevice`, 0x41204e–0x4120e4): ha a PID a
Cfg.ini `PID2` listájában van (nálunk 0320), mode = 2, különben 1 (a `[MS] SingleMode` kulcs
1-re kényszerítené, de nincs beállítva). **Ennél az egérnél csak a mode 2 (`0x21`) írása
érvényesül** (élőben igazolva: a `08 11 …` írás hibát nem adott, de nem változott semmi).

## Parancsok

| Parancs | Utána | Jelentés |
|---|---|---|
| `05 80 00 …` | GetCmd | állapot; válasz `05 80 01 01 …` = online |
| `05 21 00 …` | GET report 8 | konfigurációs blokk olvasása (mode 2) |
| `05 01 00 …` | GetCmd | „Psd” azonosító (Cfg.ini `PSD=39,32,30,31`) |
| `05 90 00 …` | GetCmd | ha [1]==0x10: szint + 16 bites érték |
| `05 51 / 52 00 …` | GET report 8 | 10 bájtos adat (DPI/LOD szint) |
| `1b <lod> …` | – | LOD beállítása (0x412ef0) |

**Írás** (0x412bb0): egyetlen SET_FEATURE report 8, 520 bájt:

```
08 21 00 92 00 00 00 00 | <146 bájtos blokk> | 00 … 00
```

A `92` a blokk hossza (az egér 154 bájtot ad vissza: 8 fejléc + 146). A szoftver 148 bájtot
másol, az utolsó kettő nulla. Mindig read–modify–write: kiolvas, módosít, visszaír.
Checksum nincs. **Élőben igazolva.**

## A blokk (offset a blokkon belül; a reportban +8)

| Offset | Tartalom |
|---|---|
| 0x00 | `0x64` (a szoftver mindig ezt írja) |
| 0x02 | low nibble: polling (1=125, 2=250, 3=500, 4=1000 Hz); bit7: külön X/Y DPI |
| 0x03 | high nibble: aktív DPI-szint (1-től), low nibble: szintek száma |
| 0x05–0x14 | 8 DPI-szint X, 2 bájt/szint, hardverkód (Cfg.ini `DPIHW`; 0x0b = 1200 DPI) |
| 0x15–0x24 | 8 DPI-szint Y |
| **0x25–0x3c** | **8 DPI-szín, RGB → a felső LED az aktív szint színét mutatja** |
| **0x3d** | **alsó LED effekt** (0–10, lásd lent) |
| 0x3e / 0x3f | effekt 1: param (sebesség<<4 \| fényerő) / irány |
| 0x40, **0x41–0x43** | effekt 2 (statikus): param, **szín RGB** |
| 0x44, 0x45, 0x46– | effekt 3: param, színek száma, max. 7 szín |
| 0x5b / 0x5c | effekt 4 / 5: param |
| 0x5d, 0x5e– | effekt 6: param, színek |
| 0x7c, 0x7d– | effekt 7: param, 2 szín |
| 0x83 / 0x84 / 0x85 | effekt 8 / 9 / 10: param |
| 0x8b–0x8f | ismeretlen (mód, param, szín – 0x41508e); élőben átírva: nincs látható hatás |
| 0x90 | `0xA5` (mágikus bájt) |
| 0x91 | flagek |

A szerkezet offsetre egyezik az OpenRGB Glorious Model O (Sinowealth) blokkjával, 16 bájttal
eltolva (itt a DPI Y-nak külön helye van).

## Két LED (élőben igazolva)

- **Felső (fő) LED:** mindig az aktív DPI-szint színe (0x25 + 3·(szint−1)). Statikus színhez
  minden szint ugyanazt kapja. A DPI-gombra a szín vált.
- **Alsó LED(-sor):** az effekt (0x3d), több LED (egyszerre több szín is látszik).

## Alsó LED effektjei (élő `effectscan`)

| ID | Látvány |
|---|---|
| 0 | ki |
| 1 | szivárvány hullám |
| 2 | statikus szín (0x41–0x43) |
| 3 | lélegző (7 szín) |
| 4 | szivárvány körforgás |
| 5 | átmenetes színváltás |
| 6 | több szín egymás mellett, statikus |
| 7 | két szín váltakozva, körforgással |
| 8 | véletlen színek egymás mellett |
| 9 | hullámzó véletlen színek |
| 10 | semmi nem látszott (param 0x02 – talán túl kis fényerő) |

## Nyitott kérdések

- Az effektek sebesség/fényerő nibble-jeinek értéktartománya.
- A 10-es effekt.
- A 0x8b–0x8f mezők szerepe.
- Mit jelent a `05 11` (mode 1) blokk ennél az egérnél (olvasható, írása nem érvényesül).
