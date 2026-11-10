"""Testes de integração com os PDFs reais em app/data/raw/.

São pulados automaticamente se os PDFs não estiverem presentes (eles não são
versionados no git).
"""

import json
import re

import pytest

pymupdf = pytest.importorskip("pymupdf")

from app.ingestion import loader  # noqa: E402
from app.ingestion.diagnostic import gerar_relatorio  # noqa: E402

PDF_2024 = loader.PASTA_RAW / "SEI_04030_00001001_2024_23 (2).pdf"
PDF_2025 = loader.PASTA_RAW / "SEI_04030_00001179_2025_55 (2).pdf"

precisa_dos_pdfs = pytest.mark.skipif(
    not (PDF_2024.exists() and PDF_2025.exists()), reason="PDFs reais não estão em app/data/raw/"
)


@pytest.fixture(scope="module")
def r2024():
    return loader.processar_pdf(PDF_2024)


@pytest.fixture(scope="module")
def r2025():
    return loader.processar_pdf(PDF_2025)


def _paginas(resultado):
    return [p for d in resultado["documentos"] for p in d["paginas"]]


def _documento_da_pagina(resultado, pagina):
    return next(d for d in resultado["documentos"] if any(p["pagina"] == pagina for p in d["paginas"]))


@precisa_dos_pdfs
@pytest.mark.parametrize("fixture, total, documentos", [("r2024", 61, 19), ("r2025", 212, 30)])
def test_nenhuma_pagina_perdida_e_documentos_contados(request, fixture, total, documentos):
    resultado = request.getfixturevalue(fixture)
    paginas = [p["pagina"] for p in _paginas(resultado)]
    assert resultado["total_paginas"] == total
    assert paginas == list(range(1, total + 1))  # todas, em ordem, sem duplicatas
    assert len(resultado["documentos"]) == documentos


@precisa_dos_pdfs
def test_processo_sei(r2024, r2025):
    assert r2024["processo_sei"] == "04030-00001001/2024-23"
    assert r2025["processo_sei"] == "04030-00001179/2025-55"
    assert r2024["avisos"] == [] and r2025["avisos"] == []


@precisa_dos_pdfs
def test_paginas_pertencem_ao_documento_certo(r2024):
    doc = _documento_da_pagina(r2024, 38)
    assert doc["documento_sei_id"] == "142739020"
    assert doc["rotulo"] == "Memorando 131"
    assert (doc["pagina_inicio"], doc["pagina_fim"]) == (37, 38)
    assert doc["paginas"][1]["pagina_no_documento"] == 2


@precisa_dos_pdfs
def test_documentos_com_mesmo_rotulo_nao_se_misturam(r2024):
    memorandos_11 = [d for d in r2024["documentos"] if d["rotulo"] == "Memorando 11"]
    assert len(memorandos_11) == 2
    assert {d["documento_sei_id"] for d in memorandos_11} == {"142928248", "194638970"}
    assert {d["numero_documento"] for d in memorandos_11} == {
        "11/2024 - UNDF/REIT/SECEX",
        "11/2026 - UNDF/REIT/CEINTER",
    }


@precisa_dos_pdfs
def test_numeros_citados_nao_contaminam_outros_documentos(r2025):
    consepe = next(d for d in r2025["documentos"] if d["rotulo"] == "Despacho CONSEPE")
    assert consepe["numero_documento"] is None
    numeros = [d["numero_documento"] for d in r2025["documentos"] if d["numero_documento"]]
    assert not any("500/2024" in n or "FAPDF" in n for n in numeros)


@precisa_dos_pdfs
def test_metadados_obrigatorios(r2024, r2025):
    for resultado in (r2024, r2025):
        for doc in resultado["documentos"]:
            assert re.fullmatch(r"\d{6,10}", doc["documento_sei_id"])
            assert doc["processo_sei"] == resultado["processo_sei"]
            assert doc["tipo_documento"]
            for pag in doc["paginas"]:
                assert set(pag) >= {"pagina", "pagina_no_documento", "texto_bruto", "texto_limpo", "flags"}


@precisa_dos_pdfs
def test_texto_limpo_sem_caracteres_invalidos_nem_moldura(r2024, r2025):
    for pag in _paginas(r2024) + _paginas(r2025):
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f�ﬀ-ﬆ]", pag["texto_limpo"])
        assert "/ pg." not in pag["texto_limpo"]
        assert "Código Verificador" not in pag["texto_limpo"]


@precisa_dos_pdfs
def test_glifos_do_edital_reparados(r2024):
    edital = next(d for d in r2024["documentos"] if d["documento_sei_id"] == "140334392")
    texto = "\n".join(p["texto_limpo"] for p in edital["paginas"])
    assert "Incentivar e apoiar a pesquisa científica" in texto
    assert "Incenvar" not in texto
    assert all("glifos_reparados" in p["flags"] for p in edital["paginas"])


@precisa_dos_pdfs
def test_relatorio_sem_paginas_faltando(r2024, r2025):
    relatorio = gerar_relatorio([r2024, r2025], [])
    assert relatorio["totais"]["paginas"] == 273
    assert relatorio["totais"]["documentos"] == 49
    for arquivo in relatorio["arquivos"]:
        assert arquivo["paginas_faltando"] == []
        assert arquivo["paginas_duplicadas"] == []


# --------------------------------------------------------------------------
# Tratamento de erros (não depende dos PDFs reais)
# --------------------------------------------------------------------------


def _pdf_valido(caminho, texto):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), texto)
    doc.save(caminho)
    doc.close()


def test_pdf_invalido_nao_interrompe_a_ingestao(tmp_path):
    raw, saida = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    (raw / "a_quebrado.pdf").write_bytes(b"isto nao e um pdf")
    _pdf_valido(raw / "b_ok.pdf", "Memorando 1 (123456789) SEI 04030-00000001/2024-01 / pg. 1")

    resultados, erros = loader.processar_pasta(raw, saida)

    assert [e["arquivo"] for e in erros] == ["a_quebrado.pdf"]
    assert [r["arquivo_origem"] for r in resultados] == ["b_ok.pdf"]
    salvo = json.loads((saida / "b_ok.json").read_text(encoding="utf-8"))
    assert salvo["documentos"][0]["documento_sei_id"] == "123456789"


def test_pagina_sem_rodape_e_mantida_e_sinalizada(tmp_path):
    caminho = tmp_path / "sem_rodape.pdf"
    _pdf_valido(caminho, "Texto qualquer sem rodape do SEI")
    resultado = loader.processar_pdf(caminho)
    (pagina,) = _paginas(resultado)
    assert "sem_rodape" in pagina["flags"]
    assert resultado["documentos"][0]["documento_sei_id"] is None


def test_pasta_vazia(tmp_path):
    assert loader.processar_pasta(tmp_path, tmp_path / "out") == ([], [])
