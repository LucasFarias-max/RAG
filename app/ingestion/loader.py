"""Ingestão de PDFs do SEI: PDF -> JSON estruturado por processo/documento/página.

Uso (a partir da raiz do repositório):

    python -m app.ingestion.loader

Lê todos os PDFs de app/data/raw/, grava um JSON por PDF em
app/data/processed/ e o relatório em app/data/reports/relatorio_ingestao.json.
Um PDF com problema é registrado no relatório e não interrompe os demais.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

import pymupdf

from app.ingestion import sei
from app.ingestion.diagnostic import gerar_relatorio, imprimir_resumo, salvar_relatorio

log = logging.getLogger("ingestao")

PASTA_APP = Path(__file__).resolve().parent.parent
PASTA_RAW = PASTA_APP / "data" / "raw"
PASTA_PROCESSED = PASTA_APP / "data" / "processed"
PASTA_REPORTS = PASTA_APP / "data" / "reports"

VERSAO_FORMATO = 2

# Limiares das flags de qualidade
MIN_CHARS_CONTEUDO = 200  # abaixo disso a página tem "pouco_texto"
MIN_COBERTURA_IMAGEM = 0.5  # fração da página coberta por imagens


class ErroIngestao(Exception):
    """PDF que não pode ser processado (inválido, protegido, vazio...)."""


# --------------------------------------------------------------------------
# Leitura de páginas
# --------------------------------------------------------------------------


def _cobertura_imagens(pagina: pymupdf.Page) -> float:
    area_pagina = pagina.rect.width * pagina.rect.height or 1.0
    area = 0.0
    for imagem in pagina.get_images(full=True):
        for rect in pagina.get_image_rects(imagem[0]):
            rect = rect & pagina.rect  # ignora o que estiver fora da página
            area += rect.width * rect.height
    return min(area / area_pagina, 1.0)


def _ler_pagina(pagina: pymupdf.Page, numero: int) -> dict:
    """Extrai texto bruto, rodapé e cobertura de imagens de uma página."""
    registro = {"pagina": numero, "texto_bruto": "", "rodape": None, "cobertura_imagens": 0.0, "erro": None}
    try:
        registro["texto_bruto"] = pagina.get_text("text")
    except Exception as exc:  # página corrompida não derruba o PDF
        registro["erro"] = f"{type(exc).__name__}: {exc}"
        log.warning("Falha ao extrair texto da página %s: %s", numero, exc)
        return registro
    registro["rodape"] = sei.extrair_rodape(registro["texto_bruto"])
    try:
        registro["cobertura_imagens"] = round(_cobertura_imagens(pagina), 3)
    except Exception as exc:
        log.debug("Não foi possível medir imagens da página %s: %s", numero, exc)
    return registro


def _flags_pagina(lida: dict, texto_limpo: sei.TextoLimpo) -> list[str]:
    flags = []
    if lida["erro"]:
        flags.append("erro_extracao")
    if lida["rodape"] is None:
        flags.append("sem_rodape")
    elif lida["rodape"].pagina != lida["pagina"]:
        flags.append("rodape_pagina_divergente")
    if texto_limpo.glifos_reparados:
        flags.append("glifos_reparados")
    if texto_limpo.glifos_desconhecidos:
        flags.append("glifos_desconhecidos")
    n = len(texto_limpo.texto)
    if n == 0:
        flags.append("sem_conteudo")
    elif n < MIN_CHARS_CONTEUDO:
        flags.append("pouco_texto")
    if lida["cobertura_imagens"] >= MIN_COBERTURA_IMAGEM:
        flags.append("imagem_dominante")
        if n < MIN_CHARS_CONTEUDO:
            flags.append("candidata_ocr")
    return flags


# --------------------------------------------------------------------------
# Montagem processo -> documentos -> páginas
# --------------------------------------------------------------------------


def _novo_documento(rodape: sei.Rodape | None, pagina: int) -> dict:
    rotulo = rodape.rotulo if rodape else None
    return {
        "documento_sei_id": rodape.documento_sei_id if rodape else None,
        "rotulo": rotulo,
        "tipo_documento": sei.tipo_do_rotulo(rotulo) if rotulo else None,
        "numero_documento": None,
        "processo_sei": rodape.processo_sei if rodape else None,
        "pagina_inicio": pagina,
        "pagina_fim": pagina,
        "paginas": [],
    }


def _agrupar_documentos(lidas: list[dict]) -> list[dict]:
    """Agrupa páginas consecutivas com o mesmo ID de documento SEI.

    Página sem rodapé herda o documento anterior (e recebe a flag
    'sem_rodape'); nenhuma página é descartada.
    """
    documentos: list[dict] = []
    atual: dict | None = None
    for lida in lidas:
        rodape = lida["rodape"]
        if atual is None or (rodape and rodape.documento_sei_id != atual["documento_sei_id"]):
            atual = _novo_documento(rodape, lida["pagina"])
            documentos.append(atual)
        elif rodape and atual["documento_sei_id"] is None:
            # documento aberto por página sem rodapé: adota o primeiro rodapé visto
            atual.update({k: v for k, v in _novo_documento(rodape, atual["pagina_inicio"]).items() if k != "paginas"})

        limpo = sei.limpar_texto(lida["texto_bruto"], atual["documento_sei_id"])
        pagina_doc = len(atual["paginas"]) + 1
        atual["paginas"].append(
            {
                "pagina": lida["pagina"],
                "pagina_no_documento": pagina_doc,
                "texto_bruto": lida["texto_bruto"],
                "texto_limpo": limpo.texto,
                "flags": _flags_pagina(lida, limpo),
                "cobertura_imagens": lida["cobertura_imagens"],
            }
        )
        atual["pagina_fim"] = lida["pagina"]

    for doc in documentos:
        primeira = doc["paginas"][0]["texto_bruto"]
        doc["numero_documento"] = sei.extrair_numero_documento(primeira, doc["rotulo"])
    return documentos


def processar_pdf(caminho_pdf: Path) -> dict:
    """Lê um PDF do SEI e devolve a estrutura processo -> documentos -> páginas."""
    try:
        documento = pymupdf.open(caminho_pdf)
    except Exception as exc:
        raise ErroIngestao(f"não foi possível abrir o PDF: {type(exc).__name__}: {exc}") from exc

    with documento:
        if documento.needs_pass:
            raise ErroIngestao("PDF protegido por senha")
        if documento.page_count == 0:
            raise ErroIngestao("PDF sem páginas")
        lidas = [_ler_pagina(pagina, n) for n, pagina in enumerate(documento, start=1)]
        total_paginas = documento.page_count

    documentos = _agrupar_documentos(lidas)

    processos = Counter(d["processo_sei"] for d in documentos if d["processo_sei"])
    processo_nome = sei.processo_do_nome_arquivo(caminho_pdf.name)
    processo = processos.most_common(1)[0][0] if processos else processo_nome
    avisos = []
    if len(processos) > 1:
        avisos.append(f"rodapés citam mais de um processo: {sorted(processos)}")
    if processo_nome and processo and processo_nome != processo:
        avisos.append(f"nome do arquivo indica {processo_nome}, rodapés indicam {processo}")

    return {
        "versao_formato": VERSAO_FORMATO,
        "processo_sei": processo,
        "arquivo_origem": caminho_pdf.name,
        "total_paginas": total_paginas,
        "processado_em": datetime.now().isoformat(timespec="seconds"),
        "avisos": avisos,
        "documentos": documentos,
    }


# --------------------------------------------------------------------------
# Saída e execução em lote
# --------------------------------------------------------------------------


def salvar_json(resultado: dict, pasta_saida: Path = PASTA_PROCESSED) -> Path:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho = pasta_saida / (Path(resultado["arquivo_origem"]).stem + ".json")
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(resultado, arquivo, ensure_ascii=False, indent=2)
    return caminho


def processar_pasta(pasta_raw: Path = PASTA_RAW, pasta_saida: Path = PASTA_PROCESSED) -> tuple[list[dict], list[dict]]:
    """Processa todos os PDFs da pasta. Devolve (resultados, erros)."""
    resultados, erros = [], []
    pdfs = sorted(pasta_raw.glob("*.pdf"))
    if not pdfs:
        log.warning("Nenhum PDF encontrado em %s", pasta_raw)
    for pdf in pdfs:
        try:
            resultado = processar_pdf(pdf)
            saida = salvar_json(resultado, pasta_saida)
        except Exception as exc:
            log.error("%s: %s", pdf.name, exc)
            erros.append({"arquivo": pdf.name, "erro": str(exc), "tipo": type(exc).__name__})
            continue
        resultados.append(resultado)
        log.info(
            "%s: %d páginas, %d documentos -> %s",
            pdf.name, resultado["total_paginas"], len(resultado["documentos"]), saida,
        )
    return resultados, erros


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    resultados, erros = processar_pasta()
    relatorio = gerar_relatorio(resultados, erros)
    caminho = salvar_relatorio(relatorio, PASTA_REPORTS)
    imprimir_resumo(relatorio)
    log.info("Relatório salvo em %s", caminho)


if __name__ == "__main__":
    main()
