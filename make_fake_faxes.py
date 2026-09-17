"""
Generate 8 synthetic "records request" fax PDFs for triage-tool testing.

ALL data here is fake: facility names, patients, MRNs, phone/fax numbers (555
exchange). Nothing in this file represents a real hospital, clinic, law firm,
or person.

Each page is rendered as a raster image with Pillow (no text layer, like a
real fax) and saved as an image-only PDF. Pillow and pypdfium2 are the only
third-party packages available -- no numpy, no pip installs.

Most real faxes are printed forms filled out by hand, so most of the faxes
below render a printed form (typed labels/underlines/checkboxes) with the
answers written in a handwriting font -- see render_field_rows() and friends.
"""

import os
import random
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

random.seed(7)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "faxes_in")
PAGE_W, PAGE_H = 1700, 2200  # 8.5x11in @ 200dpi
DPI = 200

FONT_CACHE = {}

HAND_FONT_PATHS = {
    "script": r"C:\Windows\Fonts\segoesc.ttf",
    "script_bold": r"C:\Windows\Fonts\segoescb.ttf",
    "ink": r"C:\Windows\Fonts\Inkfree.ttf",
    "print": r"C:\Windows\Fonts\segoepr.ttf",
    "print_bold": r"C:\Windows\Fonts\segoeprb.ttf",
}


def font(size):
    if size not in FONT_CACHE:
        FONT_CACHE[size] = ImageFont.load_default(size=size)
    return FONT_CACHE[size]


def hfont(hand, size):
    """Cached loader for one of the handwriting fonts, at a given size."""
    key = (hand, size)
    if key not in FONT_CACHE:
        FONT_CACHE[key] = ImageFont.truetype(HAND_FONT_PATHS[hand], size)
    return FONT_CACHE[key]


def new_page():
    return Image.new("L", (PAGE_W, PAGE_H), color=255)


def draw_fax_header(draw, from_hdr, date_str, time_str, page_str):
    """Top-of-page banner that real fax machines stamp onto every page."""
    hdr = f"FROM: {from_hdr}" + " " * 6 + f"{date_str} {time_str}" + " " * 6 + page_str
    draw.line([(40, 70), (PAGE_W - 40, 70)], fill=0, width=2)
    draw.text((40, 30), hdr, font=font(26), fill=0)
    draw.line([(40, 100), (PAGE_W - 40, 100)], fill=0, width=2)


def draw_wrapped(draw, xy, text, size=28, width_chars=95, line_gap=10, jitter=0):
    x, y = xy
    f = font(size)
    for para in text.split("\n"):
        if not para.strip():
            y += size + line_gap
            continue
        for line in textwrap.wrap(para, width=width_chars) or [""]:
            dx = random.randint(-jitter, jitter) if jitter else 0
            dy = random.randint(-jitter, jitter) if jitter else 0
            draw.text((x + dx, y + dy), line, font=f, fill=0)
            y += size + line_gap
    return y


# ---------------------------------------------------------------------------
# Handwritten-form building blocks: printed labels/underlines/checkboxes with
# answers written in a handwriting font -- baseline jitter, slight size
# variation, imperfect alignment to the line, occasional overrun (nothing
# here clips the drawn text, so a long/large value naturally runs past its
# underline, like real handwriting does).
# ---------------------------------------------------------------------------

def hand_value(draw, xy, text, hand, size, fill=0, jitter=4, size_jitter=3):
    """One handwritten value, word by word, with per-word baseline jitter."""
    x, y = xy
    for word in str(text).split(" "):
        s = max(size + random.randint(-size_jitter, size_jitter), 12)
        f = hfont(hand, s)
        dx = random.randint(-2, 3)
        dy = random.randint(-jitter, jitter)
        draw.text((x + dx, y + dy), word, font=f, fill=fill)
        x += draw.textlength(word + " ", font=f)
    return x


