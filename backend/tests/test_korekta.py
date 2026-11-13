"""Correction invoices (korekta, FA(3) RodzajFaktury KOR): mocked tests, no network, no sheet,
no KSeF, no email. Every rendered XML is validated against the FA(3) XSD shipped in ksef2. Run:
    cd backend && python tests/test_korekta.py
"""
import os, re, sys, threading, time
sys.path.insert(0, os.path.dirname(__file__))
import test_ksef_guards as g  # its module setup blocks the network and fakes KSeF, PDF and email
from test_ksef_guards import HEAD, CLIENTS, ST, FILED, EMAIL, Meta, make_db, reset, raises
from fastapi import HTTPException
import services.sheets_database as sdb
import services.ksef_service as ks
import services.correction_service as cs
import routers.invoices as rinv, routers.email as remail, routers.ksef as rksef

KER = {"id": 3, "name": "Keramint B.V.", "address": "Minister Bongaertsstraat 135, 6042 CK Roermond, Niederlande",
       "company_id": "NL851296518B01", "email": "k@example.invalid"}
PLC = {"id": 4, "name": "Polska Sp. z o.o.", "address": "Warszawa", "company_id": "5260250274", "email": "p@example.invalid"}
CLIENTS[3] = KER; CLIENTS[4] = PLC
KSEF45 = "7011092699-20261104-60B126800004-C7"


class WideWS:
    """A Database tab that grows like a real one (row_values trims, columns can be added)."""
    def __init__(self, rows, cols=15):
        self.rows = [HEAD[:]] + [list(r) for r in rows]
        self.col_count = cols
        self.writes = []
    def _w(self): return max(len(r) for r in self.rows)
    def get_all_records(self):
        w = self._w(); head = self.rows[0] + [""] * (w - len(self.rows[0]))
        return [dict(zip(head, r + [""] * (w - len(r)))) for r in self.rows[1:]]
    def row_values(self, i):
        r = list(self.rows[i - 1])
        while r and r[-1] == "": r.pop()
        return r
    def update_cell(self, r, c, v):
        assert c <= self.col_count, f"exceeds grid limits: column {c} > {self.col_count}"
        self.writes.append(("update_cell", r, c, v))
        row = self.rows[r - 1]
        row.extend([""] * (c - len(row)))
        row[c - 1] = v
    def add_cols(self, n): self.col_count += n
    def append_row(self, row):
        assert len(row) <= self.col_count, "append wider than grid"
        self.writes.append(("append_row", list(row))); self.rows.append(list(row))
    def delete_rows(self, i): del self.rows[i - 1]


def original(fn=45, num="01/11/2026", client="Keramint B.V.", amount=17600.0, ksef=KSEF45, status="sent", desc="Bonus Baustelle Steuercampus München"):
    return ["Faktura %d.pdf" % fn, fn, num, "04.11.2026", "04.12.2026", client, desc, amount, "EUR", status, "", "", ksef, "Sukces" if ksef else "", ""]


def kdb(rows, cols=15):
    reset(); db = make_db([]); db.db_worksheet = WideWS(rows, cols); db._cache_invalidate(); return db


def xml_of(b): return b.decode() if isinstance(b, bytes) else b
def tag(x, name): return re.findall(rf"<(?:\w+:)?{name}>([^<]*)<", xml_of(x))


