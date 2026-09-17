#!/usr/bin/env python3
"""triage.py -- auto-fill facility/patient/exam fields from inbound imaging-request faxes.

Reads anonymous fax PDFs, asks an LLM to extract structured fields, post-processes
the answer in plain Python, decides a routing/delivery/reports plan, fills a draft
of the RightFax web form, renames a copy of the PDF, and writes results.json /
results.csv / worklist.csv + a summary table.
"""
import argparse
import csv
import difflib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Model used for extraction. Swap this (and extract()) for a direct Anthropic API
# call later -- everything else in this file is model-agnostic.
# sonnet, not haiku: on 17 handwritten test faxes haiku misread 2 of 15 DOBs
# (confidently), sonnet misread none. A wrong DOB is a wrong patient.
DEFAULT_MODEL = "sonnet"

FIELDS_PROMPT = """Read the fax PDF at this path: {pdf_path}

It is an anonymous fax sent to a hospital radiology image library. Extract the
requested imaging order information and respond with ONLY a single JSON object
(no markdown fences, no commentary) with exactly these keys:

is_imaging_request (bool)
priority ("STAT" | "URGENT" | "ROUTINE")
facility_name (string or null)
facility_phone (string or null)
facility_fax (string or null)
facility_address (string or null)
requesting_provider (string or null)
patients (list of {{"name": string or null, "dob": string or null, "mrn": string or null, "gender": string or null, "phone": string or null}})
exams (list of {{"exam": string, "date": string or null, "group": "radiology" | "cardiac" | "dental_eye" | "other"}})
exam_date_range ({{"from": string, "to": string}} or null)
exam_dates_text (short string summarizing dates/ranges/"most recent" language, or null)
delivery_method ("electronic" | "mail" | "unknown")
delivery_target (string or null, e.g. "PowerShare", a fax number, or a mailing address)
ambra_share_code (string or null -- an Ambra share code if one is given)
powershare_destination (string or null -- a PowerShare destination name/id if given)
recipient_email (string or null -- an email address to send images/reports to, if given)
mailing_address (string or null -- a mailing address to mail a CD to, if given)
number_of_cds (int or null)
performed_at_akron (bool -- true if the fax says the imaging was performed at Akron General / Cleveland Clinic Akron General / an Akron facility)
is_legal (bool -- true if this is from a law office/attorney, or references a subpoena or court)
reports_requested (bool -- true ONLY if the fax explicitly asks for written/radiology reports, not just images)
authorization_attached (bool)
missing_info (list of strings -- anything required but missing or unreadable)
summary (one sentence string)
confidence ("high" | "medium" | "low")

Exam grouping: "radiology" for standard imaging (CT, MRI, X-ray, ultrasound,
mammo, PET, nuclear med, fluoro); "cardiac" for echocardiogram/TTE/TEE, cardiac
cath, nuclear stress test, cardiac CT/MRI, coronary CTA, EKG; "dental_eye" for
dental or eye/ophthalmology imaging; "other" for anything else.

Rules: write patient names as "LAST, FIRST" using the form's own labels to tell
last from first. Write all dates as MM/DD/YYYY. Do not guess -- use null (or an empty
list) when a value is not clearly present on the page. facility_name is the
requesting organization, whatever it is: clinic, hospital, law office, insurer,
or a doctor's practice name. is_imaging_request is true for ANY request to
release or send imaging studies or radiology reports, including from law
offices, insurers, or patients. One exams entry per exam: never combine two
exams into one entry (e.g. a mammogram and a breast ultrasound are two entries).
If the fax asks for all imaging on file, use one
exams entry {{"exam": "All imaging", "date": null, "group": "radiology"}}.
Handwritten digits are easy to misread: read every date digit by digit, and if
a DOB or exam date is not clearly legible, set it to null and list it in
missing_info rather than guessing.
missing_info lists ONLY what is needed to fulfil the request: patient name, DOB,
which exams or a date range, and a delivery destination (fax number,
PowerShare, email, or mailing address). MRN, phone number, and street address
are NEVER missing info. Return ONLY the JSON object, nothing else.
"""


