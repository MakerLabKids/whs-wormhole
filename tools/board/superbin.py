#!/usr/bin/env python3
"""Draws the two 'super bin' pages for docs/board/index.html: every sensor we have or could add.
   superbin.py portrait   -> the clear-cylinder worm viewer (letter portrait)
   superbin.py landscape  -> a black tote, cut away, with several of the same sensor (letter landscape)
Prints an <svg>. NOW = in our bins today; ADD-ON = parts we can add, or on the wish list."""
import sys

NAVY, MUTED, RED, GREEN, ORANGE = "#1b2f5e", "#5b6475", "#c8102e", "#2f7d3a", "#e8762c"

def tag(x, y, kind, anchor):
    w = 34 if kind == "NOW" else 50
    x0 = x if anchor == "start" else x - w
    if kind == "NOW":
        box = f'<rect x="{x0}" y="{y-11}" width="{w}" height="15" rx="7.5" fill="{GREEN}"/>'
        tc = "#fff"
    else:
        box = f'<rect x="{x0+.75}" y="{y-10.25}" width="{w-1.5}" height="13.5" rx="6.75" fill="#fff" stroke="{ORANGE}" stroke-width="1.5" stroke-dasharray="3 2"/>'
        tc = ORANGE
    return box + f'<text x="{x0+w/2}" y="{y}" font-size="9.5" font-weight="900" fill="{tc}" text-anchor="middle" letter-spacing=".08em">{kind}</text>', w

def callout(side, x, y, kind, title, lines, target, color, fs=15, ls=13, lh=15, run=222):
    """side 'L': text starts at x; 'R': text ends at x. Leader from the text block to target."""
    anchor = "start" if side == "L" else "end"
    t, w = tag(x, y, kind, anchor)
    tx = x + w + 6 if side == "L" else x - w - 6
    out = [t, f'<text x="{tx}" y="{y+1}" font-size="{fs}" font-weight="800" fill="{color}" text-anchor="{anchor}">{title}</text>']
    for i, l in enumerate(lines):
        out.append(f'<text x="{x}" y="{y+19+i*lh}" font-size="{ls}" font-weight="600" fill="{MUTED}" text-anchor="{anchor}">{l}</text>')
    dash = '' if kind == "NOW" else ' stroke-dasharray="5 4"'
    ly = y + 4 + (len(lines)) * lh / 2
    targets = target if isinstance(target[0], (list, tuple)) else [target]
    for (txx, tyy) in targets:
        if side == "L":
            sx = x + run
            out.append(f'<path d="M{x} {y+8+len(lines)*lh} L{sx} {y+8+len(lines)*lh} L{txx} {tyy}" fill="none" stroke="{color}" stroke-width="1.8"{dash}/>')
        else:
            sx = x - run
            out.append(f'<path d="M{x} {y+8+len(lines)*lh} L{sx} {y+8+len(lines)*lh} L{txx} {tyy}" fill="none" stroke="{color}" stroke-width="1.8"{dash}/>')
        out.append(f'<circle cx="{txx}" cy="{tyy}" r="4" fill="{color}"/>')
    return "\n".join(out)

def worm(d, c="#e8879b", w=7):
    return f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round"/>'

# ---------------------------------------------------------------- parts (small drawings)
def board(x, y, w=26, h=18, c="#5b3fa8"):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2.5" fill="{c}"/><circle cx="{x+w/2}" cy="{y+h/2}" r="3.2" fill="#d9d2ef"/>'

def probe_ds(x, y0, y1):   # cable from y0 down to a steel tip at y1
    return (f'<path d="M{x} {y0} L{x} {y1-26}" stroke="#20252d" stroke-width="3.5"/>'
            f'<rect x="{x-5}" y="{y1-28}" width="10" height="28" rx="5" fill="#c7cdd6" stroke="#8b94a3" stroke-width="1"/>')