def k01_xml_for_invoice_45():
    db = kdb([original()])
    plan = cs.plan_correction(db, 45, "14080.00", issue_date="13.11.2026")
    x = ks.render_faktura_xml(plan, KER)
    assert ks.validate_fa3_xml(x) == [], ks.validate_fa3_xml(x)
    assert tag(x, "RodzajFaktury") == ["KOR"] and tag(x, "P_2") == ["KOR/01/11/2026"], tag(x, "P_2")
    assert tag(x, "P_15") == ["-3520.00"] and tag(x, "P_13_8") == ["-3520.00"]
    assert tag(x, "P_1") == ["2026-11-13"] and tag(x, "P_6") == ["2026-11-04"], "P_6 keeps the original service date"
    assert tag(x, "DataWystFaKorygowanej") == ["2026-11-04"] and tag(x, "NrFaKorygowanej") == ["01/11/2026"]
    assert tag(x, "NrKSeF") == ["1"] and tag(x, "NrKSeFFaKorygowanej") == [KSEF45]
    assert tag(x, "TypKorekty") == ["2"] and tag(x, "PrzyczynaKorekty") == ["Zmiana wartości usługi"]
    assert tag(x, "NrWierszaFa") == ["1", "2"] and tag(x, "P_11") == ["17600.00", "14080.00"] and tag(x, "StanPrzed") == ["1"]
    assert tag(x, "P_12") == ["np I", "np I"] and tag(x, "P_18") == ["1"] and tag(x, "P_17") == ["2"]
    assert tag(x, "KodUE") == ["NL"] and tag(x, "NrVatUE") == ["851296518B01"] and tag(x, "FormaPlatnosci") == ["6"]
    assert tag(x, "Termin") == ["2026-12-04"] and tag(x, "P_7") == ["Bonus Baustelle Steuercampus München"] * 2
    assert "StanPrzed" in xml_of(x).split("NrWierszaFa>2")[0], "StanPrzed sits on the before row"
    return "XSD valid, P_15 -3520.00"


def k02_preview_writes_nothing_files_nothing():
    db = kdb([original()])
    before = [list(r) for r in db.db_worksheet.rows]
    r = rinv.preview_correction(45, rinv.CorrectionRequest(new_amount="14080"))
    assert r["xsd_valid"] and r["correction_number"] == "KOR/01/11/2026" and r["difference"] == -3520.0, r["xsd_errors"]
    assert r["amount_before"] == 17600.0 and r["amount_after"] == 14080.0 and r["original"]["ksef_reference"] == KSEF45
    assert "FAKTURA KORYGUJACA" in r["html"] and "RAZEM PO KOREKCIE" in r["html"] and "EUR 14,080.00" in r["html"]
    assert not db.db_worksheet.writes and db.db_worksheet.rows == before and not FILED


def k03_create_needs_confirmed():
    db = kdb([original()])
    for body in (rinv.CorrectionRequest(new_amount="14080"), rinv.CorrectionRequest(new_amount="14080", confirmed=False)):
        try: rinv.create_correction(45, body); raise AssertionError("created without confirmed")
        except HTTPException as e: assert e.status_code == 400 and "confirmed" in e.detail
    assert not db.db_worksheet.writes and not FILED


def k04_create_files_and_dashboard_is_14080():
    db = kdb([original(), original(46, "02/11/2026", "Bauceram GmbH", 1000.0, "7011092699-20261105-61CA98800003-FB")])
    orig_row = list(db.db_worksheet.rows[1])
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080.00", confirmed=True))
    assert r["filed"] and r["invoice_number"] == "KOR/01/11/2026" and r["ksef_reference"].startswith("7011092699-"), r
    assert len(FILED) == 1 and ks.validate_fa3_xml(FILED[0]) == [] and tag(FILED[0], "RodzajFaktury") == ["KOR"]
    head = db.db_worksheet.rows[0]
    assert head[15:18] == ["Corrects File #", "Correction Reason", "Correction Type"], head
    new = db.db_worksheet.rows[-1]
    assert new[1] == 47 and new[2] == "KOR/01/11/2026" and new[7] == -3520.0 and new[8] == "EUR" and new[15] == 45 and new[17] == 2, new
    assert new[3] == cs._today_pl() and new[4] == "04.12.2026" and new[5] == "Keramint B.V." and new[6] == orig_row[6]
    assert new[12] == r["ksef_reference"] and new[13] == "Sukces"
    assert db.db_worksheet.rows[1] == orig_row, "original row untouched"
    db._cache_invalidate()
    st = db.get_stats()
    assert round(st["due_by_client"]["Keramint B.V."], 2) == 14080.0 and round(st["total_by_client"]["Keramint B.V."], 2) == 14080.0, st
    o, c = db.get_invoice(45), db.get_invoice(47)
    assert o["corrected_amount"] == 14080.0 and o["amount_due"] == 14080.0 and o["amount"] == 17600.0 and o["corrections"][0]["invoice_number"] == "KOR/01/11/2026"
    assert c["amount_due"] == 0 and c["payment_status"] == "correction" and c["correction"]["amount_before"] == 17600.0
    assert [i["file_number"] for i in db.get_unpaid_invoices_for_client(3)] == [45]
    assert "exceeds remaining due" in raises(ValueError, db.create_payment, 45, 14080.01)
    return st["due_by_client"]