def extract(pdf_path: Path, model: str = DEFAULT_MODEL, base_url: str = None,
            api_key: str = None) -> dict:
    """Call the model to pull structured fields out of one fax PDF.

    Two backends, same prompt, same JSON contract:
    - default: the local `claude` CLI (Claude subscription, no API key).
    - base_url given: any OpenAI-compatible chat endpoint that accepts images
      (OpenCode Go in the cloud today, Ollama/vLLM on a GPU box tomorrow).
    """
    if base_url:
        return extract_openai(pdf_path, model, base_url, api_key)
    if "/" in model:  # "provider/model" means the opencode CLI, e.g. opencode-go/kimi-k3
        return extract_opencode(pdf_path, model)
    prompt = FIELDS_PROMPT.format(pdf_path=str(pdf_path.resolve()))
    # Prompt goes in via stdin: long prompts with quotes/newlines break the Windows shell.
    proc = subprocess.run(
        ["claude.cmd", "-p", "--model", model,
         "--output-format", "json", "--allowedTools", "Read"],
        input=prompt, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    envelope = json.loads(proc.stdout)
    raw = envelope["result"]
    return parse_model_json(raw)


def pdf_pages_png_b64(pdf_path: Path, scale: float = 2.0, max_pages: int = 4) -> list:
    """Render each page to PNG (about 150 dpi) and base64 it for an image API."""
    import base64
    import io
    import pypdfium2 as pdfium
    out = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            buf = io.BytesIO()
            page.render(scale=scale).to_pil().convert("RGB").save(buf, "PNG")
            page.close()
            out.append(base64.b64encode(buf.getvalue()).decode())
    finally:
        doc.close()
    return out


def extract_openai(pdf_path: Path, model: str, base_url: str, api_key: str = None) -> dict:
    """OpenAI-compatible /chat/completions with the fax pages attached as images."""
    import urllib.request
    prompt = FIELDS_PROMPT.format(pdf_path="(the fax pages are attached as images)")
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        for b64 in pdf_pages_png_b64(pdf_path)
    ]
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}],
                       "temperature": 0, "max_tokens": 4000}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
    with urllib.request.urlopen(req, timeout=300) as resp:
        reply = json.loads(resp.read())
    raw = reply["choices"][0]["message"]["content"]
    if isinstance(raw, list):  # some servers return content parts
        raw = "".join(p.get("text", "") for p in raw)
    return parse_model_json(raw)


def opencode_text_from_events(stdout: str) -> str:
    """`opencode run --format json` prints one JSON event per line; join the text parts."""
    parts = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "text":
            parts.append(ev.get("part", {}).get("text", ""))
    return "".join(parts)


def extract_opencode(pdf_path: Path, model: str) -> dict:
    """Any model the opencode CLI can reach (its own login, no key handling here)."""
    import base64
    import tempfile
    prompt = FIELDS_PROMPT.format(pdf_path="(the fax pages are attached as images)")
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for i, b64 in enumerate(pdf_pages_png_b64(pdf_path)):
            p = Path(tmp) / f"page{i + 1}.png"
            p.write_bytes(base64.b64decode(b64))
            files += ["-f", str(p)]
        # Prompt first: "-f" is an array flag and would swallow a trailing prompt as a file name.
        proc = subprocess.run(["opencode.exe", "run", prompt, "-m", model, "--format", "json", *files],
                              capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"opencode exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    return parse_model_json(opencode_text_from_events(proc.stdout))


def ocr_text(pdf_path: Path) -> str:
    """Windows built-in OCR (free, offline) via ocr_windows.ps1. Empty string if unavailable."""
    script = Path(__file__).with_name("ocr_windows.ps1")
    if not script.exists():
        return ""
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                               "-File", str(script), str(pdf_path.resolve())],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return "\n".join(l for l in proc.stdout.splitlines() if not l.startswith("====="))


_DATE = r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})"


def find_dobs(text: str) -> list:
    """Every date written right after a DOB label in OCR text, as MM/DD/YYYY, in order."""
    out = []
    for mm, dd, yyyy in re.findall(
            r"(?:\bDOB\b|D\.O\.B|date\s+of\s+birth|birth\s*date)\W{0,20}" + _DATE, text or "", re.I):
        d = f"{int(mm):02d}/{int(dd):02d}/{yyyy}"
        if d not in out:
            out.append(d)
    return out


