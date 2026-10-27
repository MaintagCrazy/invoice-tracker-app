"""Mocked guard tests for KSeF filing (no network, no sheet, no email). Run:
    cd backend && python tests/test_ksef_guards.py
"""
import asyncio, base64, hashlib, os, re, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["KSEF_TOKEN"] = "FAKE-TOKEN"
import httpx
httpx.get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network blocked"))
httpx.Client.send = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network blocked"))
from fastapi import HTTPException
import services.sheets_database as sdb
import services.ksef_service as ks
import services.pdf_service as ps
import routers.invoices as rinv, routers.email as remail, routers.chat as rchat, routers.ksef as rksef

HEAD = ['File Name','File #','Invoice Number','Issue Date','Due Date','Client','Description','Amount','Currency','Status','Drive File ID','Deleted At','KSeF Reference','KSeF Status','KSeF Hash']
class FakeWS:
    def __init__(self, rows): self.rows=[HEAD[:]]+[r+[""]*(15-len(r)) for r in rows]
    def get_all_records(self): return [dict(zip(self.rows[0], r)) for r in self.rows[1:]]
    def row_values(self, i): return self.rows[i-1]
    def update_cell(self, r, c, v): self.rows[r-1][c-1]=v
    def append_row(self, row): self.rows.append(list(row)+[""]*(15-len(row)))
    def delete_rows(self, i): del self.rows[i-1]
CLIENTS={1:{"id":1,"name":"Bauceram GmbH","address":"A 1","company_id":"DE306313681","email":"x@example.invalid"},
         2:{"id":2,"name":"Hillenbrand","address":"B 2","company_id":"","email":"y@example.invalid"}}
def make_db(rows):
    db = sdb.SheetsDatabaseService.__new__(sdb.SheetsDatabaseService)
    db._cache={}; db._cache_ts={}; db.db_worksheet=FakeWS(rows)
    db.get_client=lambda cid: CLIENTS.get(cid)
    db.get_client_by_name=lambda n: next((c for c in CLIENTS.values() if c["name"]==n), None)
    db._get_payments_by_invoice=lambda: {}
    db.update_invoice_drive_file_id=lambda *a: True
    for m in (rinv, remail, rchat, rksef): m.get_sheets_db=lambda db=db: db
    return db

ST={}; FILED=[]
def reset(**kw):
    EMAIL.sent.clear(); FILED.clear(); ST.clear(); ST.update(delay=0, send_exc=None, meta=[], dl=b"<xml/>"); ST.update(kw)
class Res:
    def __init__(s,n): s.ksef_number=n; s.reference_number="REF"; s.status=type("st",(),{"description":"Sukces","code":200})()
class Sess:
    def __enter__(s): return s
    def __exit__(s,*a): return False
    def send_invoice_and_wait(s, invoice_xml):
        FILED.append(invoice_xml); time.sleep(ST["delay"])
        if ST["send_exc"]: raise ST["send_exc"]
        return Res(f"7011092699-20261101-FAKE{len(FILED):04d}-00")
class _Id:
    def __init__(s, v): s.value=v; s.type="vatUe"
class _Buyer:
    def __init__(s, v): s.identifier=_Id(v)
class Meta:
    """ksef2 0.18.1 InvoiceMetadata, the fields we read"""
    def __init__(s, n, num, h, gross=100.0, buyer="DE306313681", currency="EUR"):
        s.invoice_number=n; s.ksef_number=num; s.invoice_hash=h; s.gross_amount=gross; s.buyer=_Buyer(buyer); s.currency=currency
class Page:
    def __init__(s, inv): s.invoices=inv
class Inv:
    def query_metadata_pages(s, *, filters):
        if ST.get("lookup_exc"): raise ST["lookup_exc"]
        return iter([Page(ST["meta"])])
    def download_invoice(s, ksef_number): return ST["dl"]
class Auth:
    def online_session(s, form_code): return Sess()
    invoices=Inv()
ks._auth=lambda: Auth()
class FakeEmail:
    def __init__(s): s.sent=[]
    def send_invoice(s, **k): s.sent.append(k); return [{"success":True,"recipient":r} for r in k["recipients"]]
EMAIL=FakeEmail(); remail.get_email_service=lambda: EMAIL
class FakePDF:
    def generate_pdf_bytes(s, inv, cl):
        p=ps.PDFService.__new__(ps.PDFService); p.company=ps.config.COMPANY; p.font_config=None
        return p.generate_html(inv,cl).encode()