def k05_refusals():
    rows = [original(), original(46, "02/11/2026", "Keramint B.V.", 500.0, ""),  # 46 not filed
            original(48, "03/11/2026", "Keramint B.V.", 900.0, "7011092699-20261106-61CA98800003-AB", status="deleted")]
    db = kdb(rows)
    def code(fid, **kw):
        try: rinv.preview_correction(fid, rinv.CorrectionRequest(**kw)); return 200
        except HTTPException as e: return e.status_code, e.detail
    assert code(46, new_amount="400")[0] == 409 and "no KSeF number" in code(46, new_amount="400")[1]
    assert code(45, new_amount="17600")[0] == 400, "zero difference"
    assert code(45, new_amount="-1")[0] == 400, "negative new total"
    assert code(45, new_amount="14080.001")[0] == 400, "more than 2 decimals"
    assert code(45, new_amount="14080", reason="x" * 257)[0] == 400
    assert code(45, new_amount="14080", correction_type=3)[0] == 400
    assert code(999, new_amount="1")[0] == 404 and code(48, new_amount="1")[0] == 404, "missing / deleted original"
    assert code(45, new_amount="0") == 200, "a correction to zero is allowed"
    # a correction cannot itself be corrected
    rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True)); db._cache_invalidate()
    st, d = code(49, new_amount="1")
    assert st == 409 and "itself a correction" in d, d
    assert not [w for w in db.db_worksheet.writes if w[0] == "append_row" and w[1][2] != "KOR/01/11/2026"]


def k06_second_correction_chains_and_numbers():
    db = kdb([original()])
    rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True)); db._cache_invalidate()
    p = rinv.preview_correction(45, rinv.CorrectionRequest(new_amount="15000"))
    assert p["correction_number"] == "KOR/01/11/2026/2" and p["amount_before"] == 14080.0 and p["difference"] == 920.0, p
    x = p["xml"]
    assert p["xsd_valid"] and tag(x, "P_15") == ["920.00"] and tag(x, "P_11") == ["14080.00", "15000.00"]
    assert tag(x, "NrFaKorygowanej") == ["01/11/2026"], "DaneFaKorygowanej names the original (pierwotna) invoice"
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="15000", confirmed=True)); db._cache_invalidate()
    assert r["filed"] and db.get_invoice(45)["corrected_amount"] == 15000.0
    assert round(db.get_stats()["due_by_client"]["Keramint B.V."], 2) == 15000.0


def k07_polish_buyer_gross_split():
    db = kdb([original(50, "05/11/2026", "Polska Sp. z o.o.", 1230.0, "7011092699-20261104-61CA98800003-CD", desc="Usluga")])
    p = rinv.preview_correction(50, rinv.CorrectionRequest(new_amount="615"))
    x = p["xml"]
    assert p["xsd_valid"], p["xsd_errors"]
    assert tag(x, "P_13_1") == ["-500.00"] and tag(x, "P_14_1") == ["-115.00"] and tag(x, "P_15") == ["-615.00"], (tag(x, "P_13_1"), tag(x, "P_14_1"))
    assert tag(x, "P_11") == ["1000.00", "500.00"] and tag(x, "P_11Vat") == ["230.00", "115.00"] and tag(x, "P_12") == ["23", "23"]
    assert tag(x, "NIP")[-1] == "5260250274" and tag(x, "P_18") == ["2"]