def dob_cross_check(record: dict) -> str:
    """Two readers must agree. OCR is only trusted where it found a labelled DOB, and a
    fax can list several patients, so any OCR DOB matching any patient is fine."""
    ocr_dobs = record.get("ocr_dobs") or []
    if not ocr_dobs:
        return ""
    model_dobs = [p.get("dob") for p in record.get("patients") or [] if p.get("dob")]
    if not model_dobs:
        return f"OCR read DOB {', '.join(ocr_dobs)}, model read none: verify"
    if not set(ocr_dobs) & set(model_dobs):
        return f"DOB conflict: model {', '.join(model_dobs)}, OCR {', '.join(ocr_dobs)}: verify"
    return ""


def load_api_key(env_name: str, key_file: str = None, key_path: str = None) -> str:
    """Key from an env var, else from a JSON file by dotted path (never printed)."""
    import os
    if os.environ.get(env_name):
        return os.environ[env_name]
    if key_file and key_path:
        node = json.loads(Path(key_file).read_text())
        for part in key_path.split("."):
            node = node[part]
        return node
    return None


def strip_json_fences(raw: str) -> str:
    """Defensively strip ```json ... ``` / ``` ... ``` fences around a model reply."""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_model_json(raw: str) -> dict:
    """Parse the model's answer text into a dict. Raises on bad JSON (caller handles)."""
    return json.loads(strip_json_fences(raw))


def safe_slug(text, max_len: int = 40) -> str:
    """Letters/digits/underscore only, collapsed, truncated. Empty/None -> 'unknown'."""
    if not text:
        return "unknown"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")
    return (slug[:max_len].rstrip("_")) or "unknown"


def patient_name_slug(patients) -> str:
    """'last_first' slug of the first patient, plus '_+N' when there are more."""
    if not patients:
        return "unknown"
    first = patients[0] or {}
    name = (first.get("name") or "").strip()
    if name:
        parts = name.split()
        if len(parts) >= 2:
            last, rest = parts[-1], " ".join(parts[:-1])
            slug = safe_slug(f"{last}_{rest}")
        else:
            slug = safe_slug(name)
    else:
        slug = "unknown"
    if len(patients) > 1:
        slug = f"{slug}_+{len(patients) - 1}"
    return slug


# Routes that get called out in the filename ahead of the priority; RADIOLOGY
# (the common case) keeps the old plain "{PRIORITY}_..." look.
ROUTE_PREFIXED = {"LEGAL", "AKRON", "HVTI", "SPLIT_HVTI", "NOT_IMAGING"}


def build_new_filename(record: dict, received_date: str, route: str = "RADIOLOGY") -> str:
    """{ROUTE?}_{PRIORITY}_{facility_slug}_{patient_last_first_slug}_{received_date}.pdf"""
    priority = record.get("priority") or "ROUTINE"
    if priority not in ("STAT", "URGENT", "ROUTINE"):
        priority = "ROUTINE"
    facility = safe_slug(record.get("facility_name"))
    patient = patient_name_slug(record.get("patients"))
    prefix = f"{route}_{priority}" if route in ROUTE_PREFIXED else priority
    # Original fax id stays in the name: keeps names unique and traceable to the source.
    src = Path(record.get("source_file") or "").stem
    return f"{prefix}_{facility}_{patient}_{received_date}_{src}.pdf".replace("_.pdf", ".pdf")


def compute_needs_review(record: dict, delivery_type: str = None, route: str = None) -> bool:
    if not record.get("is_imaging_request"):
        return True
    if record.get("missing_info"):
        return True
    if (record.get("confidence") or "").lower() == "low":
        return True
    if not record.get("patients"):
        return True
    if not record.get("exams"):
        return True
    if route == "LEGAL":  # not processed here at all, just faxed to CCF Legal
        return False
    if delivery_type == "UNKNOWN":
        return True
    if record.get("dob_check"):  # OCR and the model disagree on the DOB
        return True
    return False


