"""Tests for the pure (non-model) logic in triage.py. Run: python test_triage.py"""
import json

from triage import (
    apply_rules,
    build_form_fill,
    build_new_filename,
    compute_needs_review,
    decide_delivery,
    decide_route,
    decide_send_reports,
    exam_dates,
    image_type_summary,
    imaging_type,
    last_first,
    make_error_record,
    match_facility,
    modality_for_exam,
    parse_model_json,
    route_note,
    safe_slug,
    strip_json_fences,
    to_worklist_row,
)

FACILITIES = [
    {"facility_name": "Lakeshore Orthopedic Associates", "connection": "PowerShare",
     "care_everywhere": "yes", "destination": "Lakeshore Ortho (PowerShare)", "notes": ""},
    {"facility_name": "Riverbend Surgical Center", "connection": "none",
     "care_everywhere": "no", "destination": "", "notes": ""},
    {"facility_name": "Maplewood Family Health Clinic", "connection": "PowerShare",
     "care_everywhere": "no", "destination": "Maplewood FHC (PowerShare)", "notes": ""},
    {"facility_name": "Summit Ridge Cardiology", "connection": "Ambra",
     "care_everywhere": "yes", "destination": "SRC-4K9T", "notes": "cardiac group; HVTI handles"},
    {"facility_name": "Harbor Point Medical Center", "connection": "Ambra",
     "care_everywhere": "yes", "destination": "HPMC-7Q2X", "notes": ""},
]


def test_safe_slug():
    assert safe_slug("St. Mary's Clinic!") == "St_Mary_s_Clinic"
    assert safe_slug(None) == "unknown"
    assert safe_slug("") == "unknown"
    assert safe_slug("a" * 100) == "a" * 40


def test_build_new_filename_single_patient():
    record = {
        "priority": "STAT",
        "facility_name": "Riverside Imaging",
        "patients": [{"name": "Jane Doe", "dob": "01/02/1980", "mrn": "123"}],
    }
    name = build_new_filename(record, "20260916", "RADIOLOGY")
    assert name == "STAT_Riverside_Imaging_Doe_Jane_20260916.pdf", name


def test_build_new_filename_multi_patient():
    record = {
        "priority": "ROUTINE",
        "facility_name": "Riverside Imaging",
        "patients": [
            {"name": "Jane Doe", "dob": "01/02/1980", "mrn": "123"},
            {"name": "John Smith", "dob": "02/03/1990", "mrn": "456"},
        ],
    }
    name = build_new_filename(record, "20260916", "RADIOLOGY")
    assert name == "ROUTINE_Riverside_Imaging_Doe_Jane_+1_20260916.pdf", name


def test_build_new_filename_null_facility_and_priority():
    record = {"priority": None, "facility_name": None, "patients": []}
    name = build_new_filename(record, "20260916", "RADIOLOGY")
    assert name == "ROUTINE_unknown_unknown_20260916.pdf", name

    record = {"priority": "BOGUS", "facility_name": None, "patients": None}
    name = build_new_filename(record, "20260916", "RADIOLOGY")
    assert name == "ROUTINE_unknown_unknown_20260916.pdf", name


def test_build_new_filename_route_prefix():
    record = {
        "priority": "STAT",
        "facility_name": "Summit Ridge",
        "patients": [{"name": "Jane Doe"}],
    }
    name = build_new_filename(record, "20260916", "HVTI")
    assert name == "HVTI_STAT_Summit_Ridge_Doe_Jane_20260916.pdf", name

    name = build_new_filename(record, "20260916", "RADIOLOGY")
    assert name == "STAT_Summit_Ridge_Doe_Jane_20260916.pdf", name


def test_needs_review_rules():
    complete = {
        "is_imaging_request": True,
        "missing_info": [],
        "confidence": "high",
        "patients": [{"name": "Jane Doe"}],
        "exams": [{"exam": "CT Chest", "date": None, "group": "radiology"}],
    }
    assert compute_needs_review(complete, "Electronic", "RADIOLOGY") is False

    assert compute_needs_review({**complete, "is_imaging_request": False}) is True
    assert compute_needs_review({**complete, "missing_info": ["dob unreadable"]}) is True
    assert compute_needs_review({**complete, "confidence": "low"}) is True
    assert compute_needs_review({**complete, "patients": []}) is True
    assert compute_needs_review({**complete, "exams": []}) is True
    # delivery Unknown always needs review, even if everything else is clean
    assert compute_needs_review(complete, "UNKNOWN", "RADIOLOGY") is True
    # LEGAL is never processed here (faxed to Legal), so it never needs review
    assert compute_needs_review(complete, "UNKNOWN", "LEGAL") is False