def hand_paragraph(draw, xy, text, hand, size=34, max_width=None, line_gap=16,
                    jitter=4, size_jitter=3, fill=0):
    """Free-text prose written entirely in a handwriting font, line-wrapped by
    actual pixel width (not character count -- bold/large hands are much
    wider per character than a char-count wrap accounts for, which used to
    run text off the right edge of the page)."""
    x0, y = xy
    if max_width is None:
        max_width = PAGE_W - 40 - x0
    measure_font = hfont(hand, size)

    def flush_line(words):
        nonlocal y
        x = x0
        for w in words:
            s = max(size + random.randint(-size_jitter, size_jitter), 12)
            f = hfont(hand, s)
            dy = random.randint(-jitter, jitter)
            draw.text((x, y + dy), w, font=f, fill=fill)
            x += draw.textlength(w + " ", font=f)
        y += size + line_gap

    for para in text.split("\n"):
        if not para.strip():
            y += size + line_gap
            continue
        line, line_width = [], 0
        for word in para.split(" "):
            wlen = draw.textlength(word + " ", font=measure_font)
            if line and line_width + wlen > max_width:
                flush_line(line)
                line, line_width = [], 0
            line.append(word)
            line_width += wlen
        if line:
            flush_line(line)
    return y


def draw_field(draw, xy, label, value, hand, hand_size=32, label_size=26,
               line_len=520, fill=0, row_gap=66):
    """Printed 'Label:' + underline, answer hand-written a little above the
    line and not perfectly aligned to it -- like a filled-out form."""
    x, y = xy
    line_len = int(line_len)
    lbl = f"{label} "
    draw.text((x, y), lbl, font=font(label_size), fill=0)
    lx = x + draw.textlength(lbl, font=font(label_size))
    line_y = y + label_size + 8
    draw.line([(lx, line_y), (lx + line_len, line_y)], fill=0, width=2)
    if value not in (None, ""):
        vx = lx + random.randint(4, 18)
        vy = y - random.randint(2, 8)
        hand_value(draw, (vx, vy), value, hand, hand_size, fill=fill)
    return y + row_gap


def draw_checkbox(draw, xy, label, checked, label_size=24):
    """Printed checkbox + label; a checked box gets a hand-drawn X made of
    two short jittered strokes (not a font glyph)."""
    x, y = xy
    box = 26
    draw.rectangle([x, y, x + box, y + box], outline=0, width=2)
    if checked:
        def j(v):
            return v + random.randint(-2, 2)
        draw.line([(j(x + 4), j(y + 4)), (j(x + box - 4), j(y + box - 4))], fill=0, width=3)
        draw.line([(j(x + box - 4), j(y + 4)), (j(x + 4), j(y + box - 4))], fill=0, width=3)
    draw.text((x + box + 10, y + 1), label, font=font(label_size), fill=0)
    return x + box + 10 + draw.textlength(label, font=font(label_size)) + 40


def draw_letterhead(draw, y, name, address=None, contact=None, name_size=34):
    """Printed facility letterhead block, ending with a rule line."""
    draw.text((40, y), name, font=font(name_size), fill=0)
    y += name_size + 14
    if address:
        draw.text((40, y), address, font=font(22), fill=0)
        y += 30
    if contact:
        draw.text((40, y), contact, font=font(22), fill=0)
        y += 32
    y += 8
    draw.line([(40, y), (PAGE_W - 40, y)], fill=0, width=2)
    return y + 26


def render_field_rows(draw, y, rows, hand, x0=40, x1=880, label_size=26,
                       hand_size=32, row_gap=66, line_len=520, fill=0):
    """Data-driven form-field layout, shared by every handwritten-form fax.

    rows is a list of tuples:
      ("field", label, value[, line_len])   -- one full-width blank
      ("pair", (label1, value1), (label2, value2))  -- two-column row
      ("checks", [(label, checked), ...])   -- printed checkboxes in a row
      ("text", label, paragraph)            -- label + hand-written prose
      ("note", printed_text)                -- typed (not handwritten) note
    """
    for row in rows:
        kind = row[0]
        if kind == "field":
            label, value = row[1], row[2]
            ll = row[3] if len(row) > 3 else line_len
            y = draw_field(draw, (x0, y), label, value, hand, hand_size=hand_size,
                            label_size=label_size, line_len=ll, row_gap=row_gap, fill=fill)
        elif kind == "pair":
            (l1, v1), (l2, v2) = row[1], row[2]
            half = line_len * 0.55
            y2 = draw_field(draw, (x0, y), l1, v1, hand, hand_size=hand_size,
                             label_size=label_size, line_len=half, row_gap=row_gap, fill=fill)
            draw_field(draw, (x1, y), l2, v2, hand, hand_size=hand_size,
                       label_size=label_size, line_len=half, row_gap=row_gap, fill=fill)
            y = y2
        elif kind == "checks":
            x = x0
            for label, checked in row[1]:
                x = draw_checkbox(draw, (x, y), label, checked, label_size=max(label_size - 2, 18))
            y += row_gap
        elif kind == "text":
            label, para = row[1], row[2]
            draw.text((x0, y), label, font=font(label_size), fill=0)
            y += label_size + 14
            y = hand_paragraph(draw, (x0 + 10, y), para, hand,
                                size=max(hand_size - 6, 20), line_gap=14, fill=fill)
            y += 16
        elif kind == "note":
            y = draw_wrapped(draw, (x0, y), row[1], size=22, width_chars=105, line_gap=8)
            y += 14
    return y