def probe_moist(x, y0, y1):
    return (f'<rect x="{x-9}" y="{y0}" width="18" height="{y1-y0}" rx="3" fill="#1d2430"/>'
            f'<rect x="{x-6}" y="{y0+8}" width="12" height="{(y1-y0)*.35}" rx="2" fill="#2f3a4c"/>'
            f'<path d="M{x-6} {y1-4} L{x} {y1+6} L{x+6} {y1-4}" fill="#1d2430"/>')

def vib_motor(x, y):
    return (f'<circle cx="{x}" cy="{y}" r="10" fill="#9aa4b2" stroke="#5b6475" stroke-width="2"/><circle cx="{x}" cy="{y}" r="3" fill="#5b6475"/>'
            f'<g fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".9"><path d="M{x-16} {y-7} q-5 7 0 14"/><path d="M{x-22} {y-11} q-7 11 0 22"/><path d="M{x+16} {y-7} q5 7 0 14"/><path d="M{x+22} {y-11} q7 11 0 22"/></g>')

def geophone(x, y):     # sits on the table, spike into it
    return (f'<rect x="{x-9}" y="{y-20}" width="18" height="20" rx="3" fill="#2a9fd8"/><rect x="{x-9}" y="{y-20}" width="18" height="6" rx="3" fill="#1b6fa0"/>'
            f'<path d="M{x-3} {y} L{x} {y+9} L{x+3} {y}" fill="#5b6475"/>')

def servo(x, y, flip=False):  # SG90 body with an arm reaching toward x (flip: arm to the right)
    s = -1 if not flip else 1
    return (f'<rect x="{x-18}" y="{y-11}" width="36" height="22" rx="3" fill="#2a6fd8"/><rect x="{x-24}" y="{y-3}" width="48" height="5" rx="2" fill="#2a6fd8"/>'
            f'<circle cx="{x+s*8}" cy="{y-11}" r="5" fill="#fff"/><path d="M{x+s*8} {y-11} L{x+s*30} {y-22}" stroke="#fff" stroke-width="5" stroke-linecap="round"/>'
            f'<path d="M{x+s*8} {y-11} L{x+s*30} {y-22}" stroke="#d6dde8" stroke-width="2.5" stroke-linecap="round"/>')

def fan(x, y, r=22):
    return (f'<g transform="translate({x} {y})"><rect x="{-r}" y="{-r}" width="{2*r}" height="{2*r}" rx="7" fill="#2f3540"/><circle r="{r*.8}" fill="#3e4652"/>'
            '<g fill="#9aa4b2"><path d="M0 0 q-4 -15 6 -15 q4 8 -6 15z"/><path d="M0 0 q15 -4 15 6 q-8 4 -15 -6z"/><path d="M0 0 q4 15 -6 15 q-4 -8 6 -15z"/><path d="M0 0 q-15 4 -15 -6 q8 -4 15 6z"/></g>'
            '<circle r="4" fill="#20252d"/></g>')

def ldr(x, y):
    return (f'<circle cx="{x}" cy="{y}" r="8" fill="#f2b705" stroke="#b8860b" stroke-width="1.5"/>'
            f'<path d="M{x-5} {y-2} q2.5 -4 5 0 t5 0" fill="none" stroke="#7a5038" stroke-width="1.6"/><path d="M{x-5} {y+2} q2.5 -4 5 0 t5 0" fill="none" stroke="#7a5038" stroke-width="1.6"/>')

def mic(x, y):
    return (f'<rect x="{x-13}" y="{y-6}" width="26" height="14" rx="2.5" fill="#5b3fa8"/><circle cx="{x}" cy="{y-10}" r="8" fill="#20252d"/><circle cx="{x}" cy="{y-10}" r="4.5" fill="#5b6475"/>')

