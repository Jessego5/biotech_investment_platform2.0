"""
Stitches the frames capture.mjs wrote into docs/demo.gif.

The typing frames are nearly identical, so only every third is kept, or the
recording is four fifths somebody typing and one fifth the thing worth seeing.
The last frame is held for a moment at the end, so a reader who lands mid-loop
lands on the passage panel rather than on a blank input.

    python3 docs/make_gif.py /tmp/frames docs/demo.gif
"""

import glob
import sys

from PIL import Image

frames_dir, out = sys.argv[1], sys.argv[2]
paths = sorted(glob.glob(f"{frames_dir}/*.png"))
typing, rest = paths[:42], paths[42:]

frames = []
for path in typing[::3] + rest:
    im = Image.open(path).convert("RGB")
    im = im.resize((1000, int(im.height * 1000 / im.width)), Image.LANCZOS)
    frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))
frames += [frames[-1]] * 8

frames[0].save(out, save_all=True, append_images=frames[1:],
               duration=180, loop=0, optimize=True, disposal=2)
print(f"{out}: {len(frames)} frames")