def test_fence_stripping_and_parse():
    canned = '```json\n{"is_imaging_request": true, "priority": "STAT", "patients": []}\n```'
    data = parse_model_json(canned)
    assert data["is_imaging_request"] is True
    assert data["priority"] == "STAT"

    plain = strip_json_fences('```\n{"a": 1}\n```')
    assert json.loads(plain) == {"a": 1}

    no_fence = strip_json_fences('{"a": 1}')
    assert json.loads(no_fence) == {"a": 1}


def test_error_row_path():
    rec = make_error_record("01A182c3.PDF", "Expecting value: line 1 column 1")
    assert rec["source_file"] == "01A182c3.PDF"
    assert rec["is_imaging_request"] is False
    assert rec["confidence"] == "low"
    assert rec["missing_info"]
    # error records still need to run through the normal routing/filename/review pipeline
    route = decide_route(rec)
    assert route == "NOT_IMAGING"
    name = build_new_filename(rec, "20260916", route)
    assert name == "NOT_IMAGING_ROUTINE_unknown_unknown_20260916_01A182c3.pdf", name
    assert compute_needs_review(rec) is True


def test_match_facility():
    exact = match_facility("Harbor Point Medical Center", FACILITIES)
    assert exact["destination"] == "HPMC-7Q2X"

    fuzzy = match_facility("Lakeshore Ortho Assoc", FACILITIES)
    assert fuzzy["facility_name"] == "Lakeshore Orthopedic Associates"

    assert match_facility("Totally Unrelated Clinic Name", FACILITIES) is None
    # near-miss on a shared suffix must NOT match: this once sent a fax to the wrong facility
    assert match_facility("Washington Radiology", FACILITIES) is None
    assert match_facility("Harbor Point Medical Center - Dept. of Internal Medicine", FACILITIES)["destination"] == "HPMC-7Q2X"
    assert match_facility("RIVERBEND SURGICAL CENTER - NEUROSURGERY", FACILITIES)["facility_name"] == "Riverbend Surgical Center"
    assert match_facility("Riverside Surgical Center", FACILITIES) is None
    assert match_facility(None, FACILITIES) is None
    assert match_facility("Harbor Point Medical Center", []) is None


def test_decide_route():
    def rec(**kw):
        base = {"is_imaging_request": True, "is_legal": False, "performed_at_akron": False,
                "exams": []}
        base.update(kw)
        return base

    assert decide_route(rec(is_imaging_request=False)) == "NOT_IMAGING"
    assert decide_route(rec(is_legal=True)) == "LEGAL"
    assert decide_route(rec(performed_at_akron=True)) == "AKRON"
    assert decide_route(rec(exams=[{"exam": "Eye exam", "group": "dental_eye"}])) == "DENTAL_EYE"
    assert decide_route(rec(exams=[{"exam": "TTE", "group": "cardiac"}])) == "HVTI"
    assert decide_route(rec(exams=[{"exam": "CT Chest", "group": "radiology"},
                                    {"exam": "Echocardiogram", "group": "cardiac"}])) == "SPLIT_HVTI"
    assert decide_route(rec(exams=[{"exam": "CT Chest", "group": "radiology"}])) == "RADIOLOGY"
    # legal beats akron beats everything else
    assert decide_route(rec(is_legal=True, performed_at_akron=True)) == "LEGAL"


def test_route_note_split():
    record = {"exams": [
        {"exam": "CT Chest", "group": "radiology"},
        {"exam": "Echocardiogram", "group": "cardiac"},
        {"exam": "Nuclear stress test", "group": "cardiac"},
    ]}
    note = route_note(record, "SPLIT_HVTI")
    assert note == ("Work radiology exams here: CT Chest; email PDF to HVTI for: "
                     "Echocardiogram, Nuclear stress test"), note