def screen(x, y, w=92, h=78, label="The Wrigglers"):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#1d2430"/>'
            f'<rect x="{x+8}" y="{y+8}" width="{w-16}" height="{h*.6}" rx="3" fill="#0b1220"/>'
            f'<g font-family="monospace" font-size="8.6" fill="#e6f3ff" font-weight="700"><text x="{x+13}" y="{y+21}">{label}</text>'
            f'<text x="{x+13}" y="{y+34}">AIR 24.4C 39%</text><text x="{x+13}" y="{y+46}" fill="#a6e07f">MOIST  62%</text></g>'
            f'<circle cx="{x+w/2-12}" cy="{y+h-12}" r="5" fill="#fff" stroke="{ORANGE}" stroke-width="1.5" stroke-dasharray="2.5 2"/>'
            f'<circle cx="{x+w/2+12}" cy="{y+h-12}" r="5" fill="#fff" stroke="{ORANGE}" stroke-width="1.5" stroke-dasharray="2.5 2"/>')

def wifi(x, y, s=.5):
    return (f'<g transform="translate({x} {y}) scale({s})" fill="none" stroke="#2a9fd8" stroke-width="9" stroke-linecap="round">'
            '<path d="M-26 0 a40 40 0 0 1 52 0"/><path d="M-40 -16 a62 62 0 0 1 80 0" opacity=".7"/><path d="M-54 -32 a84 84 0 0 1 108 0" opacity=".45"/></g>')

def pico(x, y, w=58, h=16):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#2e8b3e"/><rect x="{x+w/2-6}" y="{y+3}" width="12" height="10" fill="#20252d"/>'
            + "".join(f'<circle cx="{x+4+i*5}" cy="{y+2.5}" r="1.1" fill="#e9d48a"/><circle cx="{x+4+i*5}" cy="{y+h-2.5}" r="1.1" fill="#e9d48a"/>' for i in range(int((w-6)/5))))

def accel(x, y):
    return f'<rect x="{x}" y="{y}" width="16" height="12" rx="2" fill="#c8102e"/><rect x="{x+5}" y="{y+3}" width="6" height="6" fill="#20252d"/>'

def soil_specks(xs, ys):
    import random
    r = random.Random(7)
    return "".join(f'<circle cx="{r.uniform(*xs):.0f}" cy="{r.uniform(*ys):.0f}" r="{r.uniform(1.5,3):.1f}"/>' for _ in range(40))

DEFS = '''<defs>
  <linearGradient id="sb-soil" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8a5a3c"/><stop offset=".5" stop-color="#5b3a29"/><stop offset="1" stop-color="#3a2419"/></linearGradient>
  <linearGradient id="sb-glass" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#cfe6f7" stop-opacity=".55"/><stop offset=".5" stop-color="#eef7fd" stop-opacity=".2"/><stop offset="1" stop-color="#cfe6f7" stop-opacity=".55"/></linearGradient>
  <radialGradient id="sb-glow" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ff3b5c" stop-opacity=".85"/><stop offset="1" stop-color="#ff3b5c" stop-opacity="0"/></radialGradient>
  <linearGradient id="sb-tote" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b2f36"/><stop offset="1" stop-color="#15181d"/></linearGradient>
</defs>'''