remail.get_pdf_service=lambda: FakePDF(); rinv.get_pdf_service=lambda: FakePDF()

def row(fn, num, issue, client="Bauceram GmbH", status="draft", amount="100", extra=()):
    r=["Faktura.pdf",fn,num,issue,"26.11.2026",client,"desc",amount,"EUR",status]
    return r+list(extra)
def raises(exc, f, *a, **k):
    try: f(*a, **k)
    except exc as e: return str(e)
    raise AssertionError(f"expected {exc.__name__}")

def t1_duplicate_file_number():
    reset(); db=make_db([row(39,"02/02/2026","12.02.2026","Hillenbrand","deleted",extra=("","2026-03-01T00:00:00")), row(39,"01/03/2026","27.04.2026")])
    msg=raises(ks.KsefFilingError, remail.send_invoice_sync, 39)
    assert "appears on 2 sheet rows" in msg and not FILED and not EMAIL.sent, (msg, FILED)
    assert all(r[12]=="" and r[13]=="" for r in db.db_worksheet.rows[1:]), "no row touched"
    raises(sdb.DuplicateFileNumber, db.update_invoice, 39, {"ksef_status":"x"})
    return msg

def t2a_timeout_recovered():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")])
    from ksef2.core import exceptions as E
    ST["send_exc"]=E.KSeFInvoiceProcessingTimeoutError("REF-T", 60.0)
    ST["meta"]=[Meta("01/10/2026","7011092699-20261027-AAAAAA-BB","AAEC")]  # KSeF accepted it after all
    r=remail.send_invoice_sync(1)
    assert len(FILED)==1 and r["sent"]>0, (len(FILED), r)
    rw=db.db_worksheet.rows[1]
    assert rw[12]=="7011092699-20261027-AAAAAA-BB" and rw[14]=="AAEC", rw[12:15]
    remail.send_invoice_sync(1); assert len(FILED)==1, "no second submission"
    return rw[12:15]

def t2b_timeout_not_yet_visible():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")])
    from ksef2.core import exceptions as E
    ST["send_exc"]=E.KSeFInvoiceProcessingTimeoutError("REF-T", 60.0)
    msg=raises(ks.KsefFilingError, remail.send_invoice_sync, 1)
    assert "REF-T" in msg and not EMAIL.sent, msg
    assert db.db_worksheet.rows[1][13].startswith("W TOKU") and "REF-T" in db.db_worksheet.rows[1][13]
    ST.update(send_exc=None, meta=[Meta("01/10/2026","7011092699-20261027-CCCCCC-DD","QQ")])
    remail.send_invoice_sync(1)
    assert db.db_worksheet.rows[1][12].endswith("CCCCCC-DD") and len(FILED)==1, "recovered on retry without re-sending"

def t2c_440_uses_original():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")])
    from ksef2.core import exceptions as E
    ST["send_exc"]=E.KSeFSessionError("Invoice processing failed: REF2 (440: Duplikat faktury)")  # exactly what 0.18.1 raises
    ST["meta"]=[Meta("01/10/2026","7011092699-20261027-ORIGIN-AA","h+/=")]
    remail.send_invoice_sync(1)
    rw=db.db_worksheet.rows[1]; assert rw[12]=="7011092699-20261027-ORIGIN-AA" and rw[14]=="h-_", rw[12:15]

def t3_no_vat_id():
    reset(); db=make_db([row(5,"01/10/2026","27.10.2026","Hillenbrand")])
    msg=raises(ks.KsefFilingError, remail.send_invoice_sync, 5)
    assert "no usable VAT id" in msg and not FILED and not EMAIL.sent
    assert db.db_worksheet.rows[1][13].startswith("BLAD") and not db.db_worksheet.rows[1][12]
    raises(ValueError, ks.build_faktura, {"invoice_number":"1","amount":1,"currency":"EUR","issue_date":"27.10.2026","due_date":"27.11.2026","description":"d"}, {"name":"H","address":"x","company_id":""})
    assert ks._detect_country("DE306313681")=="DE" and ks._detect_country("7011092699")=="PL" and ks._detect_country("")is None