def test_decide_delivery_precedence():
    facility_row = {"connection": "PowerShare", "destination": "Maplewood FHC (PowerShare)",
                     "care_everywhere": "no"}

    # ambra beats everything
    rec = {"ambra_share_code": "HPMC-7Q2X", "powershare_destination": "x",
           "recipient_email": "x@y.com", "mailing_address": "123 Main St"}
    assert decide_delivery(rec, facility_row) == ("ELECTRONIC", "Ambra", "HPMC-7Q2X")

    # powershare destination beats email/list/mail
    rec = {"powershare_destination": "willowcreek.imaging", "recipient_email": "x@y.com",
           "mailing_address": "123 Main St"}
    assert decide_delivery(rec, facility_row) == ("ELECTRONIC", "PowerShare", "willowcreek.imaging")

    # email beats list/mail
    rec = {"recipient_email": "x@y.com", "mailing_address": "123 Main St"}
    assert decide_delivery(rec, facility_row) == ("ELECTRONIC", "Email", "x@y.com")

    # list connection beats mailing address
    rec = {"mailing_address": "123 Main St"}
    assert decide_delivery(rec, facility_row) == (
        "ELECTRONIC", "PowerShare (on list)", "Maplewood FHC (PowerShare)")

    # no facility connection (or "none") + mailing address -> mailed CD
    assert decide_delivery(rec, None) == ("MAILED CD", "Mail", "123 Main St")
    none_row = {"connection": "none", "destination": "", "care_everywhere": "no"}
    assert decide_delivery(rec, none_row) == ("MAILED CD", "Mail", "123 Main St")

    # nothing at all -> unknown
    assert decide_delivery({}, None) == ("UNKNOWN", "", "")


def test_decide_send_reports():
    care_yes = {"care_everywhere": "yes"}
    care_no = {"care_everywhere": "no"}

    assert decide_send_reports({"reports_requested": False}, care_yes) == \
        (False, "facility in Epic Care Everywhere")
    assert decide_send_reports({"reports_requested": True}, care_yes) == \
        (True, "fax explicitly requested reports")
    assert decide_send_reports({"reports_requested": False}, None) == \
        (True, "facility not on connectivity list")
    assert decide_send_reports({"reports_requested": False}, care_no) == \
        (True, "facility not in Care Everywhere")


def test_image_type_derivation():
    assert modality_for_exam("CT Chest") == "CT"
    assert modality_for_exam("MRI Brain") == "MRI"
    assert modality_for_exam("X-ray left knee") == "XR"
    assert modality_for_exam("Renal Ultrasound") == "US"
    assert modality_for_exam("Screening Mammogram") == "Mammo"
    assert modality_for_exam("Coronary CTA") == "CT"
    assert modality_for_exam("Echocardiogram") == "Echo"
    assert modality_for_exam("Podiatry consult") == "Other"

    exams = [{"exam": "CT Chest"}, {"exam": "X-ray knee"}, {"exam": "MRI Brain"},
              {"exam": "CT Abdomen"}]
    assert image_type_summary(exams) == "CT; XR; MRI"


def test_last_first_and_imaging_type():
    assert last_first("Jane Doe") == "DOE, JANE"
    assert last_first("TESTPATIENT, Marcus") == "TESTPATIENT, MARCUS"
    assert last_first("Cher") == "CHER"
    assert last_first("TESTPATIENT_WILLIAM") == "WILLIAM, TESTPATIENT" or last_first("TESTPATIENT_WILLIAM") == "TESTPATIENT, WILLIAM"
    assert last_first(None) == ""

    rad = [{"exam": "CT Chest", "group": "radiology"}]
    mammo = [{"exam": "Screening Mammogram", "group": "radiology"}]
    card = [{"exam": "Echocardiogram", "group": "cardiac"}]
    assert imaging_type(rad) == "RADIOLOGY"
    assert imaging_type(mammo) == "MAMMOGRAPHY"
    assert imaging_type(rad + mammo) == "BOTH"
    assert imaging_type(card) == "CARDIAC"
    assert imaging_type(rad + card) == "RADIOLOGY + CARDIAC"
    assert imaging_type([]) == ""

    assert exam_dates({"exams": [{"date": "09/01/2026"}, {"date": None}, {"date": "09/01/2026"}]}) == "09/01/2026"
    assert exam_dates({"exams": [], "exam_date_range": {"from": "01/01/2025", "to": None}}) == "01/01/2025 to present"
    assert exam_dates({"exams": [], "exam_dates_text": "most recent"}) == "most recent"