def make_error_record(source_file: str, error: str) -> dict:
    """Row used when the model reply couldn't be parsed -- batch keeps going."""
    return {
        "source_file": source_file,
        "error": error,
        "is_imaging_request": False,
        "priority": "ROUTINE",
        "facility_name": None,
        "facility_phone": None,
        "facility_fax": None,
        "facility_address": None,
        "requesting_provider": None,
        "patients": [],
        "exams": [],
        "exam_date_range": None,
        "exam_dates_text": None,
        "delivery_method": "unknown",
        "delivery_target": None,
        "ambra_share_code": None,
        "powershare_destination": None,
        "recipient_email": None,
        "mailing_address": None,
        "number_of_cds": None,
        "performed_at_akron": False,
        "is_legal": False,
        "reports_requested": False,
        "reason_for_request": None,
        "authorization_attached": False,
        "missing_info": ["could not parse model response"],
        "summary": f"Extraction failed: {error}",
        "confidence": "low",
    }


# ---------------------------------------------------------------------------
# Facility list matching
# ---------------------------------------------------------------------------

_STOPWORDS = {"the", "a", "an"}


def normalize_facility_name(name) -> str:
    if not name:
        return ""
    s = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    words = [w for w in s.split() if w not in _STOPWORDS]
    return " ".join(words)


def load_facilities(path="facilities.csv") -> list:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def match_facility(name, rows):
    """Fuzzy-match a facility name against the connectivity list. None if no good match."""
    target = normalize_facility_name(name)
    if not target or not rows:
        return None
    by_norm = {}
    for row in rows:
        norm = normalize_facility_name(row.get("facility_name"))
        if norm:
            by_norm[norm] = row
    # Strict on purpose: a wrong match sends images to the wrong facility. High
    # similarity AND the same first word ("washington radiology" must never match
    # "summit ridge cardiology", "riverside" must never match "riverbend").
    first = target.split()[0]
    # "harbor point medical center dept of internal medicine" contains the listed name
    for norm, row in by_norm.items():
        if norm.split()[0] == first and (norm in target or target in norm):
            return row
    hit = difflib.get_close_matches(target, by_norm.keys(), n=1, cutoff=0.8)
    if hit and hit[0].split()[0] == first:
        return by_norm[hit[0]]
    return None


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def decide_route(record: dict) -> str:
    if not record.get("is_imaging_request"):
        return "NOT_IMAGING"
    if record.get("is_legal"):
        return "LEGAL"
    if record.get("performed_at_akron"):
        return "AKRON"
    groups = {e.get("group") for e in (record.get("exams") or []) if e}
    if groups == {"dental_eye"}:
        return "DENTAL_EYE"
    if groups == {"cardiac"}:
        return "HVTI"
    if "cardiac" in groups and "radiology" in groups:
        return "SPLIT_HVTI"
    return "RADIOLOGY"


def _exam_names(exams, group) -> str:
    return ", ".join(e.get("exam") or "?" for e in exams if e.get("group") == group)


def route_note(record: dict, route: str) -> str:
    exams = record.get("exams") or []
    if route == "NOT_IMAGING":
        return "Not an imaging request"
    if route == "LEGAL":
        return "Fax to CCF Legal. Do not process."
    if route == "AKRON":
        return "Flag, push to Akron system"
    if route == "DENTAL_EYE":
        return "Refer to Dental/Eye department"
    if route == "HVTI":
        return "Forward fax to HVTI (cardiac only)"
    if route == "SPLIT_HVTI":
        return (f"Work radiology exams here: {_exam_names(exams, 'radiology')}; "
                f"email PDF to HVTI for: {_exam_names(exams, 'cardiac')}")
    return f"Work radiology exams here: {_exam_names(exams, 'radiology') or 'see exams'}"


# ---------------------------------------------------------------------------
# Delivery + reports
# ---------------------------------------------------------------------------

def decide_delivery(record: dict, facility_row) -> tuple:
    """-> (delivery, method, where). Precedence: ambra > powershare > email >
    list connection > mailing address > unknown."""
    if record.get("ambra_share_code"):
        return "ELECTRONIC", "Ambra", record["ambra_share_code"]
    if record.get("powershare_destination"):
        return "ELECTRONIC", "PowerShare", record["powershare_destination"]
    if record.get("recipient_email"):
        return "ELECTRONIC", "Email", record["recipient_email"]
    if facility_row and (facility_row.get("connection") or "none") != "none":
        return "ELECTRONIC", f"{facility_row['connection']} (on list)", facility_row.get("destination") or ""
    if record.get("mailing_address"):
        return "MAILED CD", "Mail", record["mailing_address"]
    return "UNKNOWN", "", ""