def t4_old_and_unreadable_dates():
    reset(); db=make_db([row(1,"01/06/2022","NOT FOUND"), row(2,"01/03/2026","31.03.2026"), row(3,"01/04/2026","01.04.2026")])
    EMAIL.sent.clear()
    remail.send_invoice_sync(1); remail.send_invoice_sync(2); assert not FILED, "old/unreadable never filed"
    remail.send_invoice_sync(3); assert len(FILED)==1 and db.db_worksheet.rows[3][12]
    assert re.search(rb"<(?:\w+:)?P_1>2026-04-01<", FILED[0])
    assert not ks.ksef_required({"issue_date":"NOT FOUND"}) and ks.parse_issue_date("garbage") is None

def t5_concurrent_no_double_submit():
    reset(delay=2); db=make_db([]); out={}
    th=threading.Thread(target=lambda: out.__setitem__("c", rinv.create_invoice(client_id=1, description="race", amount=100.0, issue_date="27.10.2026", due_date="26.11.2026")))
    th.start(); time.sleep(0.7)
    out["s"]=remail.send_invoice_sync(1); th.join()
    assert len(FILED)==1 and out["c"]["ksef_reference"] and out["s"]["sent"]>0, (len(FILED), out)
    # a failure can never overwrite the stored number
    db.update_invoice(1, {"ksef_status":"BLAD: late error"}); db.update_invoice(1, {"ksef_reference":"X"})
    assert db.db_worksheet.rows[1][12].startswith("7011092699") and db.db_worksheet.rows[1][13]=="Sukces", db.db_worksheet.rows[1][12:14]

def _filed_db():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026",extra=("","","7011092699-20261027-61CA98800003-FB","Sukces","HASH"))]); return db

def t6_delete_purge_undo():
    db=_filed_db()
    assert raises(HTTPException, rinv.delete_invoice, 1) is not None
    try: rinv.delete_invoice(1)
    except HTTPException as e: assert e.status_code==409, e.status_code
    db.db_worksheet.rows[1][9]="deleted"; db.db_worksheet.rows[1][11]="2026-01-01T00:00:00"
    assert db.purge_old_deleted_invoices(30)==0 and db.db_worksheet.rows[1][12], "filed row survives purge"
    db.db_worksheet.rows[1][9]="sent"
    class AI:
        def get_pending_action(s,c): return {"function_name":"delete_invoice","arguments":{"invoice_id":1}}
        def clear_conversation(s,c): pass
    rchat.get_ai_service=lambda: AI()
    try: asyncio.run(rchat.confirm_action("c")); raise AssertionError("undo claimed success")
    except HTTPException as e: assert e.status_code==409, e.status_code

def t7_patch_filed():
    db=_filed_db()
    try: rinv.patch_invoice(1, rinv.InvoicePatchRequest(amount=5000.0))
    except HTTPException as e: assert e.status_code==409 and "correction" in e.detail
    else: raise AssertionError("patched a filed invoice")
    class AI:
        def get_pending_action(s,c): return {"function_name":"edit_invoice","arguments":{"invoice_id":1,"new_amount":1}}
        def clear_conversation(s,c): pass
    rchat.get_ai_service=lambda: AI()
    try: asyncio.run(rchat.confirm_action("c")); raise AssertionError("chat edited filed invoice")
    except HTTPException as e: assert e.status_code==409
    assert db.db_worksheet.rows[1][7]=="100"
    rinv.patch_invoice(1, rinv.InvoicePatchRequest(status="paid"))  # status still allowed

def t8_qr_date():
    f=lambda d: ps.ksef_qr_url("7011092699", d, "H")
    assert f("1.6.2026").endswith("/01-06-2026/H") and f("2026-10-27").endswith("/27-10-2026/H") and f("27.10.2026").endswith("/27-10-2026/H")
    raises(ValueError, f, "NOT FOUND")

def t9_chat_failures_visible():
    reset(); db=make_db([]); ST["send_exc"]=RuntimeError("KSeF down")
    class AI:
        def get_pending_action(s,c): return {"function_name":"create_invoice","arguments":{"client_name":"Bauceram GmbH","amount":"100","description":"x"}}
        def clear_conversation(s,c): pass
    rchat.get_ai_service=lambda: AI()
    r=asyncio.run(rchat.confirm_action("c"))
    assert r["success"] and r["ksef_error"] and "NOT filed" in r["message"], r
    assert db.db_worksheet.rows[1][13].startswith("BLAD: KSeF down")
    class AI2(AI):
        def get_pending_action(s,c): return {"function_name":"send_invoice_email","arguments":{"invoice_id":1}}
    rchat.get_ai_service=lambda: AI2()
    r=asyncio.run(rchat.confirm_action("c")); assert r["success"] is False and "NOT emailed" in r["message"], r
    # dashboard send endpoint: loud 502, nothing mailed
    EMAIL.sent.clear()
    try: asyncio.run(remail.send_invoice(1, type("BT",(),{"add_task":lambda *a,**k:None})(), remail.SendEmailRequest(confirmed=True))); raise AssertionError("sent")
    except HTTPException as e: assert e.status_code==502 and "Email NOT sent" in e.detail and not EMAIL.sent