# ---------------------------------------------------------------- portrait: the worm viewer
def portrait():
    cx, rx, ry = 380, 108, 17
    L, R = cx - rx, cx + rx
    top, bed, bot = 204, 334, 728
    o = [f'<svg viewBox="0 0 760 800" role="img" aria-label="The super bin: a clear worm-viewer cylinder with every sensor we have or could add, each one labeled" font-family="Nunito Sans, Arial">', DEFS]
    # table
    o.append(f'<rect x="120" y="{bot+20}" width="520" height="6" rx="3" fill="#d9cdb8"/><ellipse cx="{cx}" cy="{bot+18}" rx="{rx+14}" ry="8" fill="#000" opacity=".10"/>')
    # bedding
    o.append(f'<path d="M{L+8} {bed} L{L+8} {bot} A{rx-8} {ry} 0 0 0 {R-8} {bot} L{R-8} {bed} Z" fill="url(#sb-soil)"/><ellipse cx="{cx}" cy="{bed}" rx="{rx-8}" ry="{ry-3}" fill="#9a6a48"/>')
    o.append(f'<g fill="#b38358" opacity=".55">{soil_specks((L+16, R-16), (bed+16, bot-6))}</g>')
    o.append(f'<path d="M{cx-60} {bed-2} q12 -12 26 0 q-13 6 -26 0z" fill="#6fbf3f"/><path d="M{cx+30} {bed} q9 -10 22 -2 q-10 8 -22 2z" fill="#f08a2c"/>')
    o += [worm(f"M{L+18} 390 q14 -12 28 0 t28 0"), worm(f"M{cx+18} 470 q12 10 24 0 t24 0", "#d96d84"), worm(f"M{L+24} 640 q12 -10 24 0 t24 2"),
          worm(f"M{cx+30} 690 q10 8 20 0 t20 -4", "#d96d84", 6), worm(f"M{cx-40} 520 q10 -8 20 0 t20 0", "#e8879b", 6)]
    # soil temperature probes at three depths, moisture probe, vibration motor
    o += [probe_ds(cx - 54, top, 440), probe_ds(cx - 4, top, 560), probe_ds(cx + 40, top, 680)]
    o.append(probe_moist(cx + 74, 300, 420))
    o.append(f'<path d="M{cx-84} {top} L{cx-84} 600" stroke="#20252d" stroke-width="2.5"/>' + vib_motor(cx - 84, 610))
    # under the lid: laser, light sensor, air sensor
    under = (f'<path d="M{cx-79} {top} L{cx-79} {top+28}" stroke="#20252d" stroke-width="2"/><rect x="{cx-92}" y="{top+28}" width="26" height="11" rx="3" fill="#111"/><line x1="{cx-79}" y1="{top+39}" x2="{cx-79}" y2="{bed-4}" stroke="#ff2d55" stroke-width="3" stroke-dasharray="6 5"/><circle cx="{cx-79}" cy="{bed-2}" r="11" fill="url(#sb-glow)"/>'
             f'<path d="M{cx-26} {top} L{cx-26} {top+30}" stroke="#20252d" stroke-width="2"/>' + ldr(cx - 26, top + 38) +
             f'<path d="M{cx+56} {top} L{cx+56} {top+30}" stroke="#20252d" stroke-width="2"/>' + board(cx + 44, top + 30))
    # the glass
    o.append(f'<path d="M{L} {top-6} L{L} {bot} A{rx} {ry+3} 0 0 0 {R} {bot} L{R} {top-6}" fill="url(#sb-glass)" stroke="#9cc3e0" stroke-width="3"/>')
    o.append(f'<rect x="{L+12}" y="{top+30}" width="9" height="{bot-top-80}" rx="4.5" fill="#fff" opacity=".5"/><rect x="{L+28}" y="{top+40}" width="4" height="{bot-top-120}" rx="2" fill="#fff" opacity=".4"/>')
    o.append(under)
    # fan on the glass, inside near the top
    o.append(fan(R - 26, top + 78, 20))
    # outside: room air sensor clipped to the glass, the thumper, geophones
    o.append(f'<path d="M{R+6} {top-4} C {R+30} {top+40}, {R+26} 300, {R+22} 318" fill="none" stroke="#20252d" stroke-width="2"/>' + board(R + 8, 318, 28, 20))
    o.append(servo(R + 34, 520))
    o += [geophone(L - 46, bot + 20), geophone(L - 18, bot + 34), geophone(R + 18, bot + 34), geophone(R + 46, bot + 20)]
    # the lid
    o.append(f'<path d="M{L-10} {top-20} L{L-10} {top-2} A{rx+10} {ry+8} 0 0 0 {R+10} {top-2} L{R+10} {top-20} Z" fill="#d9ab00"/><ellipse cx="{cx}" cy="{top-20}" rx="{rx+10}" ry="{ry+8}" fill="#f2c400"/>')
    dots = []
    for j, yy in enumerate(range(top - 34, top - 6, 7)):
        for i in range(-12, 13):
            xx = cx + i * 8 + (4 if j % 2 else 0)
            if ((xx - cx) / (rx + 2)) ** 2 + ((yy - (top - 20)) / (ry + 4)) ** 2 < .82 and not (cx - 20 < xx < cx + 58 and yy < top - 12):
                dots.append(f'<circle cx="{xx}" cy="{yy}" r="2.4"/>')
    o.append(f'<g fill="#c99a00">{"".join(dots)}</g>')
    # on the lid: Pico, screen, mic, accelerometer, Wi-Fi
    o.append(pico(cx - 64, top - 44))
    o.append(screen(cx + 2, top - 124))
    o.append(f'<rect x="{cx-2}" y="{top-48}" width="100" height="10" rx="4" fill="#111"/>')
    o.append(mic(cx - 78, top - 56))
    o.append(accel(cx + 70, top - 20))
    o.append(wifi(cx + 48, top - 140))
    # callouts
    C = []
    C.append(callout("L", 12, 26, "ADD-ON", "MICROPHONE", ["how loud the room gets.", "Do worms notice?"], (cx - 78, top - 62), "#5b3fa8"))
    C.append(callout("L", 12, 96, "NOW", "3D-PRINTED LID", ["designed and printed by us;", "a honeycomb of air holes"], (L - 4, top - 14), "#b8860b"))
    C.append(callout("L", 12, 166, "NOW", "LASER RANGER", ["times a flash of infrared light", "off the bedding, to the mm"], (cx - 92, top + 34), RED))
    C.append(callout("L", 12, 236, "ADD-ON", "LIGHT SENSOR", ["how bright it gets", "inside the glass"], (cx - 26, top + 38), "#b8860b"))
    C.append(callout("L", 12, 330, "NOW", "SOIL TEMPERATURE", ["waterproof probes; many share", "one wire, so try three depths"], [(cx - 54, 426), (cx - 4, 546), (cx + 40, 666)], "#7a5038"))
    C.append(callout("L", 12, 500, "ADD-ON", "VIBRATION MOTOR", ["buried in the bedding, a buzz", "now and then. Do they move?"], (cx - 94, 610), MUTED))
    C.append(callout("L", 12, 640, "ADD-ON", "GEOPHONES x4", ["super-sensitive vibration", "sensors. Can we hear worms?"], [(L - 46, bot + 4), (L - 18, bot + 18)], "#2a9fd8"))
    C.append(callout("R", 748, 26, "NOW", "0.96\" SCREEN", ["128 x 64 pixels. We program it;", "add buttons to flip or pause"], (cx + 94, top - 100), "#2a9fd8"))
    C.append(callout("R", 748, 112, "NOW", "PICO 2 W", ["the brain, on Wi-Fi:", "a reading every minute"], (cx - 6, top - 36), GREEN))
    C.append(callout("R", 748, 190, "ADD-ON", "ACCELEROMETER", ["knows when the lid moves", "(the laser can tell, too)"], (cx + 86, top - 14), RED))
    C.append(callout("R", 748, 262, "NOW", "AIR SENSOR", ["temperature, humidity and", "air pressure in the bin"], (cx + 70, top + 40), "#5b3fa8"))
    C.append(callout("R", 748, 332, "NOW", "FAN", ["on by humidity, soil", "moisture or temperature"], (R - 6, top + 78), ORANGE))
    C.append(callout("R", 748, 402, "ADD-ON", "ROOM AIR SENSOR", ["a second one outside,", "to compare with the bin"], (R + 36, 328), "#5b3fa8"))
    C.append(callout("R", 748, 472, "NOW", "SOIL MOISTURE", ["a capacitive probe: no bare", "metal in the dirt"], (cx + 83, 380), NAVY))
    C.append(callout("R", 748, 572, "ADD-ON", "THE THUMPER", ["a servo that taps the glass.", "Does tapping bother them?"], (R + 6, 506), "#2a6fd8"))
    o.append('\n'.join(C))
    o.append('</svg>')
    return "\n".join(o)