def decide_send_reports(record: dict, facility_row) -> tuple:
    """-> (bool, reason)."""
    if record.get("reports_requested"):
        return True, "fax explicitly requested reports"
    if facility_row is None:
        return True, "facility not on connectivity list"
    if (facility_row.get("care_everywhere") or "").lower() == "yes":
        return False, "facility in Epic Care Everywhere"
    return True, "facility not in Care Everywhere"


# ---------------------------------------------------------------------------
# Image type (RightFax "Image Type" field)
# ---------------------------------------------------------------------------

_MODALITY_PATTERNS = [
    (r"magnetic resonance|\bmri\b", "MRI"),
    (r"mammo", "Mammo"),
    (r"nuclear|\bnm\b", "NM"),
    (r"echo", "Echo"),
    (r"\bcath\b", "Cath"),
    (r"fluoro", "Fluoro"),
    (r"x-?ray|radiograph", "XR"),
    (r"ultrasound|sonogram|\bus\b", "US"),
    (r"\bpet\b", "PET"),
    (r"\bcta\b|\bct\b|cat scan", "CT"),
]


def modality_for_exam(exam_name) -> str:
    name = (exam_name or "").lower()
    for pattern, code in _MODALITY_PATTERNS:
        if re.search(pattern, name):
            return code
    return "Other"


def image_type_summary(exams) -> str:
    codes = []
    for e in exams or []:
        code = modality_for_exam(e.get("exam"))
        if code not in codes:
            codes.append(code)
    return "; ".join(codes)


# ---------------------------------------------------------------------------
# Worklist row (what the human pastes into Epic / RightFax)
# ---------------------------------------------------------------------------

def last_first(name) -> str:
    """'Jane Doe' or 'DOE, JANE' -> 'DOE, JANE'. Ready to paste into Epic."""
    # Underlines on forms get read as "_" by the model; treat them as spaces.
    name = (name or "").replace("_", " ").strip()
    if not name:
        return ""
    if "," in name:
        last, first = name.split(",", 1)
    else:
        parts = name.split()
        last, first = parts[-1], " ".join(parts[:-1])
    return f"{last.strip()}, {first.strip()}".strip(", ").upper()


def imaging_type(exams) -> str:
    """RADIOLOGY / MAMMOGRAPHY / BOTH (plus CARDIAC when HVTI exams are present)."""
    exams = exams or []
    if not exams:
        return ""
    mammo = any(modality_for_exam(e.get("exam")) == "Mammo" for e in exams)
    cardiac = any(e.get("group") == "cardiac" for e in exams)
    radiology = any(e.get("group") == "radiology" and modality_for_exam(e.get("exam")) != "Mammo"
                    for e in exams)
    base = "BOTH" if (mammo and radiology) else "MAMMOGRAPHY" if mammo else "RADIOLOGY" if radiology else ""
    if cardiac:
        return f"{base} + CARDIAC" if base else "CARDIAC"
    return base


def exam_dates(record: dict) -> str:
    dates = []
    for e in record.get("exams") or []:
        if e.get("date") and e["date"] not in dates:
            dates.append(e["date"])
    if dates:
        return "; ".join(dates)
    rng = record.get("exam_date_range") or {}
    if rng.get("from") or rng.get("to"):
        return f"{rng.get('from') or '?'} to {rng.get('to') or 'present'}"
    return record.get("exam_dates_text") or ""


def connection_lookup(facility_row, given_name=None) -> str:
    """What the internal connectivity list says about this facility."""
    if not facility_row:
        return "not on list"
    conn = facility_row.get("connection") or "none"
    text = ("on list, no electronic connection" if conn == "none"
            else f"{conn}: {facility_row.get('destination') or ''}".strip(": "))
    listed = facility_row.get("facility_name") or ""
    if given_name and normalize_facility_name(given_name) != normalize_facility_name(listed):
        text += f" (matched as '{listed}', verify)"  # fuzzy match: a human should confirm
    return text


FORM_KEYS = ("patient", "dob", "epic_search", "imaging_type", "facility", "exam_dates", "exams",
             "delivery", "method", "send_to", "connection_lookup", "mail_address", "cd_copies",
             "reports", "reports_fax", "notes")