def t10_sent_gate():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")])
    try: rinv.mark_invoice_sent(1); raise AssertionError("marked sent unfiled")
    except HTTPException as e: assert e.status_code==409
    try: rinv.patch_invoice(1, rinv.InvoicePatchRequest(status="sent")); raise AssertionError("patched sent")
    except HTTPException as e: assert e.status_code==409
    assert db.db_worksheet.rows[1][9]=="draft"

def t11_backfill_crosscheck():
    db=_filed_db(); db.db_worksheet.rows[1][14]=""
    xml=b"<filed/>"; good=base64.b64encode(hashlib.sha256(xml).digest()).decode()
    reset(dl=xml); db.db_worksheet.rows[1][14]=""
    ST["meta"]=[Meta("01/10/2026","7011092699-20261027-61CA98800003-FB", base64.b64encode(hashlib.sha256(b"other").digest()).decode())]
    r=ks.backfill_ksef_hashes(db); assert "!=" in r[0]["error"] and db.db_worksheet.rows[1][14]=="", r
    ST["meta"]=[]; r=ks.backfill_ksef_hashes(db); assert "cross-check" in r[0]["error"] and db.db_worksheet.rows[1][14]==""
    ST["meta"]=[Meta("01/10/2026","7011092699-20261027-61CA98800003-FB", good)]
    r=ks.backfill_ksef_hashes(db); assert r[0]["saved"] and db.db_worksheet.rows[1][14]==ks.xml_hash_b64url(xml)
    ks._auth=lambda: (_ for _ in ()).throw(RuntimeError("login refused")); db.db_worksheet.rows[1][14]=""
    r=ks.backfill_ksef_hashes(db); assert "login failed" in r[0]["error"]
    ks._auth=lambda: Auth()

def t12_lookup_failure_is_loud_not_notfound():
    from ksef2.core import exceptions as E
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")])
    ST["send_exc"]=E.KSeFInvoiceProcessingTimeoutError("REF-T", 60.0); ST["lookup_exc"]=ImportError("cannot import name InvoicesFilter")
    msg=raises(ks.KsefFilingError, remail.send_invoice_sync, 1)
    assert "lookup failed" in msg and "ImportError" in msg and not EMAIL.sent, msg
    assert db.db_worksheet.rows[1][13].startswith("BLAD: KSeF lookup failed")
    # the real 0.18.1 import path + filter construction must work (no network): lookup with no hit returns None, not an error
    ST.update(lookup_exc=None, meta=[]); inv=db.get_invoice(1)
    assert ks._metadata(Auth(), inv, inv["client"]) is None
    db2=_filed_db(); db2.db_worksheet.rows[1][14]=""; ST["lookup_exc"]=AttributeError("no query_metadata_pages")
    r=ks.backfill_ksef_hashes(db2); assert "lookup failed" in r[0]["error"] and db2.db_worksheet.rows[1][14]==""

def t13_record_must_match_before_adoption():
    from ksef2.core import exceptions as E
    for bad in (dict(gross=999.0), dict(buyer="DE111111111"), dict(currency="PLN")):
        reset(); db=make_db([row(1,"05/10/2026","27.10.2026")])
        ST["send_exc"]=E.KSeFSessionError("Invoice processing failed: R (440: Duplikat faktury)")
        ST["meta"]=[Meta("05/10/2026","7011092699-20261020-OTHER-01","H", **bad)]
        msg=raises(ks.KsefFilingError, remail.send_invoice_sync, 1)
        assert "not adopted" in msg and not db.db_worksheet.rows[1][12] and not EMAIL.sent, (bad, msg)
    reset(); db=make_db([row(1,"05/10/2026","27.10.2026")])  # 440 and KSeF has nothing matching: refuse
    ST["send_exc"]=E.KSeFSessionError("Invoice processing failed: R (440: Duplikat faktury)")
    assert "check it in KSeF by hand" in raises(ks.KsefFilingError, remail.send_invoice_sync, 1)

