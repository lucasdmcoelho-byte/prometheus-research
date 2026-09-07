import io
import zipfile

import pytest

from prometheus.b3_instruments import audit_reviewed_tickers, parse_bvbg028_zip


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:bvmf.100.02.xsd">
 <RptParams><RptDtAndTm><Dt>2026-08-14</Dt></RptDtAndTm></RptParams>
 <InstrmInf><EqtyInf><ISIN>BRCURYACNOR3</ISIN><SpcfctnCd>ON</SpcfctnCd>
  <CrpnNm>CURY CONSTRUTORA E INCORPORADORA S.A.</CrpnNm><TckrSymb>CURY3</TckrSymb>
 </EqtyInf></InstrmInf>
</Document>'''


def _archive(path, xml=XML):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BVBG.028.02_20260814.xml", xml)


def test_parse_bvbg028_preserves_official_identity_and_provenance(tmp_path):
    path = tmp_path / "IN260814.zip"
    _archive(path)
    snapshot = parse_bvbg028_zip(path)
    assert snapshot.reference_date == "2026-08-14"
    assert len(snapshot.source_sha256) == 64
    assert snapshot.equities()[0].ticker == "CURY3"
    assert snapshot.equities()[0].isin == "BRCURYACNOR3"


def test_b3_audit_rejects_ticker_name_or_isin_mismatch(tmp_path):
    path = tmp_path / "IN260814.zip"
    _archive(path)
    snapshot = parse_bvbg028_zip(path)
    ok = audit_reviewed_tickers(snapshot, [{"ticker": "CURY3", "b3_corporation_name": "CURY CONSTRUTORA E INCORPORADORA S.A.", "isin": "BRCURYACNOR3"}])
    assert ok["status"] == "PASS"
    bad = audit_reviewed_tickers(snapshot, [{"ticker": "CURY3", "isin": "BRWRONG00000"}, {"ticker": "XXXX3"}])
    assert bad["status"] == "FAIL"
    assert bad["failures"][0]["reasons"] == ["ISIN_MISMATCH"]
    assert bad["failures"][1]["reasons"] == ["TICKER_NOT_IN_B3_SNAPSHOT"]


def test_bvbg028_rejects_archive_without_xml(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "x")
    with pytest.raises(ValueError, match="no XML"):
        parse_bvbg028_zip(path)


def test_parse_nested_download_wrapper_and_reject_mixed_dates(tmp_path):
    inner_bytes = io.BytesIO()
    with zipfile.ZipFile(inner_bytes, "w") as inner:
        inner.writestr("part1.xml", XML)
    wrapper = tmp_path / "pesquisa-pregao.zip"
    with zipfile.ZipFile(wrapper, "w") as outer:
        outer.writestr("IN260814.zip", inner_bytes.getvalue())
    assert parse_bvbg028_zip(wrapper).equities()[0].ticker == "CURY3"

    mixed = XML.replace(b"2026-08-14", b"2026-08-13")
    path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.xml", XML)
        archive.writestr("two.xml", mixed)
    with pytest.raises(ValueError, match="mixes reference dates"):
        parse_bvbg028_zip(path)