def build_form_fill(record: dict, facility_row, route: str, note: str, delivery: str,
                    method: str, where: str, send_reports: bool) -> dict:
    if route == "LEGAL":  # nothing to fill in: the whole fax goes to Legal untouched
        return {**{k: "" for k in FORM_KEYS}, "facility": record.get("facility_name") or "", "notes": note}
    patients = record.get("patients") or []
    first = patients[0] if patients else {}
    exams = record.get("exams") or []
    patient = last_first(first.get("name"))
    dob = first.get("dob") or ""
    reports_fax = (record.get("facility_fax") or "") if send_reports else ""

    cds = record.get("number_of_cds")
    if cds is None:
        cds = 1

    notes = []
    if route != "RADIOLOGY":
        notes.append(note)
    if record.get("missing_info"):
        notes.append("Missing: " + "; ".join(record["missing_info"]))
    if send_reports and not reports_fax:
        notes.append("Reports: no fax number given")
    if record.get("dob_check"):
        notes.append(record["dob_check"])
    if len(patients) > 1:
        notes.append("2nd patient: " + "; ".join(
            f"{last_first(p.get('name'))} {p.get('dob') or ''}".strip() for p in patients[1:]))

    return {
        "patient": patient,
        "dob": dob,
        "epic_search": f"{patient} {dob}".strip(),
        "imaging_type": imaging_type(exams),
        "facility": record.get("facility_name") or "",
        "exam_dates": exam_dates(record),
        "exams": "; ".join(e.get("exam") or "?" for e in exams),
        "delivery": delivery,
        "method": method if delivery == "ELECTRONIC" else "",
        "send_to": where if delivery == "ELECTRONIC" else "",
        "connection_lookup": connection_lookup(facility_row, record.get("facility_name")),
        "mail_address": where if delivery == "MAILED CD" else "",
        "cd_copies": cds if delivery == "MAILED CD" else "",
        "reports": "Y" if send_reports else "N",
        "reports_fax": reports_fax,
        "notes": " | ".join(notes),
    }


def to_csv_row(record: dict) -> dict:
    patients = record.get("patients") or []
    date_range = record.get("exam_date_range") or {}
    exams = record.get("exams") or []
    exams_text = ";".join(
        f"{e.get('exam', '?')} ({e['date']})" if e.get("date") else (e.get("exam") or "?")
        for e in exams
    )
    return {
        "source_file": record.get("source_file"),
        "new_file": record.get("new_file"),
        "priority": record.get("priority"),
        "route": record.get("route"),
        "needs_review": record.get("needs_review"),
        "is_imaging_request": record.get("is_imaging_request"),
        "facility_name": record.get("facility_name"),
        "patient_names": ";".join(p.get("name") or "" for p in patients),
        "dobs": ";".join(p.get("dob") or "" for p in patients),
        "exams": exams_text,
        "date_from": date_range.get("from"),
        "date_to": date_range.get("to"),
        "delivery_method": record.get("delivery_method"),
        "delivery_target": record.get("delivery_target"),
        "delivery_type": record.get("delivery_type"),
        "delivery_plan": record.get("delivery_plan"),
        "send_reports": record.get("send_reports"),
        "authorization_attached": record.get("authorization_attached"),
        "missing_info": ";".join(record.get("missing_info") or []),
        "confidence": record.get("confidence"),
        "summary": record.get("summary"),
    }


CSV_FIELDS = [
    "source_file", "new_file", "priority", "route", "needs_review", "is_imaging_request",
    "facility_name", "patient_names", "dobs", "exams", "date_from", "date_to",
    "delivery_method", "delivery_target", "delivery_type", "delivery_plan", "send_reports",
    "authorization_attached", "missing_info", "confidence", "summary",
]


WORKLIST_FIELDS = [
    "fax", "route", "priority", "needs_review",
    "patient", "dob", "epic_search", "imaging_type", "facility", "exam_dates", "exams",
    "delivery", "method", "send_to", "connection_lookup", "mail_address", "cd_copies",
    "reports", "reports_fax", "notes", "new_file",
]


def to_worklist_row(record: dict) -> dict:
    ff = record.get("form_fill") or {}
    row = {"fax": record.get("source_file"), "route": record.get("route"),
           "priority": record.get("priority"), "needs_review": record.get("needs_review")}
    row.update({k: ff.get(k, "") for k in WORKLIST_FIELDS if k in ff})
    row["new_file"] = record.get("new_file")
    return row


