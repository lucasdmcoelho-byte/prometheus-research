import zipfile

from prometheus.b3_isin_registry import parse_isin_registry_zip


def test_parse_official_isin_registry(tmp_path):
    path = tmp_path / "isinp.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("EMISSOR.TXT", '"CURY","CURY CONSTRUTORA","08797760000183","20200817"\r\n')
        row = [""] * 45
        row[0], row[1], row[2], row[3], row[4], row[5] = "20260814", "N", "BRCURYACNOR3", "CURY", "ESVUFR", "ACOES NOMINATIVAS"
        row[20], row[21], row[22], row[42], row[44] = "ACN", "E", "OR", "A", "B3"
        import csv, io
        stream = io.StringIO(); csv.writer(stream, lineterminator="\r\n").writerow(row)
        archive.writestr("NUMERACA.TXT", stream.getvalue())
    registry = parse_isin_registry_zip(path)
    assert registry.issuers["CURY"].cnpj == "08797760000183"
    assert registry.securities["BRCURYACNOR3"].category == "E"
    assert len(registry.source_sha256) == 64
