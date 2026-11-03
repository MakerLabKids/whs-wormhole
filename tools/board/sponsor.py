#!/usr/bin/env python3
"""Builds the standalone sponsor pieces from the display board's drawings and photos:
   docs/sponsor/index.html     'Sponsor a Bin' one-sheet (letter portrait, full bleed)
   docs/sponsor/brochure.html  trifold brochure (two letter-landscape sheets, print double-sided, flip on short edge)
Run: python3 tools/board/sponsor.py"""
import os, re

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
BOARD = open(os.path.join(ROOT, "docs/board/index.html")).read()

def cover_bin():
    """The cover's bin drawing without its callouts, cropped to the bin."""
    a = BOARD.index('<div class="hero">'); svg = BOARD[BOARD.index("<svg", a):BOARD.index("</svg>", a) + 6]
    svg = re.sub(r'<!-- callouts -->\s*<g font-family="Nunito Sans, Arial" font-size="15" font-weight="800">.*?</g>\s*', "", svg, flags=re.S)
    svg = svg.replace('viewBox="0 0 760 400"', 'viewBox="196 4 368 394"')
    return svg

BIN = cover_bin()

HEAD = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="icon" href="../favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Nunito+Sans:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
  :root {{ --navy:#1b2f5e; --navy2:#24407e; --red:#c8102e; --orange:#e8762c; --green:#5fae3a; --dgreen:#2f7d3a; --blue:#2a9fd8;
          --yellow:#f2c400; --soil:#5b3a29; --soil2:#7a5038; --cream:#fff8ec; --ink:#1f2633; --muted:#5b6475; --pink:#e8879b; }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{ margin: 0; background: #d9dee6; color: var(--ink); font-family: "Nunito Sans", Arial, sans-serif; }}
  h1, h2, h3, .fd {{ font-family: "Fredoka", "Nunito Sans", Arial, sans-serif; }}
  .bar {{ max-width: {barw}; margin: 18px auto 0; padding: 0 16px; display: flex; gap: 12px; align-items: center; justify-content: space-between;
          flex-wrap: wrap; font-size: 14px; color: #2b3445; }}
  .bar button {{ font: inherit; font-weight: 700; background: var(--navy); color: #fff; border: 0; border-radius: 8px; padding: 9px 16px; cursor: pointer; }}
  .bar a {{ color: var(--navy); }}
  @page {{ size: {pagesize}; margin: 0; }}
  .sheet {{ width: {w}; height: {h}; margin: 18px auto; background: #fff; position: relative; overflow: hidden;
           box-shadow: 0 6px 24px rgba(20,30,50,.18); }}
  @media print {{ body {{ background: #fff; }} .bar {{ display: none; }} .sheet {{ margin: 0; box-shadow: none; break-after: page; }} }}
  @media screen and (max-width: {zoomw}) {{ .sheet {{ zoom: calc(100vw / {zoomin}); }} }}
  .worm {{ fill: none; stroke-linecap: round; }}
{css}
</style>
</head>
<body>
<div class="bar"><span><b>{title}</b> · {barnote} Print with <b>margins: none</b> and <b>background graphics</b> on.</span>
  <button onclick="window.print()">Print</button></div>
'''

PERKS = [
    ("#2a9fd8", '<path d="M5 7h14v10H5z" fill="none" stroke="#fff" stroke-width="2.4"/><path d="M8 11h8M8 14h5" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>',
     "Name the bin", "The team's bin carries your name, on its screen and on the website."),
    ("#e8762c", '<g fill="#fff"><rect x="5" y="5" width="4" height="4"/><rect x="10" y="5" width="4" height="4"/><rect x="15" y="5" width="4" height="4"/><rect x="5" y="10" width="4" height="4"/><rect x="15" y="10" width="4" height="4"/><rect x="5" y="15" width="4" height="4"/><rect x="10" y="15" width="4" height="4"/><rect x="15" y="15" width="4" height="4" opacity=".5"/></g>',
     "Your logo, in pixels", "Students draw your logo as pixel art for the bin's screen."),
    ("#c8102e", '<path d="M4 6h16v10H11l-5 4v-4H4z" fill="none" stroke="#fff" stroke-width="2.4" stroke-linejoin="round"/><path d="M12 9.2c-1-1.6-3.6-.8-2.6 1.2.6 1.1 2.6 2.3 2.6 2.3s2-1.2 2.6-2.3c1-2-1.6-2.8-2.6-1.2z" fill="#fff"/>',
     "Cheer them on", "Send the team a note. It pops up on their bin's screen."),
    ("#2f7d3a", '<circle cx="12" cy="12" r="8" fill="none" stroke="#fff" stroke-width="2.4"/><path d="M4 12h16M12 4c3 3 3 13 0 16M12 4c-3 3-3 13 0 16" fill="none" stroke="#fff" stroke-width="1.8"/>',
     "Watch it live", "Every reading, from anywhere, at whs.makerlabkids.com."),
    ("#7a5038", '<rect x="5" y="4" width="14" height="16" rx="1.5" fill="none" stroke="#fff" stroke-width="2.4"/><path d="M8 8h8M8 11h8M8 14h5" stroke="#fff" stroke-width="2" stroke-linecap="round"/>',
     "Follow the story", "The Daily Worm writes up the day's readings as a newspaper."),
    ("#5b3fa8", '<path d="M12 4l2.4 5 5.6.6-4.2 3.8 1.2 5.6L12 16.2 7 19l1.2-5.6L4 9.6 9.6 9z" fill="#fff"/>',
     "Come see it", "Stop by, meet the team, and watch the worms at work."),
]

def perk(c, icon, t, d, cls="perk"):
    return f'<div class="{cls}"><div class="pi" style="background:{c}"><svg viewBox="0 0 24 24">{icon}</svg></div><div><h3>{t}</h3><p>{d}</p></div></div>'

GOES = ["Sensor kits, so every team has its own", "3D printer filament and parts", "Worms, bins and bedding for more classrooms", "3D printers and design software"]

LOGOS = '''<div class="logos"><span class="chip whs"><img src="../whs-mascot.png" alt="Woodstock Wolverine"><b>WOODSTOCK<br>HIGH SCHOOL</b></span>
  <span class="chip"><img class="mlk" src="../logo.png" alt="Maker Lab Kids"></span></div>'''

QR = '<img class="qr" src="qr-whs.svg" alt="QR code for whs.makerlabkids.com">'

def squiggles(n=7, w=816, h=200, seed=3):
    import random
    r = random.Random(seed); out = []
    for _ in range(n):
        x, y = r.uniform(0, w), r.uniform(10, h - 10); s = r.uniform(.6, 1.3)
        out.append(f'<path class="worm" d="M{x:.0f} {y:.0f} q{14*s:.0f} {-12*s:.0f} {28*s:.0f} 0 t{28*s:.0f} 0 t{28*s:.0f} 0" stroke="rgba(255,255,255,.10)" stroke-width="{9*s:.1f}"/>')
    return "".join(out)

# ======================================================================= one-sheet
ONE_CSS = '''
  .top { background: linear-gradient(150deg, #1b2f5e 0%, #24407e 55%, #2a9fd8 120%); color: #fff; padding: .34in .5in 0; height: 4.2in; position: relative; }
  .top .bg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .logos { display: flex; justify-content: space-between; align-items: center; position: relative; }
  .chip { background: #fff; border-radius: 14px; padding: 6px 12px; display: inline-flex; align-items: center; gap: 8px; }
  .chip img { height: .46in; display: block; } .chip img.mlk { height: .5in; }
  .chip.whs b { font-family: "Fredoka"; color: var(--navy); font-size: 13px; line-height: 1.05; letter-spacing: .05em; }
  .kick { position: relative; margin-top: .16in; font-weight: 900; letter-spacing: .2em; font-size: 13px; color: #a6e07f; }
  h1 { position: relative; margin: 2px 0 0; font-size: 84px; line-height: .9; color: var(--yellow); letter-spacing: -.01em; text-shadow: 0 4px 0 rgba(0,0,0,.18); }
  h1 span { color: #fff; }
  .lead { position: relative; font-size: 17.5px; line-height: 1.36; max-width: 4.3in; margin: 10px 0 0; color: #e7efff; }
  .lead b { color: #fff; }
  .binart { position: absolute; right: .4in; top: .95in; width: 2.85in; }
  .binart svg { width: 100%; height: auto; display: block; filter: drop-shadow(0 10px 18px rgba(0,0,0,.25)); }
  .burst { position: absolute; right: 2.7in; top: 1.3in; width: 1.32in; height: 1.32in; transform: rotate(-12deg); }
  .burst svg { width: 100%; height: 100%; }
  .ribbon { position: absolute; left: 0; right: 0; bottom: 0; height: .5in; background: #fff; clip-path: polygon(0 100%, 0 70%, 100% 0, 100% 100%); }
  .body { padding: 0 .5in; }
  .sec { font-family: "Fredoka"; font-size: 26px; color: var(--navy); margin: -4px 0 6px; }
  .sec em { font-style: normal; color: var(--orange); }
  .perks { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
  .perk { display: flex; gap: 10px; align-items: flex-start; background: #f6f8fc; border-radius: 14px; padding: 8px 10px; }
  .pi { flex: 0 0 40px; height: 40px; border-radius: 11px; display: grid; place-items: center; } .pi svg { width: 26px; height: 26px; }
  .perk h3 { margin: 0; font-size: 17px; color: var(--navy); } .perk p { margin: 2px 0 0; font-size: 12.5px; line-height: 1.35; color: #3a4352; }
  .strip { display: grid; grid-template-columns: 1.05fr 1fr 1fr; gap: 10px; margin-top: 10px; }
  .ph { border-radius: 14px; overflow: hidden; position: relative; height: 1.12in; background: #0b1220; }
  .ph img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .ph .cap { position: absolute; left: 8px; bottom: 8px; background: rgba(27,47,94,.9); color: #fff; font-weight: 800; font-size: 11.5px; border-radius: 99px; padding: 3px 10px; }
  .oleds { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 6px; background: #1d2430; height: 1.12in; border-radius: 14px; position: relative; }
  .oleds img { width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; background: #0b1220; border-radius: 5px; display: block; }
  .mid { display: grid; grid-template-columns: 1fr 1.25fr; gap: 12px; margin-top: 10px; align-items: stretch; }
  .goes { background: var(--cream); border: 2px solid #f1dcc0; border-radius: 16px; padding: 12px 14px; }
  .goes h3 { margin: 0 0 4px; color: var(--soil); font-size: 20px; }
  .goes ul { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.55; }
  .why { background: linear-gradient(140deg, #2f7d3a, #5fae3a); color: #fff; border-radius: 16px; padding: 12px 16px; }
  .why h3 { margin: 0 0 4px; font-size: 20px; color: #fff; }
  .why p { margin: 0; font-size: 13.5px; line-height: 1.45; }
  .stats { display: flex; gap: 10px; margin-top: 8px; }
  .stats div { flex: 1; background: rgba(255,255,255,.16); border-radius: 10px; padding: 5px 4px; text-align: center; font-size: 10.5px; line-height: 1.2; font-weight: 700; }
  .stats b { display: block; font-family: "Fredoka"; font-size: 22px; color: #ffe27a; }
  .foot { position: absolute; left: 0; right: 0; bottom: 0; height: 1.22in; background: var(--navy); color: #fff; display: grid;
          grid-template-columns: 1fr auto; gap: 18px; align-items: center; padding: 0 .5in; }
  .foot h2 { margin: 0; font-size: 30px; color: var(--yellow); line-height: 1; }
  .foot p { margin: 6px 0 0; font-size: 14px; line-height: 1.4; color: #dfe8fb; } .foot p b { color: #fff; }
  .qrbox { background: #fff; border-radius: 12px; padding: 7px; display: flex; gap: 10px; align-items: center; color: var(--navy); }
  .qr { width: .92in; height: .92in; display: block; }
  .qrbox span { font-size: 12px; font-weight: 800; line-height: 1.3; width: 1.4in; } .qrbox span b { display: block; font-family: "Fredoka"; font-size: 16px; color: var(--orange); }
'''

BURST = '''<svg viewBox="0 0 100 100"><polygon points="50,2 58,20 77,9 76,30 97,30 84,46 99,60 79,66 86,86 66,80 60,99 50,84 40,99 34,80 14,86 21,66 1,60 16,46 3,30 24,30 23,9 42,20" fill="#f2c400"/>
<text x="50" y="44" text-anchor="middle" font-family="Fredoka" font-weight="700" font-size="13" fill="#1b2f5e">YOUR</text>
<text x="50" y="58" text-anchor="middle" font-family="Fredoka" font-weight="700" font-size="13" fill="#1b2f5e">NAME</text>
<text x="50" y="72" text-anchor="middle" font-family="Fredoka" font-weight="700" font-size="13" fill="#c8102e">HERE!</text></svg>'''

def one_sheet():
    o = [HEAD.format(title="Sponsor a Bin", desc="Sponsor a smart worm bin at Woodstock High School: one printable letter page.", barw="8.5in", pagesize="letter portrait",
                     w="8.5in", h="11in", zoomw="860px", zoomin="8.9in", barnote="one letter page.", css=ONE_CSS)]
    o.append(f'''<section class="sheet">
  <div class="top">
    <svg class="bg" viewBox="0 0 816 475" preserveAspectRatio="none">{squiggles(9, 816, 475)}</svg>
    {LOGOS}
    <div class="kick">WORMS · WIRES · WI-FI</div>
    <h1>Sponsor<br><span>a Bin!</span></h1>
    <p class="lead">Woodstock High students turn <b>cafeteria scraps</b> into compost, and worm bins into
      <b>science stations</b>. Put your name on one!</p>
    <div class="binart">{BIN}</div>
    <div class="burst">{BURST}</div>
    <div class="ribbon"></div>
  </div>

  <div class="body">
    <h2 class="sec">What sponsors <em>get</em></h2>
    <div class="perks">{"".join(perk(*p) for p in PERKS)}</div>

    <div class="strip">
      <div class="ph"><img src="../board/img/build-screen.jpg" alt="A worm bin with a 3D-printed lid and its screen"><span class="cap">Built by students</span></div>
      <div class="ph"><img src="../board/img/skin-deck.jpg" alt="Mission control: every bin on one screen" style="object-position:left top"><span class="cap">Live on the big screen</span></div>
      <div class="oleds"><img src="../board/img/oled-school.png" alt="Wolverine on the bin screen"><img src="../board/img/oled-yourname.png" alt="Sponsored by: your name here, on the bin screen">
        <img src="../board/img/oled-scientist.png" alt="Data screen"><img src="../board/img/oled-bigworm.png" alt="Wormhole animation"></div>
    </div>

    <div class="mid">
      <div class="goes"><h3>Where your support goes</h3><ul>{"".join(f"<li>{g}</li>" for g in GOES)}</ul></div>
      <div class="why"><h3>Real STEM, real science</h3>
        <p>Students wire sensors, write code, 3D print parts and collect real data. They even run a company that sells the castings.</p>
        <div class="stats"><div><b>40+</b>smart bins</div><div><b>3</b>classrooms</div><div><b>8+</b>things measured</div><div><b>60s</b>a fresh reading</div></div>
      </div>
    </div>
  </div>

  <div class="foot">
    <div><h2>Let's grow something together.</h2>
      <p>Talk to <b>Ms. Audra Thomas</b> at <b>Woodstock High School</b>, or to any of our students. Thank you for supporting STEM in our school!</p></div>
    <div class="qrbox">{QR}<span><b>Watch live</b>whs.makerlabkids.com</span></div>
  </div>
</section>
</body>
</html>
''')
    return "".join(o)

# ======================================================================= trifold
TRI_CSS = '''
  .sheet { display: grid; grid-template-columns: repeat(3, 1fr); }
  .panel { padding: .36in .3in .3in; position: relative; overflow: hidden; display: flex; flex-direction: column; }
  h2 { font-size: 25px; color: var(--navy); margin: 0 0 6px; line-height: 1.05; } h2 em { font-style: normal; color: var(--orange); }
  .k { font-weight: 900; letter-spacing: .18em; font-size: 10.5px; color: var(--red); margin-bottom: 2px; }
  p { font-size: 12.5px; line-height: 1.45; margin: 0 0 8px; }
  .cover { color: var(--ink); }
  .cover h1 { position: relative; font-size: 64px; line-height: .9; margin: 6px 0 0; color: var(--navy); }
  .cover h1 span { color: var(--orange); }
  .cover .lead { position: relative; font-size: 15px; color: #36404f; margin-top: 10px; line-height: 1.4; }
  .cover .binart { position: relative; margin: 14px auto 0; width: 3.15in; } .cover .burst { position: absolute; left: .18in; top: 3.0in; width: 1.15in; height: 1.15in; transform: rotate(-12deg); } .cover .burst svg { width: 100%; height: 100%; }
  .cover .binart svg { width: 100%; height: auto; display: block; }
  .cover .kick { position: relative; font-weight: 900; letter-spacing: .2em; font-size: 11px; color: var(--dgreen); margin-top: 12px; }
  .chips { position: relative; display: flex; gap: 8px; margin-top: auto; }
  .chip { background: none; border-radius: 12px; padding: 5px 4px; display: inline-flex; align-items: center; gap: 6px; }
  .chip img { height: .38in; display: block; } .chip b { font-family: "Fredoka"; color: var(--navy); font-size: 10.5px; line-height: 1.05; letter-spacing: .04em; }
  .back { text-align: center; align-items: center; }
  .back .qr { width: 1.55in; height: 1.55in; display: block; margin: 8px auto; background: #fff; border-radius: 10px; padding: 6px; }
  .back .big { font-family: "Fredoka"; font-size: 20px; color: var(--navy); }
  .back .url { font-weight: 900; color: var(--orange); font-size: 15px; }
  .back .contact { background: var(--navy); color: #fff; border-radius: 14px; padding: 12px; margin-top: 14px; width: 100%; }
  .back .contact h3 { margin: 0 0 4px; color: var(--yellow); font-size: 21px; } .back .contact p { margin: 0; font-size: 13px; }
  .back .logosv { display: flex; gap: 10px; align-items: center; justify-content: center; margin-top: auto; }
  .back .logosv img { height: .55in; }
  .steps { display: flex; flex-direction: column; gap: 8px; }
  .step { border-radius: 12px; padding: 9px 11px; color: #fff; } .step h3 { margin: 0; font-size: 17px; } .step p { margin: 2px 0 0; font-size: 12px; line-height: 1.35; }
  .s1 { background: linear-gradient(135deg, #7a5038, #5b3a29); } .s2 { background: linear-gradient(135deg, #2f7d3a, #5fae3a); } .s3 { background: linear-gradient(135deg, #1b2f5e, #2a9fd8); }
  .meas { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; font-size: 11.5px; margin-top: 8px; padding: 0; list-style: none; }
  .meas li::before { content: "● "; color: var(--green); }
  .photo { border-radius: 12px; overflow: hidden; margin: 4px 0 8px; background: #ddd; } .photo img { width: 100%; display: block; object-fit: cover; }
  .q { background: var(--cream); border-left: 5px solid var(--yellow); border-radius: 0 12px 12px 0; padding: 8px 10px; font-family: "Fredoka"; font-size: 15px; color: var(--navy); line-height: 1.25; }
  .tperk { display: flex; gap: 9px; align-items: flex-start; margin-bottom: 9px; }
  .pi { flex: 0 0 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; } .pi svg { width: 22px; height: 22px; }
  .tperk h3 { margin: 0; font-size: 17px; color: var(--navy); } .tperk p { margin: 1px 0 0; font-size: 12.8px; line-height: 1.38; } .tperk { margin-bottom: 12px; }
  .goes { background: var(--cream); border: 2px solid #f1dcc0; border-radius: 14px; padding: 10px 12px; }
  .goes h3 { margin: 0 0 3px; color: var(--soil); font-size: 18px; } .goes ul { margin: 0; padding-left: 16px; font-size: 12px; line-height: 1.5; }
  .learn { display: flex; flex-wrap: wrap; gap: 5px; margin: 6px 0 10px; }
  .learn span { background: var(--navy); color: #fff; font-weight: 800; font-size: 11px; border-radius: 99px; padding: 3px 9px; }
  .learn span:nth-child(3n+2) { background: var(--orange); } .learn span:nth-child(3n) { background: var(--dgreen); }
  .oled-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; background: #1d2430; padding: 5px; border-radius: 10px; margin-top: auto; }
  .oled-row img { width: 100%; image-rendering: pixelated; display: block; border-radius: 3px; }
  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-top: 12px; }
  .tiles div { color: #fff; border-radius: 12px; padding: 8px; text-align: center; font-weight: 800; font-size: 11.5px; }
  .tiles b { display: block; font-family: "Fredoka"; font-size: 30px; line-height: 1; color: #fff; }
  .sheetlabel { position: absolute; top: 4px; left: 50%; transform: translateX(-50%); font-size: 9px; color: #9aa4b2; letter-spacing: .12em; }
  @media print { .sheetlabel { display: none; } }
'''

def trifold():
    o = [HEAD.format(title="Sponsor a Bin Brochure", desc="A trifold brochure for sponsors of the Woodstock High School smart worm bins: two letter-landscape sheets.", barw="11in",
                     pagesize="letter landscape", w="11in", h="8.5in", zoomw="1160px", zoomin="11.4in",
                     barnote="trifold: 2 landscape sheets, print double-sided, flip on the short edge, fold in thirds.", css=TRI_CSS)]
    perks = "".join(perk(*p, cls="tperk") for p in PERKS)
    o.append(f'''
<!-- OUTSIDE: inside flap | back | front cover -->
<section class="sheet">
  <div class="panel">
    <div class="k">HOW IT WORKS</div>
    <h2>A smart <em>worm bin</em></h2>
    <p>Red wigglers turn our cafeteria's food scraps into castings, the rich compost gardeners call black gold. Sensors tell us how the worms are doing, around the clock.</p>
    <div class="steps">
      <div class="step s1"><h3>1 · Feed</h3><p>Cafeteria scraps and shredded paper go in. Worms eat, wiggle and leave castings.</p></div>
      <div class="step s2"><h3>2 · Sense</h3><p>Sensors read the bin twice a second. A screen on the lid shows them.</p></div>
      <div class="step s3"><h3>3 · Share</h3><p>Every minute, Wi-Fi carries the readings to a website anyone can open.</p></div>
    </div>
    <ul class="meas"><li>Air temperature</li><li>Humidity</li><li>Air pressure</li><li>Soil temperature</li><li>Soil moisture</li><li>Bedding level</li><li>Light (coming)</li><li>Sound (coming)</li></ul>
    <div class="photo" style="margin-top:10px"><img src="../board/img/build-lid-top.jpg" alt="The 3D-printed honeycomb lid with its screen case" style="height:1.75in"></div>
    <div class="oled-row"><img src="../board/img/oled-school.png" alt="Wolverine"><img src="../board/img/oled-radar.png" alt="Worm radar"><img src="../board/img/oled-scientist.png" alt="Data"><img src="../board/img/oled-yourname.png" alt="Sponsored by: your name here"></div>
  </div>
  <div class="panel back">
    <div class="big" style="margin-top:6px">Watch the bins live</div>
    <img class="qr" src="qr-whs.svg" alt="QR code for whs.makerlabkids.com">
    <div class="url">whs.makerlabkids.com</div>
    <p style="margin-top:8px">Every bin, every reading, updated every minute. Open it on your phone right now.</p>
    <div class="contact"><h3>Let's talk!</h3><p>Ms. Audra Thomas<br>Woodstock High School<br>or ask any of our students</p></div>
    <p style="margin-top:12px;font-size:11.5px;color:var(--muted)">A vermiculture project-based learning program at Woodstock High School, with Maker Lab Kids.</p>
    <div class="logosv"><img src="../whs-mascot.png" alt="Woodstock Wolverine"><img src="../logo.png" alt="Maker Lab Kids"></div>
  </div>
  <div class="panel cover">
    <div class="kick">WORMS · WIRES · WI-FI</div>
    <h1>Sponsor<br><span>a Bin!</span></h1>
    <p class="lead">Help Woodstock High students turn cafeteria scraps into real science.</p>
    <div class="binart">{BIN}</div>
    <div class="burst">{BURST}</div>
    <p class="lead" style="margin-top:14px">Name a bin, cheer on a team, and watch the science happen live.</p>
    <div class="chips"><span class="chip"><img src="../whs-mascot.png" alt="Woodstock Wolverine"><b>WOODSTOCK<br>HIGH SCHOOL</b></span><span class="chip"><img src="../logo.png" alt="Maker Lab Kids"></span></div>
  </div>
</section>

<!-- INSIDE: three panels -->
<section class="sheet">
  <div class="panel">
    <div class="k">THE PROJECT</div>
    <h2>Scraps in, <em>science</em> out</h2>
    <div class="photo"><img src="../board/img/build-screen.jpg" alt="A student-built worm bin with a 3D-printed lid and screen" style="height:2.3in"></div>
    <p>Every bin is a clear cylinder or tote of red wigglers with a 3D-printed lid, a tiny Wi-Fi computer, a screen and a set of sensors, all built by students.</p>
    <p>The worms eat scraps from our own cafeteria. The school even started a company so students can sell the castings to the public.</p>
    <div class="q">How do we keep thousands of red wigglers happy, and prove it with data?</div>
    <div class="photo" style="margin-top:auto"><img src="../board/img/build-red-lid.jpg" alt="An earlier red lid on a clear cylinder with the sensors inside" style="height:1.7in"></div>
  </div>
  <div class="panel">
    <div class="k">FOR SPONSORS</div>
    <h2>What you <em>get</em></h2>
    {perks}
    <div class="photo" style="margin-top:auto"><img src="../board/img/skin-deck.jpg" alt="Mission control: every bin on one screen" style="height:1.75in;object-position:left top"></div>
  </div>
  <div class="panel">
    <div class="k">YOUR SUPPORT</div>
    <h2>Where it <em>goes</em></h2>
    <div class="goes"><ul>{"".join(f"<li>{g}</li>" for g in GOES)}</ul></div>
    <h2 style="margin-top:12px">What students <em>learn</em></h2>
    <div class="learn"><span>Microcontrollers</span><span>Coding</span><span>Circuits</span><span>Soldering</span><span>Sensors</span><span>Networking</span><span>Data visualization</span><span>3D CAD</span><span>3D printing</span><span>Worm biology</span><span>Running a business</span></div>
    <div class="q" style="font-size:14px">Design it, build it, break it, fix it. Every failure teaches something, and that's when the learning sticks.</div>
    <div class="tiles"><div style="background:#1b2f5e"><b>40+</b>smart bins</div><div style="background:#e8762c"><b>3</b>classrooms</div>
      <div style="background:#2f7d3a"><b>8+</b>things measured</div><div style="background:#c8102e"><b>60s</b>a fresh reading</div></div>
    <p style="margin-top:10px">Some of what we measure, nobody knows yet. Our students will share their data and findings so others can build on them.</p>
  </div>
</section>
</body>
</html>
''')
    return "".join(o)

if __name__ == "__main__":
    out = os.path.join(ROOT, "docs/sponsor")
    open(os.path.join(out, "index.html"), "w").write(one_sheet())
    open(os.path.join(out, "brochure.html"), "w").write(trifold())
    print("wrote docs/sponsor/index.html and brochure.html")
