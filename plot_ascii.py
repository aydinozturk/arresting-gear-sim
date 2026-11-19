#!/usr/bin/env python3
"""out/arrest_nominal.csv dosyasini terminalde ASCII grafik olarak cizer.

Bagimlilik yok. Kullanim:  python3 plot_ascii.py [csv]
"""
import sys

W, H = 72, 16


def load(path):
    rows = []
    with open(path) as fh:
        hdr = fh.readline().strip().split(",")
        for line in fh:
            rows.append([float(c) for c in line.strip().split(",")])
    return hdr, rows


def plot(xs, series, title, ylab):
    lo = min(min(s[1]) for s in series)
    hi = max(max(s[1]) for s in series)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    x0, x1 = xs[0], xs[-1]
    grid = [[" "] * W for _ in range(H)]
    marks = "*o+."
    for si, (name, ys) in enumerate(series):
        ch = marks[si % len(marks)]
        for x, y in zip(xs, ys):
            cx = int((x - x0) / (x1 - x0) * (W - 1))
            cy = int((hi - y) / (hi - lo) * (H - 1))
            if 0 <= cx < W and 0 <= cy < H:
                grid[cy][cx] = ch
    print()
    print(f"  {title}   [{ylab}]")
    for r, row in enumerate(grid):
        val = hi - (hi - lo) * r / (H - 1)
        print(f"  {val:9.1f} |" + "".join(row))
    print(f"  {'':9} +" + "-" * W)
    print(f"  {'':9}  {x0:<10.2f}{'':>{W-22}}{x1:>10.2f}  [t, s]")
    lg = "   ".join(f"{marks[i % len(marks)]} {n}" for i, (n, _) in enumerate(series))
    print(f"  {'':9}  {lg}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "out/arrest_nominal.csv"
    hdr, rows = load(path)
    c = {n: i for i, n in enumerate(hdr)}
    t = [r[c["t"]] for r in rows]
    plot(t, [("v (ucak)", [r[c["v"]] for r in rows]),
             ("v_ref", [r[c["v_ref"]] for r in rows])],
         "HIZ ve REFERANS", "m/s")
    plot(t, [("kanca yuku", [r[c["hook_N"]] / 1e3 for r in rows])],
         "KANCA YUKU", "kN")
    plot(t, [("T su turbini", [r[c["T_twister"]] / 1e3 for r in rows]),
             ("T motor", [r[c["T_motor"]] / 1e3 for r in rows])],
         "MIL TORKU PAYLASIMI", "kN.m")
    plot(t, [("DC bara", [r[c["vbus"]] for r in rows])], "DC BARA GERILIMI", "V")