# ---------------------------------------------------------------- landscape: a black tote, cut away
def landscape():
    o = [f'<svg viewBox="0 0 1120 560" role="img" aria-label="A black plastic worm bin, cut away to show several of each sensor: soil temperature probes in a grid at different depths, moisture probes, and more" font-family="Nunito Sans, Arial">', DEFS]
    o.append('<g transform="translate(60 60)">')
    X0, X1, T, B = 250, 750, 150, 430     # front face of the tote
    D = 40                                # depth offset (back edge up and right)
    # table + shadow
    o.append(f'<rect x="140" y="{B+34}" width="720" height="7" rx="3.5" fill="#d9cdb8"/><ellipse cx="{(X0+X1)/2+10}" cy="{B+30}" rx="290" ry="10" fill="#000" opacity=".12"/>')
    # back wall and right wall (dark), floor, then bedding cutaway
    o.append(f'<path d="M{X0+D} {T-D+20} L{X1+D} {T-D+20} L{X1+D} {B-D+18} L{X1} {B} L{X1} {T+20} Z" fill="#1d2026"/>')
    o.append(f'<path d="M{X0} {T+20} L{X0+D} {T-D+20} L{X1+D} {T-D+20} L{X1} {T+20} Z" fill="#30343c"/>')
    bed = 230
    o.append(f'<path d="M{X0+6} {bed} L{X0+D} {bed-26} L{X1+D-6} {bed-26} L{X1-6} {bed} Z" fill="#9a6a48"/>')
    o.append(f'<rect x="{X0+6}" y="{bed}" width="{X1-X0-12}" height="{B-bed-6}" fill="url(#sb-soil)"/>')
    o.append(f'<g fill="#b38358" opacity=".55">{soil_specks((X0+16, X1-16), (bed+12, B-14))}</g>')
    o += [worm("M290 300 q14 -12 28 0 t28 0"), worm("M520 360 q12 10 24 0 t24 0", "#d96d84"), worm("M640 280 q12 -10 24 0 t24 2"),
          worm("M400 400 q10 8 20 0 t20 -4", "#d96d84", 6), worm("M600 410 q10 -8 20 0 t20 0", "#e8879b", 6)]
    o.append('<path d="M340 228 q12 -12 26 0 q-13 6 -26 0z" fill="#6fbf3f"/><path d="M560 226 q9 -10 22 -2 q-10 8 -22 2z" fill="#f08a2c"/>')
    # soil temperature grid: 3 columns x 2 rows of depth (front row deep, back row shallow)
    probes = [(300, 300), (420, 360), (540, 300), (660, 380), (360, 410), (600, 412)]
    for x, d in probes:
        o.append(probe_ds(x, T + 10, d))
    for x in (480, 700):
        o.append(probe_moist(x, 200, 300))
    o.append(probe_moist(330, 200, 300))
    o.append(f'<path d="M455 {T+10} L455 380" stroke="#20252d" stroke-width="2.5"/>' + vib_motor(455, 392))
    # under the lid: two lasers, light, air sensor
    for lx in (380, 620):
        o.append(f'<rect x="{lx-13}" y="{T+12}" width="26" height="11" rx="3" fill="#111"/><line x1="{lx}" y1="{T+23}" x2="{lx}" y2="{bed-12}" stroke="#ff2d55" stroke-width="3" stroke-dasharray="6 5"/><circle cx="{lx}" cy="{bed-10}" r="11" fill="url(#sb-glow)"/>')
    o.append(ldr(520, T + 26))
    o.append(board(560, T + 14))
    # front wall: the cutaway edge (left and bottom rims), black plastic
    o.append(f'<path d="M{X0} {T+20} L{X0} {B} L{X1} {B} L{X1} {T+20}" fill="none" stroke="#15181d" stroke-width="12" stroke-linejoin="round"/>')
    o.append(f'<path d="M{X1} {B} L{X1+D} {B-D+18}" stroke="#15181d" stroke-width="12" stroke-linecap="round"/>')
    o.append(f'<path d="M{X1+6} {T+26} L{X1+6} {B-6}" stroke="#2b2f36" stroke-width="2"/>')
    # fan on the right wall
    o.append(fan(X1 + 22, 230, 20))
    # thumper on the left wall (outside), room air sensor outside, geophones at the corners
    o.append(servo(X0 - 34, 330, flip=True))
    o.append(f'<path d="M{X0+10} {T+6} C {X0-30} {T+20}, {X0-40} 210, {X0-44} 236" fill="none" stroke="#20252d" stroke-width="2"/>' + board(X0 - 58, 236, 28, 20))
    o += [geophone(X0 - 26, B + 32), geophone(X1 + 30, B + 32), geophone(X0 + 30, B + 46), geophone(X1 - 26, B + 46)]
    # the lid: black, with vent holes, a lip
    o.append(f'<path d="M{X0-12} {T+6} L{X0+D-6} {T-D+4} L{X1+D+12} {T-D+4} L{X1+12} {T+6} Z" fill="#2b2f36"/>')
    o.append(f'<rect x="{X0-12}" y="{T+6}" width="{X1-X0+24}" height="16" rx="3" fill="#15181d"/>')
    o.append(f'<g fill="#0d0f12">' + "".join(f'<circle cx="{x}" cy="{y}" r="3"/>' for y in (T - 20, T - 6) for x in range(X0 + 40 + (8 if y == T - 6 else 0), X0 + 220, 18)) + '</g>')
    # on the lid
    o.append(pico(430, T - 18))
    o.append(screen(560, T - 92))
    o.append(f'<rect x="556" y="{T-16}" width="100" height="10" rx="4" fill="#111"/>')
    o.append(mic(690, T - 10))
    o.append(accel(380, T - 14))
    o.append(wifi(606, T - 108))
    o.append('</g>')
    # callouts, compact (targets are in the shifted drawing's coordinates)
    C = []
    def c(side, x, y, kind, title, lines, tgt, col):
        tg = [(a + 60, b + 60) for a, b in (tgt if isinstance(tgt[0], (list, tuple)) else [tgt])]
        C.append(callout(side, 10 if side == "L" else 1110, y + 30, kind, title, lines, tg, col, fs=14, ls=12, lh=14, run=262 if side == "L" else 248))
    c("L", 10, 20, "NOW", "3D-PRINTED SCREEN CASE", ["0.96\" screen, 128 x 64 pixels"], (560, T - 70), "#2a9fd8")
    c("L", 10, 76, "NOW", "LASER RANGERS x2", ["bedding level, two spots"], [(380, T + 14), (620, T + 14)], RED)
    c("L", 10, 132, "ADD-ON", "ROOM AIR SENSOR", ["outside, to compare"], (X0 - 44, 246), "#5b3fa8")
    c("L", 10, 228, "NOW", "SOIL TEMPERATURE x6", ["one wire, a grid of depths:", "map the warm spots"], [(300, 290), (420, 350), (360, 400)], "#7a5038")
    c("L", 10, 312, "ADD-ON", "THE THUMPER", ["a servo tapping the wall"], (X0 - 20, 318), "#2a6fd8")
    c("L", 10, 380, "ADD-ON", "GEOPHONES x4", ["one under each corner"], [(X0 - 26, B + 16), (X0 + 30, B + 30)], "#2a9fd8")
    c("R", 990, 20, "ADD-ON", "MICROPHONE", ["how loud the room gets"], (690, T - 18), "#5b3fa8")
    c("R", 990, 76, "ADD-ON", "ACCELEROMETER", ["knows when the lid moves"], (388, T - 8), RED)
    c("R", 990, 132, "NOW", "AIR SENSOR + LIGHT", ["temp, humidity, pressure, light"], [(572, T + 22), (520, T + 26)], "#5b3fa8")
    c("R", 990, 210, "NOW", "FAN", ["on by humidity, moisture or heat"], (X1 + 22, 230), ORANGE)
    c("R", 990, 270, "NOW", "SOIL MOISTURE x3", ["wet here, dry there?"], [(700, 250), (480, 250), (330, 250)], NAVY)
    c("R", 990, 340, "ADD-ON", "VIBRATION MOTOR", ["a buzz now and then"], (465, 392), MUTED)
    o.append('\n'.join(C))
    o.append('</svg>')
    return "\n".join(o)

if __name__ == "__main__":
    print(portrait() if sys.argv[1:] == ["portrait"] else landscape())