def print_summary_table(records: list) -> None:
    cols = ("fax", "route", "patient", "dob", "imaging_type", "delivery", "send_to",
            "connection_lookup", "reports", "reports_fax", "needs_review")
    rows = [cols]
    for r in records:
        w = to_worklist_row(r)
        rows.append(tuple(str(w.get(c) if w.get(c) is not None else "-")[:34] for c in cols))
    widths = [max(len(row[i]) for row in rows) for i in range(len(cols))]
    for row in rows:
        print(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def apply_rules(data: dict, facilities: list) -> dict:
    """Route, delivery, reports, review flag, form fill. Pure Python, no model."""
    # MRN is looked up in Epic, never required from the fax, whatever the model says.
    data["missing_info"] = [m for m in data.get("missing_info") or []
                            if not re.search(r"\bmrn\b|medical record", m, re.I)]
    data["dob_check"] = dob_cross_check(data)
    facility_row = match_facility(data.get("facility_name"), facilities)
    route = decide_route(data)
    note = route_note(data, route)
    delivery_type, method, where = decide_delivery(data, facility_row)
    send_reports, send_reports_reason = decide_send_reports(data, facility_row)
    data.update({
        "route": route,
        "route_note": note,
        "delivery_type": delivery_type,
        "delivery_plan": f"{method}: {where}".strip(": "),
        "send_reports": send_reports,
        "send_reports_reason": send_reports_reason,
        "facility_on_list": bool(facility_row),
        "needs_review": compute_needs_review(data, delivery_type, route),
        "form_fill": build_form_fill(data, facility_row, route, note, delivery_type, method, where, send_reports),
    })
    return data


def process_dir(input_dir: Path, output_dir: Path, model: str, base_url: str = None,
                api_key: str = None) -> list:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.json"
    existing = []
    done_sources = set()
    if results_path.exists():
        existing = json.loads(results_path.read_text())
        done_sources = {r["source_file"] for r in existing}

    facilities = load_facilities()

    pdfs = sorted(set(input_dir.glob("*.pdf")) | set(input_dir.glob("*.PDF")))
    records = list(existing)
    for pdf in pdfs:
        if pdf.name in done_sources:
            continue
        print(f"processing {pdf.name} ...")
        try:
            data = extract(pdf, model, base_url, api_key)
        except Exception as e:  # noqa: BLE001 -- never crash the batch
            data = make_error_record(pdf.name, str(e))
        data["source_file"] = pdf.name
        records.append(data)

    # Rules run on every record, old and new: edit a rule or facilities.csv and rerun,
    # no model calls needed for faxes already extracted.
    for data in records:
        pdf = input_dir / data["source_file"]
        if "ocr_dobs" not in data and pdf.exists():  # free second reader, done once per fax
            data["ocr_dobs"] = find_dobs(ocr_text(pdf))
        apply_rules(data, facilities)
        if pdf.exists():
            received = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%Y%m%d")
            data["new_file"] = build_new_filename(data, received, data["route"])
            shutil.copy2(pdf, output_dir / data["new_file"])
        print(f"  {data['source_file']} -> route={data['route']}  needs_review={data['needs_review']}")

    results_path.write_text(json.dumps(records, indent=2))
    with (output_dir / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(to_csv_row(r))

    with (output_dir / "worklist.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=WORKLIST_FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(to_worklist_row(r))

    return records


def main():
    ap = argparse.ArgumentParser(description="Triage inbound imaging-request faxes.")
    ap.add_argument("input_dir", nargs="?", default="faxes_in")
    ap.add_argument("output_dir", nargs="?", default="faxes_out")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None,
                    help="OpenAI-compatible endpoint, e.g. https://opencode.ai/zen/go/v1 "
                         "or http://localhost:11434/v1 (Ollama). Omit to use the claude CLI.")
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY",
                    help="Name of the env var holding the API key for --base-url")
    args = ap.parse_args()

    api_key = load_api_key(args.api_key_env) if args.base_url else None
    if args.base_url and not api_key and "localhost" not in args.base_url:
        sys.exit(f"set {args.api_key_env} to the API key for {args.base_url}")
    records = process_dir(Path(args.input_dir), Path(args.output_dir), args.model,
                          args.base_url, api_key)
    print()
    print_summary_table(records)


if __name__ == "__main__":
    main()
