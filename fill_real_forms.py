#!/usr/bin/env python3
"""fill_real_forms.py -- hand-fill the 5 blank real hospital forms in real_forms/ with
fake TESTPATIENT data and drop image-only PDFs into faxes_in/, so they look like real
handwritten faxes an image library would receive.

Renders page 1 of each blank PDF with pypdfium2, draws values with Pillow using a
handwriting TTF (coordinates hardcoded per form, found by eyeballing a gridded render),
adds a typed fax header, slight rotation, and speckle noise, then saves as a PDF.
"""
import random
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).parent
REAL_FORMS = ROOT / "real_forms"
FAXES_IN = ROOT / "faxes_in"

SCALE = 2.3  # ~200dpi on a 612x792pt (letter) page -> ~1408x1822px

FONTS = {
    "segoesc": r"C:\Windows\Fonts\segoesc.ttf",
    "inkfree": r"C:\Windows\Fonts\Inkfree.ttf",
    "segoepr": r"C:\Windows\Fonts\segoepr.ttf",
    "segoeprb": r"C:\Windows\Fonts\segoeprb.ttf",
}

_font_cache = {}


def font(name, size):
    key = (name, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONTS[name], size)
    return _font_cache[key]


def jitter(base, spread):
    return base + random.uniform(-spread, spread)


def write(draw, xy, text, font_name, size, fill=40, size_jitter=2, baseline_jitter=4):
    """Draw one handwritten line, top-left anchored at xy, with slight jitter per call."""
    x, y = xy
    s = max(8, size + random.randint(-size_jitter, size_jitter))
    f = font(font_name, s)
    y = jitter(y, baseline_jitter)
    x = jitter(x, baseline_jitter * 0.6)
    draw.text((x, y), text, font=f, fill=fill)


def hand_x(draw, cx, cy, r=9, fill=40, width=3):
    """A hand-drawn X mark (two jittered lines) centered at (cx, cy), for a checkbox."""
    for sign in (1, -1):
        x0 = jitter(cx - r * sign, 2)
        y0 = jitter(cy - r, 2)
        x1 = jitter(cx + r * sign, 2)
        y1 = jitter(cy + r, 2)
        draw.line([(x0, y0), (x1, y1)], fill=fill, width=width)


def hand_circle(draw, cx, cy, rx, ry, fill=40, width=3):
    """A rough hand-drawn oval around a word, as a few jittered arcs (not a perfect ellipse)."""
    pts = []
    import math
    n = 22
    for i in range(n + 1):
        ang = 2 * math.pi * i / n
        px = cx + rx * math.cos(ang) + random.uniform(-2, 2)
        py = cy + ry * math.sin(ang) + random.uniform(-2, 2)
        pts.append((px, py))
    draw.line(pts, fill=fill, width=width, joint="curve")


def fax_header(draw, w, fax_no, facility, dt):
    """Typed fax header line at the very top of the page."""
    text = f"FROM: {fax_no} {facility}   {dt}   P.1/1"
    f = font("segoepr", 20) if False else ImageFont.load_default()
    # Use a plain sans-ish look via a small handwriting font at modest size reads
    # too "handwritten" for a typed header; fall back to the bold print font small.
    f = font("segoeprb", 22)
    draw.text((14, 8), text, font=f, fill=20)


def finish_and_save(img, out_path, rotation=None):
    """Grayscale, small rotation, light speckle noise, save as a 200dpi PDF."""
    if rotation is None:
        rotation = random.uniform(0.3, 0.8) * random.choice([-1, 1])
    img = img.convert("L")
    img = img.rotate(rotation, expand=False, fillcolor=255, resample=Image.BICUBIC)

    # Light speckle noise.
    noise = Image.effect_noise(img.size, 14).point(lambda p: 255 if p > 235 else 255)
    px = img.load()
    w, h = img.size
    n_specks = int(w * h * 0.0015)
    for _ in range(n_specks):
        x = random.randrange(w)
        y = random.randrange(h)
        px[x, y] = max(0, min(255, px[x, y] + random.randint(-60, 60)))

    img = img.filter(ImageFilter.GaussianBlur(0.3))
    img.save(out_path, "PDF", resolution=200)


def render_form(name):
    pdf = pdfium.PdfDocument(str(REAL_FORMS / f"{name}.pdf"))
    bitmap = pdf[0].render(scale=SCALE)
    return bitmap.to_pil().convert("RGB")