def t14_file_number_never_reused():
    reset(); db=make_db([row(44,"01/10/2026","27.10.2026",status="deleted",extra=("","2026-01-01T00:00:00"))])
    assert db.get_next_file_number()==45
    db.db_worksheet.get_all_records=lambda: (_ for _ in ()).throw(RuntimeError("429 quota"))
    raises(RuntimeError, db.get_next_file_number)

def t15_amount_must_be_positive():
    reset(); db=make_db([])
    for a in (0.0,-5.0):
        raises(ValueError, db.create_invoice, client_id=1, description="d", amount=a)
        try: rinv.create_invoice(client_id=1, description="d", amount=a); raise AssertionError("created")
        except HTTPException as e: assert e.status_code==400
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026",amount="0")])
    assert "greater than 0" in raises(ks.KsefFilingError, remail.send_invoice_sync, 1) and not FILED

def t16_unknown_currency_refused():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")]); db.db_worksheet.rows[1][8]="SEK"
    assert "not supported" in raises(ks.KsefFilingError, remail.send_invoice_sync, 1) and not FILED
    raises(ValueError, ks.build_faktura, {"invoice_number":"1","amount":1,"currency":"SEK","issue_date":"27.10.2026","due_date":"27.11.2026","description":"d"}, CLIENTS[1])

def t17_unreadable_date_after_cutoff_refused():
    for d in ("garbage","","32.13.2026"):
        reset(); db=make_db([row(1,"05/10/2026",d)])
        assert ks.ksef_required(db.get_invoice(1))
        msg=raises(ks.KsefFilingError, remail.send_invoice_sync, 1)
        assert "not readable" in msg and not FILED and not EMAIL.sent and db.db_worksheet.rows[1][13].startswith("BLAD"), msg
    for d in ("27-10-2026","27.10.26","2026/10/27","27.10.2026 "):
        assert ks.parse_issue_date(d)==ks.parse_issue_date("27.10.2026"), d
    reset(); make_db([row(1,"01/06/2022","NOT FOUND")]); remail.send_invoice_sync(1); assert not FILED and EMAIL.sent  # legacy still goes out

def t18_stale_copy_never_used():
    reset(); db=make_db([row(1,"01/10/2026","27.10.2026")]); stale=db.get_invoice(1)
    ks.file_invoice_in_ksef(db, stale, stale["client"]); assert len(FILED)==1
    db._cache_invalidate(); db._get_payments_by_invoice=lambda: (_ for _ in ()).throw(RuntimeError("429 quota"))
    assert "could not re-read" in raises(ks.KsefFilingError, ks.file_invoice_in_ksef, db, stale, stale["client"]) and len(FILED)==1

def t20_number_printed_without_hash():
    p=ps.PDFService.__new__(ps.PDFService); p.company=ps.config.COMPANY; p.font_config=None
    inv={"invoice_number":"01/10/2026","description":"d","amount":1,"currency":"EUR","issue_date":"27.10.2026","due_date":"26.11.2026","ksef_reference":"7011092699-20261027-61CA98800003-FB","ksef_hash":""}
    h=p.generate_html(inv,CLIENTS[1]); assert "61CA98800003" in h and "data:image/png" not in h
    inv["ksef_hash"]="H"; assert "data:image/png" in p.generate_html(inv,CLIENTS[1])

def t19_create_lock_distinct_file_numbers():
    reset(); db=make_db([]); orig=db.get_next_file_number
    def slow(): n=orig(); time.sleep(0.4); return n
    db.get_next_file_number=slow; out=[]
    ths=[threading.Thread(target=lambda: out.append(db.create_invoice(client_id=1, description="d", amount=10.0, issue_date="27.10.2026", due_date="26.11.2026")["file_number"])) for _ in range(2)]
    [t.start() for t in ths]; [t.join() for t in ths]
    assert sorted(out)==[1,2], out

if __name__=="__main__":
    for n,f in sorted((n,f) for n,f in globals().items() if n.startswith("t") and n[1].isdigit()):
        try: out=f(); print("PASS",n, (out or ""))
        except Exception as e:
            import traceback; print("FAIL",n); traceback.print_exc()