def render_authorization(draw, y, hand, patient_name, release_to, signature, date_str,
                          images=True, reports=False):
    """Generic 'Authorization for Release of Imaging' checkbox form."""
    draw.text((40, y), "AUTHORIZATION FOR RELEASE OF MEDICAL IMAGING", font=font(28), fill=0)
    y += 60
    y = draw_field(draw, (40, y), "Patient Name:", patient_name, hand, hand_size=32, row_gap=60)
    y = draw_wrapped(draw, (40, y), "authorizes release of the records described above to:",
                      size=22, width_chars=100)
    y += 10
    y = draw_field(draw, (40, y), "Release To:", release_to, hand, hand_size=32,
                    row_gap=60, line_len=700)
    x = draw_checkbox(draw, (40, y), "Images", images, label_size=24)
    draw_checkbox(draw, (x, y), "Reports", reports, label_size=24)
    y += 60
    y = draw_field(draw, (40, y), "Signature:", signature, hand, hand_size=38,
                    row_gap=70, line_len=600)
    y = draw_field(draw, (40, y), "Date:", date_str, hand, hand_size=30,
                    row_gap=60, line_len=260)
    return y


def render_request_box(draw, y, hand, body_text, hand_size=46, box_bottom=2080):
    """Nearly-blank form: a bordered 'Request' box filled with free-text
    prose in a handwriting font."""
    draw.text((40, y), "Request:", font=font(24), fill=0)
    y += 36
    box_top = y
    draw.rectangle([40, box_top, PAGE_W - 40, box_bottom], outline=0, width=2)
    hand_paragraph(draw, (60, box_top + 24), body_text, hand, size=hand_size,
                    max_width=PAGE_W - 60 - 80, line_gap=28, jitter=4, size_jitter=3)
    return box_bottom + 20