# ---------------------------------------------------------------------------
# 1. Cleveland Clinic release form
# ---------------------------------------------------------------------------

def fill_ccf():
    img = render_form("ccf_release")
    d = ImageDraw.Draw(img)
    hf = "segoesc"

    write(d, (270, 208), "TESTPATIENT, OLIVIA", hf, 30)
    # Date of Birth __/__/__ segments
    write(d, (210, 262), "10", hf, 22)
    write(d, (270, 262), "02", hf, 22)
    write(d, (323, 258), "1977", hf, 18)
    write(d, (265, 375), "Brookfield Spine & Pain", hf, 27)
    write(d, (175, 424), "555-0341", hf, 24)
    write(d, (360, 484), "Referring provider", hf, 26)

    # Right column: Date of Exam __/__/__  Type of Exam ____  (two rows used)
    for row_y in (232, 299):
        write(d, (860, row_y), "06", hf, 24)
        write(d, (895, row_y), "14", hf, 24)
        write(d, (925, row_y), "2026", hf, 24)
    write(d, (1152, 218), "MRI Cerv Spine", hf, 24)
    write(d, (1152, 285), "XR Cerv Spine", hf, 24)

    # Mode of delivery: hand X next to "Electronic"
    hand_x(d, 862, 577, r=10)

    # Release to
    write(d, (415, 676), "Brookfield Spine & Pain", hf, 24)
    write(d, (165, 726), "90 Mill Road", hf, 24)
    write(d, (310, 776), "Fairhaven, OH 55555", hf, 24)
    write(d, (165, 826), "brookfield.spine@example.com", hf, 22)

    # Signature + date
    write(d, (375, 978), "O. Testpatient", hf, 26)

    fax_header(d, img.width, "555-0341", "BROOKFIELD SPINE & PAIN", "09/16/2026 08:14")
    finish_and_save(img, FAXES_IN / "01A183a9.PDF")


# ---------------------------------------------------------------------------
# 2. Stanford upload/overread request
# ---------------------------------------------------------------------------

def fill_stanford():
    img = render_form("stanford_upload")
    d = ImageDraw.Draw(img)
    hf = "inkfree"

    write(d, (225, 138), "TESTPATIENT, KEVIN", hf, 26, size_jitter=3)
    write(d, (225, 175), "DOB: 01/19/1983", hf, 20)

    # Priority: check ROUTINE
    hand_x(d, 1073, 339, r=9)

    write(d, (405, 512), "M. ALVAREZ MD", hf, 26)
    write(d, (665, 512), "M Alvarez", hf, 26)

    # Outside image upload table, row 1
    write(d, (200, 775), "CT", hf, 26)
    write(d, (528, 775), "Right Shoulder", hf, 26)
    write(d, (948, 775), "Pacific Crest Orthopedics", hf, 24)

    write(d, (70, 1303), "R shoulder pain, s/p injury. Exam 07/21/2026. Please fax confirmation.", hf, 19)

    write(d, (270, 1488), "Pacific Crest Orthopedics", hf, 22)
    write(d, (705, 1488), "555-0176", hf, 22)
    write(d, (205, 1578), "M Alvarez", hf, 26)

    fax_header(d, img.width, "555-0177", "PACIFIC CREST ORTHOPEDICS", "09/16/2026 10:47")
    finish_and_save(img, FAXES_IN / "01A183bd.PDF")


# ---------------------------------------------------------------------------
# 3. Dartmouth Health imaging request
# ---------------------------------------------------------------------------

