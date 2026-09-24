#!/usr/bin/env bash
# Rebuilds fax-triage-promo.mp4 from index.html (the animation) and audio.py (the soundtrack).
# Needs: node + playwright, python3 with pymupdf, numpy, imageio-ffmpeg.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p img
python3 -c "
import glob, pymupdf
for p in sorted(glob.glob('../faxes_in/*.PDF')):
    pymupdf.open(p)[0].get_pixmap(dpi=130).save('img/' + p.split('/')[-1][:-4] + '.png')
"
rm -rf frames && node render.js full
python3 audio.py
FF=$(python3 -c "import imageio_ffmpeg as i; print(i.get_ffmpeg_exe())")
"$FF" -y -loglevel error -framerate 30 -i frames/f%05d.jpg -i audio.wav -c:v libx264 -preset slow -crf 23 -tune grain \
  -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart -shortest fax-triage-promo.mp4
rm -rf frames audio.wav
echo "wrote promo/fax-triage-promo.mp4"