def test_form_fill_and_worklist_row():
    record = {
        "source_file": "fax1.pdf",
        "facility_name": "Cedar Valley Family Medicine",
        "patients": [
            {"name": "Jane Doe", "dob": "01/02/1980"},
            {"name": "John Smith", "dob": "02/03/1990"},
        ],
        "exams": [
            {"exam": "CT Chest", "date": "09/01/2026", "group": "radiology"},
            {"exam": "MRI Brain", "date": None, "group": "radiology"},
        ],
        "reason_for_request": "continuity of care",
        "missing_info": ["DOB unreadable for second patient"],
        "number_of_cds": None,
    }
    ff = build_form_fill(record, None, "RADIOLOGY", "Work radiology exams here", "MAILED CD", "Mail",
                         "123 Main St", True)
    assert ff["patient"] == "DOE, JANE"
    assert ff["epic_search"] == "DOE, JANE 01/02/1980"
    assert ff["imaging_type"] == "RADIOLOGY"
    assert ff["exam_dates"] == "09/01/2026"
    assert ff["exams"] == "CT Chest; MRI Brain"
    assert ff["delivery"] == "MAILED CD"
    assert ff["mail_address"] == "123 Main St"
    assert ff["cd_copies"] == 1
    assert ff["send_to"] == ""
    assert ff["reports"] == "Y"
    assert ff["connection_lookup"] == "not on list"
    assert ff["reports_fax"] == ""  # reports wanted but no fax number on the fax
    assert ff["notes"] == ("Missing: DOB unreadable for second patient | Reports: no fax number given"
                           " | 2nd patient: SMITH, JOHN 02/03/1990")
    assert "continuity of care" not in json.dumps(ff)  # reason is never shown

    on_list = {"facility_name": "Summit Ridge Cardiology", "connection": "Ambra",
               "care_everywhere": "yes", "destination": "SRC-4K9T"}
    ff2 = build_form_fill({**record, "facility_fax": "555-0821", "facility_name": "Summit Ridge Cardiology"}, on_list, "HVTI",
                          "Forward fax to HVTI", "ELECTRONIC", "Ambra", "SRC-4K9T", False)
    assert (ff2["method"], ff2["send_to"], ff2["mail_address"], ff2["cd_copies"]) == ("Ambra", "SRC-4K9T", "", "")
    assert ff2["connection_lookup"] == "Ambra: SRC-4K9T"
    assert ff2["reports_fax"] == ""  # reports N -> no fax listed
    assert ff2["notes"].startswith("Forward fax to HVTI")

    ff3 = build_form_fill({**record, "facility_fax": "555-0734", "facility_name": "Cedar Valley Fam Med"},
                          {"facility_name": "Cedar Valley Family Medicine", "connection": "none"},
                          "RADIOLOGY", "", "UNKNOWN", "", "", True)
    assert ff3["connection_lookup"] == "on list, no electronic connection (matched as 'Cedar Valley Family Medicine', verify)"
    assert ff3["reports_fax"] == "555-0734"
    assert "Reports:" not in ff3["notes"]

    legal = build_form_fill({**record, "facility_name": "Dunmore & Associates, LLP"}, None, "LEGAL",
                            "Fax to CCF Legal. Do not process.", "MAILED CD", "Mail", "123 Main St", True)
    assert legal["facility"] == "Dunmore & Associates, LLP"
    assert legal["notes"] == "Fax to CCF Legal. Do not process."
    assert all(legal[k] == "" for k in legal if k not in ("facility", "notes")), legal

    row = to_worklist_row({**record, "form_fill": ff, "route": "RADIOLOGY", "priority": "ROUTINE",
                            "needs_review": True, "new_file": "x.pdf"})
    assert row["fax"] == "fax1.pdf"
    assert row["patient"] == "DOE, JANE"
    assert row["new_file"] == "x.pdf"