def k08_correction_row_locked_restore_refused_delete_drops():
    db = kdb([original()])
    ST["send_exc"] = RuntimeError("KSeF down")
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True))
    assert not r["filed"] and "KSeF down" in r["ksef_error"] and db.db_worksheet.rows[-1][13].startswith("BLAD"), r.get("ksef_error")
    db._cache_invalidate()
    for upd in ({"amount": 1.0}, {"description": "x"}):
        try: rinv.patch_invoice(r["id"], rinv.InvoicePatchRequest(**upd)); raise AssertionError("edited a correction")
        except HTTPException as e: assert e.status_code == 409 and "correction" in e.detail
    try: rinv.preview_correction(45, rinv.CorrectionRequest(new_amount="10000")); raise AssertionError("second while first unfiled")
    except HTTPException as e: assert e.status_code == 409 and "not filed in KSeF yet" in e.detail
    rinv.delete_invoice(r["id"]); db._cache_invalidate()
    assert db.get_invoice(45).get("corrected_amount") is None and db.get_invoice(45)["amount_due"] == 17600.0, "deleted correction changes nothing"
    try: rinv.restore_invoice(r["id"]); raise AssertionError("restored a correction")
    except HTTPException as e: assert e.status_code == 409
    ST["send_exc"] = None
    p = rinv.preview_correction(45, rinv.CorrectionRequest(new_amount="14080"))
    assert p["correction_number"] == "KOR/01/11/2026/2", "a deleted correction's number is never reused"


def k09_failed_filing_is_retried_and_broken_link_refused():
    db = kdb([original()])
    ST["send_exc"] = RuntimeError("KSeF down")
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True))
    ST["send_exc"] = None; db._cache_invalidate()
    out = rksef.submit_to_ksef(r["id"], rksef.KsefSubmitRequest(confirmed=True))
    assert out["ksef_number"] and len(FILED) == 2 and tag(FILED[-1], "RodzajFaktury") == ["KOR"] and ks.validate_fa3_xml(FILED[-1]) == []
    db2 = kdb([original(), ["Faktura 47.pdf", 47, "KOR/X", "13.11.2026", "04.12.2026", "Keramint B.V.", "d", -5.0, "EUR", "draft", "", "", "", "", "", 999, "r", 2]])
    db2.db_worksheet.rows[0] += ["Corrects File #", "Correction Reason", "Correction Type"]; db2._cache_invalidate()
    inv = db2.get_invoice(47)
    assert "not in the sheet" in inv["correction"]["error"]
    msg = raises(ks.KsefFilingError, ks.file_invoice_in_ksef, db2, inv, KER)
    assert "not in the sheet" in msg and not FILED, "a correction with a broken link is never sent"
    assert db2.db_worksheet.rows[2][13].startswith("BLAD"), db2.db_worksheet.rows[2][13]


def k10_pdf_filed_correction_and_email():
    db = kdb([original()])
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True)); db._cache_invalidate()
    db.update_invoice(r["id"], {"ksef_hash": "HASH_URL"}); db._cache_invalidate()
    html = rinv.download_invoice_pdf(r["id"]).body.decode()
    assert "FAKTURA KORYGUJACA" in html and "KOR/01/11/2026" in html and KSEF45 in html and r["ksef_reference"] in html
    assert "EUR 17,600.00" in html and "EUR 14,080.00" in html and "EUR -3,520.00" in html and "data:image/png" in html
    remail.send_invoice_sync(r["id"])
    sent = EMAIL.sent[-1]
    assert "FAKTURA KORYGUJACA" in sent["pdf_bytes"].decode() and len(FILED) == 1, "emailing a filed correction never re-files"
    plain = rinv.download_invoice_pdf(45).body.decode()
    assert "FAKTURA KORYGUJACA" not in plain and "RAZEM DO ZAPLATY" in plain, "the original keeps its own PDF"


