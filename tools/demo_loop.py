"""Fast graphics demo for a board: both logos, the ten worm shows and any
kids' shows in shows/, back to back with no pause between them, forever.

Put it on a board as main.py (keep the real main.py to swap back):
    mpremote cp :main.py :main_wormbin.py
    mpremote cp lib/wormshow.py :lib/wormshow.py
    mpremote cp lib/logos.py :lib/logos.py
    mpremote cp lib/pbmshow.py :lib/pbmshow.py
    mpremote cp tools/demo_loop.py :main.py
    mpremote reset
Back to normal: mpremote cp :main_wormbin.py :main.py + mpremote reset.
FPS = 20 is the pace the shows were drawn for; raise it for a faster run
(the OLED refresh tops out near 40).
"""
import picolab
import wormshow

FPS = 20


def demo_list():
  shows = wormshow.LOGOS + wormshow.SHOWS
  try:
    import pbmshow
    shows = shows + pbmshow.playlist((), list_file="/no-shows.txt", show_dir=pbmshow.SHOW_DIR)   # every file in shows/, A to Z
  except ImportError:
    pass
  return shows


def main():
  shows = demo_list()
  display = picolab.Display()
  picolab.banner("DEMO LOOP", ["%d in a row: %s" % (len(shows), ", ".join(s.name for s in shows))])
  wormshow.play(display, loop=True, fps=FPS, hold_ms=0, shows=shows)


if __name__ == "__main__":
  main()