def test_apply_rules_drops_mrn_from_missing():
    rec = {"is_imaging_request": True, "confidence": "high", "facility_name": None,
           "patients": [{"name": "Doe, Jane", "dob": "01/02/1980"}],
           "exams": [{"exam": "CT Chest", "date": "09/01/2026", "group": "radiology"}],
           "mailing_address": "1 Main St",
           "missing_info": ["Medical Record Number", "MRN not given"]}
    apply_rules(rec, [])
    assert rec["missing_info"] == []
    assert rec["needs_review"] is False
    assert rec["route"] == "RADIOLOGY" and rec["delivery_type"] == "MAILED CD"


def test_dob_cross_check():
    from triage import dob_cross_check, find_dobs
    assert find_dobs("Patient Name: TESTPATIENT, LINDA DOB: 12/05/1958 MRN: 660412") == ["12/05/1958"]
    assert find_dobs("Date of Birth 4-12-1968  SS #") == ["04/12/1968"]
    assert find_dobs("D.O.B. : 1 / 2 / 1990") == ["01/02/1990"]
    assert find_dobs("Exam date 07/02/2026, no birth date here") == []
    assert find_dobs("DOB: MRN: Exam") == []  # handwritten value the OCR could not read
    assert find_dobs("") == []
    # two patients on one fax, first DOB unreadable
    assert find_dobs("Patient 1 DOB: MRN: 771002  Patient 2 DOB: 01/08/1955 MRN: 771015") == ["01/08/1955"]

    patient = lambda dob: {"patients": [{"name": "X", "dob": dob}]}
    assert dob_cross_check({**patient("12/05/1958"), "ocr_dobs": ["12/05/1958"]}) == ""
    assert dob_cross_check({**patient("12/05/1958"), "ocr_dobs": []}) == ""
    assert "conflict" in dob_cross_check({**patient("12/05/1958"), "ocr_dobs": ["12/05/1953"]})
    assert "model read none" in dob_cross_check({**patient(None), "ocr_dobs": ["12/05/1958"]})
    # OCR found only the second patient's DOB: not a conflict
    two = {"patients": [{"name": "A", "dob": "05/19/1990"}, {"name": "B", "dob": "01/08/1955"}]}
    assert dob_cross_check({**two, "ocr_dobs": ["01/08/1955"]}) == ""
    assert "conflict" in dob_cross_check({**two, "ocr_dobs": ["01/08/1956"]})

    rec = {"is_imaging_request": True, "confidence": "high", "facility_name": None,
           **patient("01/14/1923"), "ocr_dobs": ["01/19/1983"], "mailing_address": "1 Main St",
           "exams": [{"exam": "CT Chest", "date": None, "group": "radiology"}], "missing_info": []}
    apply_rules(rec, [])
    assert rec["needs_review"] is True
    assert "DOB conflict: model 01/14/1923, OCR 01/19/1983" in rec["form_fill"]["notes"]


def test_opencode_event_parsing():
    from triage import opencode_text_from_events
    stdout = (
        '{"type":"step_start","part":{"type":"step-start"}}\n'
        '{"type":"text","part":{"type":"text","text":"```json\\n{\\"priority\\": "}}\n'
        'not json noise line\n'
        '{"type":"text","part":{"type":"text","text":"\\"STAT\\"}\\n```"}}\n'
        '{"type":"step_finish","part":{"reason":"stop"}}\n'
    )
    text = opencode_text_from_events(stdout)
    assert parse_model_json(text) == {"priority": "STAT"}


def test_openai_backend_against_mock_server():
    """Spin up a fake /chat/completions, send a real fax PDF through extract_openai."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    from triage import extract_openai

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["model"] = body["model"]
            seen["images"] = sum(1 for p in body["messages"][0]["content"] if p["type"] == "image_url")
            seen["has_prompt"] = "is_imaging_request" in body["messages"][0]["content"][0]["text"]
            reply = {"choices": [{"message": {"content": '```json\n{"is_imaging_request": true, "priority": "STAT", "patients": []}\n```'}}]}
            out = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):  # quiet
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        pdf = next(iter(sorted(Path("faxes_in").glob("*.PDF"))), None)
        if pdf is None:
            print("  (skipped: no faxes_in PDFs)")
            return
        data = extract_openai(pdf, "test-model", f"http://127.0.0.1:{srv.server_port}/v1", "sk-test")
    finally:
        srv.shutdown()
    assert data["priority"] == "STAT"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["model"] == "test-model"
    assert seen["images"] >= 1 and seen["has_prompt"]


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print("OK")


if __name__ == "__main__":
    main()