def k11_timeout_recovery_adopts_negative_record():
    from ksef2.core import exceptions as E
    db = kdb([original()])
    ST["send_exc"] = E.KSeFSessionError("Invoice processing failed: R (440: Duplikat faktury)")
    ST["meta"] = [Meta("KOR/01/11/2026", "7011092699-20261113-AAAAAA-BB", "h+/=", gross=-3520.0, buyer="NL851296518B01")]
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True))
    assert r["filed"] and r["ksef_reference"] == "7011092699-20261113-AAAAAA-BB", r.get("ksef_error")
    db = kdb([original()]); ST["send_exc"] = E.KSeFSessionError("Invoice processing failed: R (440: Duplikat faktury)")
    ST["meta"] = [Meta("KOR/01/11/2026", "7011092699-20261113-CCCCCC-DD", "h", gross=3520.0, buyer="NL851296518B01")]
    r = rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True))
    assert not r["filed"] and "not adopted" in r["ksef_error"], "a KSeF record with another amount is never adopted"


def k12_concurrent_creates_one_row():
    db = kdb([original()]); ST["delay"] = 0.5; out = []
    def go():
        try: out.append(rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True))["invoice_number"])
        except HTTPException as e: out.append(e.status_code)
    ths = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ths]; [t.join() for t in ths]
    appended = [w for w in db.db_worksheet.writes if w[0] == "append_row"]
    assert len(appended) == 1 and sorted(map(str, out)) == ["409", "KOR/01/11/2026"], (out, len(appended))


def k13_grid_widened_and_layout_checked():
    db = kdb([original()], cols=15)
    rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True))
    assert db.db_worksheet.col_count >= 18 and db.db_worksheet.rows[0][15] == "Corrects File #"
    db = kdb([original()]); db.db_worksheet.rows[0][7] = "Betrag"
    try: rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True)); raise AssertionError("wrote into a changed layout")
    except HTTPException as e: assert e.status_code == 500 and "layout" in e.detail
    assert not [w for w in db.db_worksheet.writes if w[0] == "append_row"] and not FILED


def k14_xsd_gate_before_save_and_before_send():
    bad = "7011092699-2026-BAD"  # not a KSeF number: NrKSeFFaKorygowanej fails the XSD pattern
    db = kdb([original(ksef=bad)])
    p = rinv.preview_correction(45, rinv.CorrectionRequest(new_amount="14080"))
    assert p["xsd_valid"] is False and any("NrKSeFFaKorygowanej" in e for e in p["xsd_errors"]), p["xsd_errors"]
    try: rinv.create_correction(45, rinv.CorrectionRequest(new_amount="14080", confirmed=True)); raise AssertionError("saved an XSD-invalid correction")
    except HTTPException as e: assert e.status_code == 422 and "XSD" in e.detail, e.detail
    assert not [w for w in db.db_worksheet.writes if w[0] == "append_row"] and not FILED
    # a stored correction whose XML fails the XSD (row written by hand / older data) is never sent
    db = kdb([original(ksef=bad), ["Faktura 46.pdf", 46, "KOR/01/11/2026", "13.11.2026", "04.12.2026", "Keramint B.V.",
                                   "Bonus Baustelle Steuercampus München", -3520.0, "EUR", "draft", "", "", "", "", "", 45, "r", 2]])
    db.db_worksheet.rows[0] += ["Corrects File #", "Correction Reason", "Correction Type"]; db._cache_invalidate()
    msg = raises(ks.KsefFilingError, ks.file_invoice_in_ksef, db, db.get_invoice(46), KER)
    assert "XSD" in msg and not FILED and db.db_worksheet.rows[2][13].startswith("BLAD"), msg
    assert ks.validate_fa3_xml(b"<not-faktura/>") and ks.validate_fa3_xml(b"\xff") , "garbage is never valid"


if __name__ == "__main__":
    failed = 0
    for n, f in sorted((n, f) for n, f in globals().items() if re.match(r"k\d\d_", n)):
        try: out = f(); print("PASS", n, (out or ""))
        except Exception:
            failed += 1
            import traceback; print("FAIL", n); traceback.print_exc()
    print(f"{'ALL PASS' if not failed else str(failed) + ' FAILED'}")
    sys.exit(1 if failed else 0)
