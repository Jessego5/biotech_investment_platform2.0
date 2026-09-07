"""
Stitches the frames capture.mjs wrote into an animated GIF.

    python3 docs/make_gif.py FRAMES OUT [--thin N:K]

--thin keeps only every Kth of the first N frames. The Ask recording spends
forty frames on somebody typing, which are nearly identical, and without it the
result is four fifths typing and one fifth the thing worth seeing. The scrolling
recording needs no thinning, since every frame is a different part of the page.

The last frame is held for a moment either way, so a reader landing mid-loop
lands on something rather than on a blank input.
"""

import glob
import sys

from PIL import Image

frames_dir, out = sys.argv[1], sys.argv[2]
thin = next((a for a in sys.argv[3:] if a.startswith("--thin")), None)

paths = sorted(glob.glob(f"{frames_dir}/*.png"))
if thin:
    n, k = (int(x) for x in sys.argv[sys.argv.index(thin) + 1].split(":"))
    paths = paths[:n][::k] + paths[n:]

frames = []
for path in paths:
    im = Image.open(path).convert("RGB")
    im = im.resize((1000, int(im.height * 1000 / im.width)), Image.LANCZOS)
    frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))
frames += [frames[-1]] * 8

frames[0].save(out, save_all=True, append_images=frames[1:],
               duration=180, loop=0, optimize=True, disposal=2)
print(f"{out}: {len(frames)} frames")