def add_speckle(img, count=3500):
    """Sparse dark/light speckle noise, cheap (no numpy needed)."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for _ in range(count):
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        shade = random.choice([0, 0, 60, 200, 255, 255])
        draw.point((x, y), fill=shade)
    return img


def finalize_page(img, rotate_deg=None, low_contrast=False, speckle=True):
    if speckle:
        add_speckle(img)
    if low_contrast:
        img = ImageEnhance.Contrast(img).enhance(0.55)
        img = ImageEnhance.Brightness(img).enhance(1.08)
    if rotate_deg is None:
        rotate_deg = random.uniform(0.3, 1.0) * random.choice([-1, 1])
    img = img.rotate(rotate_deg, resample=Image.BICUBIC, fillcolor=255, expand=False)
    return img.convert("RGB")


def save_pdf(pages, filename):
    path = os.path.join(OUT_DIR, filename)
    pages[0].save(path, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    return path


# ---------------------------------------------------------------------------
# Fax 1: routine, single exam, PowerShare electronic delivery, signed auth pg2
# Handwritten-on-form: two-column form with letterhead. Hand: script.
# ---------------------------------------------------------------------------

def fax_1():
    hand = "script"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0142 LAKESHORE ORTHOPEDIC ASSOC", "09/16/2026", "16:50", "P.1/2")
    y = draw_letterhead(d, 140, "LAKESHORE ORTHOPEDIC ASSOCIATES",
                         "412 Birchwood Ave, Suite 200, Millbrook, IL 60000",
                         "Phone: 555-0142   Fax: 555-0143")
    d.text((40, y), "MEDICAL IMAGING RECORDS REQUEST", font=font(30), fill=0); y += 50
    rows = [
        ("field", "Requesting Provider:", "Dr. Harold Feeney, MD", 700),
        ("pair", ("Patient Name:", "TESTPATIENT, JANE"), ("DOB:", "04/12/1968")),
        ("pair", ("MRN:", "998231"), ("Exam Date:", "08/22/2026")),
        ("field", "Exam(s) Requested:", "CT Abdomen/Pelvis with contrast", 700),
        ("checks", [("Fax back", False), ("Mail CD", False), ("Electronic - PowerShare", True)]),
        ("field", "Send to / Address / Email:", "Lakeshore Ortho PACS", 600),
        ("checks", [("STAT", False), ("URGENT", False), ("Routine", True)]),
        ("text", "Reason for Request:", "Pre-operative surgical planning, follow-up ortho consult."),
        ("note", "Please include prior comparison studies if available. Signed patient\n"
                 "authorization attached on page 2. Thank you."),
    ]
    render_field_rows(d, y, rows, hand)
    p1 = finalize_page(img)

    img2 = new_page()
    d2 = ImageDraw.Draw(img2)
    draw_fax_header(d2, "555-0142 LAKESHORE ORTHOPEDIC ASSOC", "09/16/2026", "16:51", "P.2/2")
    render_authorization(d2, 140, hand, "JANE TESTPATIENT", "Lakeshore Orthopedic Associates",
                          "/s/ Jane Testpatient", "09/10/2026", images=True, reports=False)
    p2 = finalize_page(img2)
    return [p1, p2], "Fax 1: routine CT Abd/Pelvis request, PowerShare delivery, page 2 is signed patient authorization."


# ---------------------------------------------------------------------------
# Fax 2: STAT, MRI Brain, patient in surgery tomorrow, fax back push
# Handwritten-on-form: single-column, messy/large (rushed). Hand: print_bold.
# ---------------------------------------------------------------------------

def fax_2():
    hand = "print_bold"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0288 RIVERBEND SURGICAL CENTER", "09/16/2026", "08:14", "P.1/1")
    y = 140
    d.text((40, y), "*** STAT REQUEST ***", font=font(38), fill=0); y += 56
    d.text((40, y), "RIVERBEND SURGICAL CENTER - NEUROSURGERY", font=font(28), fill=0); y += 44
    d.text((40, y), "9900 Riverbend Pkwy, Grantsville, OH 55555   Fax back: 555-0299", font=font(20), fill=0); y += 46
    rows = [
        ("field", "Requesting Provider:", "Dr. Priya Anand, MD - Neurosurgery", 750),
        ("field", "Patient Name:", "TESTPATIENT, MARCUS"),
        ("field", "DOB:", "11/03/1975", 300),
        ("field", "MRN:", "44219A", 300),
        ("field", "Exam(s) Requested:", "MRI Brain w/ and w/o contrast", 650),
        ("field", "Exam Date:", "09/15/2026", 300),
        ("checks", [("STAT", True), ("Routine", False)]),
        ("text", "Delivery / Notes:",
         "PUSH IMAGES ELECTRONICALLY ASAP - do not mail. Surgery TOMORROW morning "
         "(09/17/2026), neurosurgery needs prior imaging before the case starts. "
         "Call fax-back line 555-0299 to confirm images have been sent."),
    ]
    render_field_rows(d, y, rows, hand, hand_size=46, row_gap=88, label_size=27)
    p1 = finalize_page(img)
    return [p1], "Fax 2: STAT MRI Brain, surgery tomorrow, fax-back number given, wants images pushed electronically."


# ---------------------------------------------------------------------------
# Fax 3: all imaging in date range, mail CD to address
# Handwritten-on-form: single-column with delivery checkboxes. Hand: ink.
# ---------------------------------------------------------------------------

def fax_3():
    hand = "ink"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0356 CEDAR VALLEY FAMILY MEDICINE", "09/15/2026", "13:02", "P.1/1")
    y = 140
    d.text((40, y), "Cedar Valley Family Medicine", font=font(32), fill=0); y += 48
    d.text((40, y), "Release of Information Request - Diagnostic Imaging", font=font(24), fill=0); y += 46
    rows = [
        ("field", "Requesting Provider:", "Dr. Susan Ilyanova, DO", 650),
        ("pair", ("Patient Name:", "TESTPATIENT, ROBERT"), ("DOB:", "02/27/1959")),
        ("field", "MRN:", "310075", 300),
        ("field", "Exam(s) Requested:", "ALL imaging studies on file, any modality", 700),
        ("field", "Date Range:", "01/01/2025 through 08/31/2026", 600),
        ("checks", [("Fax", False), ("Electronic", False), ("Mail CD", True)]),
        ("text", "Send to / Address:",
         "Cedar Valley Family Medicine, Attn: Medical Records, 77 Hollow Creek Road, "
         "Fairhaven, PA 55555"),
        ("checks", [("Routine", True), ("STAT", False)]),
        ("text", "Reason for Request:",
         "Establishing care with new PCP, need full imaging history for chart."),
    ]
    render_field_rows(d, y, rows, hand)
    p1 = finalize_page(img)
    return [p1], "Fax 3: request for all imaging 01/2025-08/2026, CD mailed to a mailing address."


# ---------------------------------------------------------------------------
# Fax 4: missing DOB, no exam dates, vague request -> missing-info flag
# Handwritten-on-form: single-column, faint (pen ran light). Hand: print.
# ---------------------------------------------------------------------------

def fax_4():
    hand = "print"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0417 QUICKCARE URGENT CARE #6", "09/14/2026", "19:45", "P.1/1")
    y = 140
    d.text((40, y), "QuickCare Urgent Care - Clinic #6", font=font(30), fill=0); y += 44
    d.text((40, y), "Records Request", font=font(24), fill=0); y += 44
    rows = [
        ("field", "Requesting Provider:", "Dr. T. Osei", 500),
        ("field", "Patient Name:", "TESTPATIENT, WILLIAM"),
        ("field", "DOB:", "(not provided)", 400),
        ("field", "Exam(s) Requested:", "any recent chest x-rays", 600),
        ("field", "Exam Date:", "unknown, just whatever you have recent", 700),
        ("field", "Delivery Method:", "fax back to 555-0418", 500),
        ("checks", [("Routine", True), ("STAT", False)]),
        ("text", "Reason for Request:", "patient says he had one done, need for chart"),
    ]
    render_field_rows(d, y, rows, hand, hand_size=30, row_gap=60, fill=150)
    p1 = finalize_page(img)
    return [p1], "Fax 4: vague chest x-ray request, DOB missing and no exam date -> should trigger missing-info flag."


# ---------------------------------------------------------------------------
# Fax 5: law office subpoena-style request, mail delivery (kept typed)
# ---------------------------------------------------------------------------

def fax_5():
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0561 DUNMORE & ASSOCIATES LLP", "09/12/2026", "10:20", "P.1/1")
    y = 140
    d.text((40, y), "DUNMORE & ASSOCIATES, LLP", font=font(32), fill=0); y += 46
    d.text((40, y), "Attorneys at Law - 200 Courthouse Sq, Suite 900, Bellcross, TX 55555", font=font(20), fill=0); y += 40
    d.text((40, y), "RE: Subpoena Duces Tecum - Request for Medical Imaging Records", font=font(24), fill=0); y += 50
    y = draw_wrapped(d, (40, y), (
        "Requesting Party: Dunmore & Associates, LLP, on behalf of client\n"
        "Patient Name: TESTPATIENT, DIANE\n"
        "DOB: 06/30/1982      MRN: 552019\n"
        "\n"
        "Records Requested: All diagnostic imaging IMAGES and RADIOLOGY REPORTS\n"
        "Exam Date Range: 01/01/2024 to present\n"
        "\n"
        "Delivery Method: Mail to counsel at address above (paper or CD acceptable)\n"
        "Priority: Routine - 30 day statutory response window\n"
        "Reason for Request: Pending litigation, records requested pursuant to\n"
        "subpoena attached under separate cover. Please include itemized invoice\n"
        "for copying costs.\n"
    ), size=27, line_gap=12)
    p1 = finalize_page(img)
    return [p1], "Fax 5: law-firm subpoena-style request for images + reports, mail delivery."


# ---------------------------------------------------------------------------
# Fax 6: two patients on one fax from a referring clinic, routine
# Handwritten-on-form: letterhead + single-column, two patient cards. Hand: script_bold.
# ---------------------------------------------------------------------------

def fax_6():
    hand = "script_bold"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0673 MAPLEWOOD FAMILY HEALTH", "09/11/2026", "11:33", "P.1/1")
    y = 140
    d.text((40, y), "Maplewood Family Health Clinic", font=font(30), fill=0); y += 44
    d.text((40, y), "Weekly Imaging Records Request Batch", font=font(24), fill=0); y += 46
    rows = [
        ("field", "Requesting Provider:", "Dr. Alan Meeks, MD", 650),
        ("checks", [("Electronic - PowerShare", True)]),
        ("checks", [("Routine", True), ("STAT", False)]),
        ("text", "Reason for Request:", "Referral follow-up for both patients below."),
    ]
    y = render_field_rows(d, y, rows, hand)
    y += 6
    d.line([(40, y), (PAGE_W - 40, y)], fill=0, width=2); y += 24
    d.text((40, y), "Patient 1", font=font(24), fill=0); y += 36
    rows1 = [
        ("field", "Patient Name:", "TESTPATIENT, NANCY"),
        ("pair", ("DOB:", "05/19/1990"), ("MRN:", "771002")),
        ("field", "Exam Requested:", "MRI Lumbar Spine, exam date 09/01/2026", 700),
    ]
    y = render_field_rows(d, y, rows1, hand)
    y += 6
    d.line([(40, y), (PAGE_W - 40, y)], fill=0, width=2); y += 24
    d.text((40, y), "Patient 2", font=font(24), fill=0); y += 36
    rows2 = [
        ("field", "Patient Name:", "TESTPATIENT, OMAR"),
        ("pair", ("DOB:", "01/08/1955"), ("MRN:", "771015")),
        ("field", "Exam Requested:", "CT Chest without contrast, exam date 08/29/2026", 700),
    ]
    render_field_rows(d, y, rows2, hand)
    p1 = finalize_page(img)
    return [p1], "Fax 6: two different patients listed on one fax from a referring clinic, routine."


# ---------------------------------------------------------------------------
# Fax 7: NOT an imaging request (pharmacy prior-authorization form, kept typed)
# ---------------------------------------------------------------------------

def fax_7():
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0789 CORNERSTONE PHARMACY BENEFITS", "09/10/2026", "09:05", "P.1/1")
    y = 140
    d.text((40, y), "Cornerstone Pharmacy Benefits", font=font(30), fill=0); y += 44
    d.text((40, y), "PRIOR AUTHORIZATION REQUEST FORM", font=font(28), fill=0); y += 48
    y = draw_wrapped(d, (40, y), (
        "Member Name: TESTPATIENT, CARL\n"
        "Member ID: PBM55501234\n"
        "Prescriber: Dr. Linda Ashworth, MD\n"
        "\n"
        "Medication Requested: Atorvastatin 40mg, 90-day supply\n"
        "Diagnosis Code: E78.5\n"
        "\n"
        "Has patient tried and failed generic alternative?  [ ] Yes  [ ] No\n"
        "Clinical justification: see attached chart notes.\n"
        "\n"
        "Please fax completed determination to 555-0790 within 72 hours.\n"
        "This form is NOT a request for medical imaging records.\n"
    ), size=27, line_gap=12)
    p1 = finalize_page(img)
    return [p1], "Fax 7: pharmacy prior-authorization form, not an imaging request at all (negative test case)."


# ---------------------------------------------------------------------------
# Fax 8: handwritten free-text, ultrasound OB, ASAP, phone only
# Nearly blank form: printed header fields + a big "Request" box filled with
# hand-written prose, messy/large. Hand: script.
# ---------------------------------------------------------------------------

def fax_8():
    hand = "script"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0912 DR. R. NAKAMURA OB/GYN", "09/16/2026", "07:22", "P.1/1")
    y = 140
    d.text((40, y), "Dr. R. Nakamura OB/GYN - Records Request", font=font(28), fill=0); y += 50
    y = draw_field(d, (40, y), "Patient:", "TESTPATIENT, Grace", hand, hand_size=40, row_gap=64)
    y = draw_field(d, (40, y), "DOB:", "03/02/1996", hand, hand_size=40, row_gap=64, line_len=350)
    y += 10
    render_request_box(d, y, hand, (
        "Need: Ultrasound OB (pregnancy), most recent one you have.\n"
        "ASAP please!! not STAT but pt is here today.\n"
        "Call me back - 555-0913 (no fax back, just call)."
    ), hand_size=44)
    p1 = finalize_page(img, low_contrast=False)
    return [p1], "Fax 8: handwritten-style, urgent ultrasound OB request (\"ASAP\" not STAT), phone callback only, no fax back."


# ---------------------------------------------------------------------------
# Fax 9: routine, two exams (knee x-ray + CT head) performed elsewhere at
# "Cleveland Clinic Akron General", fax-back requested
# Handwritten-on-form: two-column with letterhead, messy/large. Hand: ink.
# ---------------------------------------------------------------------------

def fax_9():
    hand = "ink"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0733 PORTAGE LAKES FAMILY PRACTICE", "09/08/2026", "10:12", "P.1/1")
    y = draw_letterhead(d, 140, "Portage Lakes Family Practice",
                         "4410 Portage Lakes Dr, Portage Lakes, OH 55555",
                         "Phone: 555-0733   Fax: 555-0734")
    d.text((40, y), "IMAGING RECORDS REQUEST", font=font(30), fill=0); y += 50
    rows = [
        ("field", "Requesting Provider:", "Dr. Wanda Holt, MD", 750),
        ("field", "Patient Name:", "TESTPATIENT, HENRY", 650),
        ("field", "DOB:", "09/14/1961", 400),
        ("field", "Exam(s) Requested:", "Knee x-ray series (bilateral) and CT Head", 800),
        ("field", "Exam Date:", "performed 06/2026 at Cleveland Clinic Akron General", 850),
        ("checks", [("Fax", True), ("Electronic", True), ("Mail", False)]),
        ("field", "Fax-back / Notes:", "fax back to 555-0734 to confirm receipt", 750),
        ("checks", [("Routine", True), ("STAT", False)]),
        ("text", "Reason for Request:",
         "patient transferring care to our practice, need imaging performed at "
         "Akron General for the chart."),
    ]
    render_field_rows(d, y, rows, hand, hand_size=44, row_gap=84, label_size=27)
    p1 = finalize_page(img)
    return [p1], "Fax 9: routine knee x-ray series + CT head performed at Cleveland Clinic Akron General, fax-back requested -> should route to Akron team."


# ---------------------------------------------------------------------------
# Fax 10: cardiac-only imaging request (TTE + cath films), Ambra share code
# (kept typed)
# ---------------------------------------------------------------------------

def fax_10():
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0820 SUMMIT RIDGE CARDIOLOGY", "09/09/2026", "14:27", "P.1/1")
    y = 140
    d.text((40, y), "SUMMIT RIDGE CARDIOLOGY GROUP", font=font(30), fill=0); y += 44
    d.text((40, y), "Cardiac Imaging Records Request", font=font(24), fill=0); y += 46
    y = draw_wrapped(d, (40, y), (
        "Requesting Provider: Dr. Iris Kwan, MD - Cardiology\n"
        "Patient Name: TESTPATIENT, LINDA\n"
        "DOB: 12/05/1958      MRN: 660412\n"
        "\n"
        "Exam(s) Requested:\n"
        "  - Echocardiogram (TTE), exam date 07/02/2026\n"
        "  - Cardiac catheterization films, exam date 07/09/2026\n"
        "\n"
        "Delivery Method: please send to our Ambra share code SRC-4K9T\n"
        "Priority: Routine\n"
        "Reason for Request: cardiology follow-up, need prior cardiac imaging\n"
        "for comparison.\n"
        "\n"
        "Phone: 555-0820   Fax: 555-0821\n"
    ), size=27, line_gap=12)
    p1 = finalize_page(img)
    return [p1], "Fax 10: cardiac-only request (TTE + cath films), Ambra share code SRC-4K9T -> should route to HVTI, not radiology."


# ---------------------------------------------------------------------------
# Fax 11: URGENT mixed request (radiology + cardiac exams), two pages,
# page 2 signed authorization
# Handwritten-on-form: letterhead + single-column p1, authorization p2. Hand: print_bold.
# ---------------------------------------------------------------------------

def fax_11():
    hand = "print_bold"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0901 HARBOR POINT MEDICAL CENTER", "09/10/2026", "09:40", "P.1/2")
    y = 140
    d.text((40, y), "*** URGENT ***", font=font(36), fill=0); y += 52
    y = draw_letterhead(d, y, "HARBOR POINT MEDICAL CENTER - DEPT OF INTERNAL MEDICINE",
                         contact="Phone: 555-0901   Fax: 555-0902", name_size=26)
    rows = [
        ("field", "Requesting Provider:", "Dr. Anita Feld, MD - Internal Medicine", 750),
        ("field", "Patient Name:", "TESTPATIENT, GEORGE", 650),
        ("field", "DOB:", "03/22/1970", 400),
        ("field", "Exam 1:", "CT Chest with contrast - 08/11/2026", 750),
        ("field", "Exam 2:", "Chest X-ray - 08/10/2026", 750),
        ("field", "Exam 3:", "Echocardiogram - 08/12/2026", 750),
        ("field", "Exam 4:", "Nuclear stress test - 08/13/2026", 750),
        ("field", "Delivery / Send to:", "Ambra share code HPMC-7Q2X", 700),
        ("checks", [("URGENT", True), ("Routine", False)]),
        ("text", "Notes:",
         "Patient has appointment 09/19/2026. Signed authorization attached on page 2."),
    ]
    render_field_rows(d, y, rows, hand, hand_size=32, row_gap=64, label_size=27)
    p1 = finalize_page(img)

    img2 = new_page()
    d2 = ImageDraw.Draw(img2)
    draw_fax_header(d2, "555-0901 HARBOR POINT MEDICAL CENTER", "09/10/2026", "09:41", "P.2/2")
    render_authorization(d2, 140, hand, "GEORGE TESTPATIENT",
                          "Harbor Point Medical Center, Dept of Internal Medicine",
                          "/s/ George Testpatient", "09/09/2026", images=True, reports=False)
    p2 = finalize_page(img2)
    return [p1, p2], "Fax 11: URGENT mixed request (CT chest/CXR + echo/nuclear stress) -> radiology part stays here, cardiac part forwards to HVTI. Page 2 is signed authorization."


# ---------------------------------------------------------------------------
# Fax 12: unknown facility not in lookup, supplies its own PowerShare
# destination, explicitly wants images AND the written report
# Handwritten-on-form: two-column with letterhead. Hand: script_bold.
# ---------------------------------------------------------------------------

def fax_12():
    hand = "script_bold"
    img = new_page()
    d = ImageDraw.Draw(img)
    draw_fax_header(d, "555-0655 WILLOW CREEK IMAGING", "09/11/2026", "15:05", "P.1/1")
    y = draw_letterhead(d, 140, "Willow Creek Imaging Center",
                         "1120 Willow Creek Blvd, Fernvale, MI 55555",
                         "Phone: 555-0655   Fax: 555-0656")
    d.text((40, y), "RECORDS REQUEST - MRI", font=font(30), fill=0); y += 50
    rows = [
        ("field", "Requesting Provider:", "Dr. Miguel Santoro, MD", 700),
        ("pair", ("Patient Name:", "TESTPATIENT, SOFIA"), ("DOB:", "07/17/1988")),
        ("field", "Exam(s) Requested:", "MRI Right Knee without contrast", 700),
        ("field", "Exam Date:", "05/30/2026", 400),
        ("checks", [("Images", True), ("Report", True)]),
        ("field", "Send to / Address / Email:", "willowcreek.imaging@example.com (PowerShare)", 850),
        ("checks", [("Routine", True), ("STAT", False)]),
        ("text", "Reason for Request:",
         "patient establishing care at our imaging center, need prior study and "
         "report for comparison."),
    ]
    render_field_rows(d, y, rows, hand)
    p1 = finalize_page(img)
    return [p1], "Fax 12: unknown facility (Willow Creek Imaging, not in lookup) supplies its own PowerShare email destination, explicitly wants images AND the written report."


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.upper().endswith(".PDF"):
            os.remove(os.path.join(OUT_DIR, f))

    builders = [fax_1, fax_2, fax_3, fax_4, fax_5, fax_6, fax_7, fax_8,
                fax_9, fax_10, fax_11, fax_12]
    names = ["01A182c3.PDF", "01A182d7.PDF", "01A182e1.PDF", "01A182f5.PDF",
             "01A18309.PDF", "01A1831d.PDF", "01A18331.PDF", "01A18345.PDF",
             "01A18359.PDF", "01A1836d.PDF", "01A18381.PDF", "01A18395.PDF"]

    # fax 4 gets the noticeably-lower-contrast treatment
    low_contrast_index = 3

    results = []
    for i, (build, name) in enumerate(zip(builders, names)):
        pages, desc = build()
        if i == low_contrast_index:
            pages = [ImageEnhance.Contrast(p).enhance(0.5) for p in pages]
        path = save_pdf(pages, name)
        results.append((name, desc, os.path.getsize(path)))

    print(f"Created {len(results)} fax PDFs in {OUT_DIR}\n")
    for name, desc, size in results:
        print(f"  {name}  ({size:,} bytes)\n    {desc}")


def demo():
    """ponytail: smallest runnable check -- render fax_4 and verify a real PDF comes out."""
    os.makedirs(OUT_DIR, exist_ok=True)
    pages, _ = fax_4()
    assert len(pages) == 1
    assert pages[0].size == (PAGE_W, PAGE_H)
    tmp = os.path.join(OUT_DIR, "_selftest.pdf")
    pages[0].save(tmp, "PDF", resolution=DPI)
    assert os.path.getsize(tmp) > 1000
    os.remove(tmp)
    print("demo() self-check passed")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        demo()
    else:
        main()