def fill_dartmouth():
    img = render_form("dartmouth_request")
    d = ImageDraw.Draw(img)
    hf = "segoepr"

    write(d, (195, 265), "TESTPATIENT, MARIA", hf, 27)
    write(d, (980, 262), "05", hf, 20)
    write(d, (1045, 262), "05", hf, 20)
    write(d, (1108, 258), "1949", hf, 18)

    # Notes lines -- used for the mail-CD instructions and reports request,
    # since this form has no dedicated delivery section.
    write(d, (750, 350), "Please mail CD to Northfield Women's Health,", hf, 19)
    write(d, (750, 393), "12 Elm St, Northfield, VT 55555 - 2 copies please", hf, 19)
    write(d, (750, 435), "Please include the radiology reports", hf, 19)

    write(d, (370, 620), "Bilateral Breast / Left Breast", hf, 22)
    write(d, (215, 665), "Bilateral (mammo); Left (US)", hf, 22)
    write(d, (215, 750), "Screening + diagnostic breast imaging,", hf, 20)
    write(d, (215, 798), "routine screening / follow-up", hf, 20)
    write(d, (290, 850), "Screening Mammo 03/03/26; US Breast L 03/10/26", hf, 18)

    # Modality: Ultrasound + Other:"Mammo"
    hand_x(d, 1155, 920, r=8)
    hand_x(d, 1155, 957, r=8)
    write(d, (1225, 972), "Mammo", hf, 18)

    write(d, (355, 1085), "Northfield Women's Health", hf, 22)
    write(d, (355, 1122), "555-0522", hf, 22)
    write(d, (385, 1165), "S. Okafor MD", hf, 22)
    write(d, (410, 1207), "S Okafor", hf, 24)

    fax_header(d, img.width, "555-0523", "NORTHFIELD WOMEN'S HEALTH", "09/16/2026 09:02")
    finish_and_save(img, FAXES_IN / "01A183d1.PDF")


# ---------------------------------------------------------------------------
# 4. HSS release of information (radiology only)
# ---------------------------------------------------------------------------

def fill_hss():
    img = render_form("hss_disc_request")
    d = ImageDraw.Draw(img)
    hf = "segoeprb"

    write(d, (275, 422), "TESTPATIENT, DANIEL", hf, 26)
    write(d, (1025, 422), "08/30/1965", hf, 24)

    write(d, (145, 728), "Hospital for Special Surgery", hf, 24)
    write(d, (145, 893), "555-0688", hf, 22)
    write(d, (750, 893), "555-0689", hf, 22)

    # Circle "Radiology Report(s)" and the CD/images phrase -- want both reports+images
    hand_circle(d, 515, 1068, 120, 16)
    hand_circle(d, 857, 1068, 200, 16)

    # Circle X-Ray and MRI exam types
    hand_circle(d, 320, 1125, 42, 18)
    hand_circle(d, 647, 1125, 32, 18)

    write(d, (240, 1144), "04/18/2026", hf, 22)

    # Purpose: Medical Care
    hand_x(d, 520, 1275, r=9)

    # Neither printed pickup/mail option fits -- override with electronic instructions.
    write(d, (120, 1512), "Send electronically - PowerShare: HSS Radiology", hf, 20)

    fax_header(d, img.width, "555-0689", "HOSPITAL FOR SPECIAL SURGERY", "09/16/2026 13:29")
    finish_and_save(img, FAXES_IN / "01A183e5.PDF")


# ---------------------------------------------------------------------------
# 5. Washington Radiology patient release request
# ---------------------------------------------------------------------------

def fill_washington():
    img = render_form("washington_radiology_release")
    d = ImageDraw.Draw(img)
    hf = "inkfree"
    faint = 110

    # STAT note, prominent, in the blank top margin.
    write(d, (850, 55), "*** STAT - surgery 09/20/2026 ***", hf, 27, fill=60, size_jitter=2)

    write(d, (210, 665), "TESTPATIENT, AMARA", hf, 26, fill=faint)
    write(d, (305, 707), "11/11/1991", hf, 25, fill=faint)

    write(d, (515, 1000), "All imaging 01/01/2024-present. Mail 1 CD to:", hf, 19, fill=faint)
    write(d, (90, 1040), "44 Birch Ln, Fairhaven, OH 55555 (not the address below)", hf, 19, fill=faint)

    write(d, (255, 1302), "Amara T.", hf, 26, fill=faint)
    write(d, (1080, 1302), "09/15/2026", hf, 20, fill=faint)
    write(d, (430, 1371), "555-0904", hf, 22, fill=faint)

    fax_header(d, img.width, "555-0904", "TESTPATIENT, AMARA (SELF)", "09/16/2026 07:58")
    finish_and_save(img, FAXES_IN / "01A183f9.PDF")


def main():
    random.seed(20260916)
    FAXES_IN.mkdir(exist_ok=True)
    fill_ccf()
    fill_stanford()
    fill_dartmouth()
    fill_hss()
    fill_washington()
    print("wrote 5 filled faxes to", FAXES_IN)


if __name__ == "__main__":
    main()
