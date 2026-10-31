"""Splash-screen demo mode for a board: every worm show, forever.

Put it on a board as main.py (keep the real main.py as main_wormbin.py
to swap back):
    mpremote cp lib/wormshow.py :lib/wormshow.py
    mpremote cp :main.py :main_wormbin.py     # (or mpremote cp from a local copy)
    mpremote cp tools/splash_demo.py :main.py
    mpremote reset
"""
import picolab
import wormshow

display = picolab.Display()
picolab.banner("WORM SHOW", ["%d shows, looping: %s" % (len(wormshow.SHOWS), ", ".join(c.name for c in wormshow.SHOWS))])
wormshow.play(display, loop=True)
