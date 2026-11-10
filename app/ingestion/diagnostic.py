"""Relatório de qualidade da ingestão.

Gerado automaticamente ao fim de `python -m app.ingestion.loader`, ou
refeito a partir dos JSONs já processados com:

    python -m app.ingestion.diagnostic
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PASTA_APP = Path(__file__).resolve().parent.parent
PASTA_PROCESSED = PASTA_APP / "data" / "processed"
PASTA_REPORTS = PASTA_APP / "data" / "reports"

# Flags que indicam possível perda de informação (as demais são informativas).
FLAGS_ALERTA = {
    "erro_extracao",
    "sem_rodape",
    "rodape_pagina_divergente",
    "glifos_desconhecidos",
    "candidata_ocr",
}


def _relatorio_arquivo(resultado: dict) -> dict:
    paginas_por_flag: dict[str, list[int]] = defaultdict(list)
    registradas: list[int] = []
    documentos = []
    for doc in resultado["documentos"]:
        for pag in doc["paginas"]:
            registradas.append(pag["pagina"])
            for flag in pag["flags"]:
                paginas_por_flag[flag].append(pag["pagina"])
        documentos.append(
            {
                "documento_sei_id": doc["documento_sei_id"],
                "rotulo": doc["rotulo"],
                "tipo_documento": doc["tipo_documento"],
                "numero_documento": doc["numero_documento"],
                "paginas": f"{doc['pagina_inicio']}-{doc['pagina_fim']}",
                "total_paginas": len(doc["paginas"]),
                "caracteres": sum(len(p["texto_limpo"]) for p in doc["paginas"]),
            }
        )

    esperadas = set(range(1, resultado["total_paginas"] + 1))
    contagem = Counter(registradas)
    ids = Counter(d["documento_sei_id"] for d in resultado["documentos"])

    return {
        "arquivo": resultado["arquivo_origem"],
        "processo_sei": resultado["processo_sei"],
        "total_paginas": resultado["total_paginas"],
        "paginas_registradas": len(registradas),
        "paginas_faltando": sorted(esperadas - set(registradas)),
        "paginas_duplicadas": sorted(p for p, n in contagem.items() if n > 1),
        "total_documentos": len(documentos),
        "documentos_sem_id": sum(1 for d in documentos if not d["documento_sei_id"]),
        "documentos_id_repetido": sorted(i for i, n in ids.items() if i and n > 1),
        "documentos_sem_numero": [d["rotulo"] for d in documentos if not d["numero_documento"]],
        "paginas_por_flag": {f: sorted(p) for f, p in sorted(paginas_por_flag.items())},
        "avisos": resultado.get("avisos", []),
        "documentos": documentos,
    }


def gerar_relatorio(resultados: list[dict], erros: list[dict]) -> dict:
    arquivos = [_relatorio_arquivo(r) for r in resultados]
    alertas = []
    for a in arquivos:
        if a["paginas_faltando"]:
            alertas.append(f"{a['arquivo']}: páginas faltando {a['paginas_faltando']}")
        if a["paginas_duplicadas"]:
            alertas.append(f"{a['arquivo']}: páginas duplicadas {a['paginas_duplicadas']}")
        if a["documentos_id_repetido"]:
            alertas.append(f"{a['arquivo']}: documento SEI aparece em blocos separados {a['documentos_id_repetido']}")
        for flag in sorted(FLAGS_ALERTA & a["paginas_por_flag"].keys()):
            alertas.append(f"{a['arquivo']}: {flag} nas páginas {a['paginas_por_flag'][flag]}")
        alertas.extend(f"{a['arquivo']}: {aviso}" for aviso in a["avisos"])
    alertas.extend(f"{e['arquivo']}: ERRO {e['erro']}" for e in erros)

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "totais": {
            "pdfs_processados": len(arquivos),
            "pdfs_com_erro": len(erros),
            "paginas": sum(a["total_paginas"] for a in arquivos),
            "documentos": sum(a["total_documentos"] for a in arquivos),
        },
        "alertas": alertas,
        "erros": erros,
        "arquivos": arquivos,
    }


def salvar_relatorio(relatorio: dict, pasta: Path = PASTA_REPORTS) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / "relatorio_ingestao.json"
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(relatorio, arquivo, ensure_ascii=False, indent=2)
    return caminho


def imprimir_resumo(relatorio: dict) -> None:
    t = relatorio["totais"]
    print(
        f"\n=== Ingestão: {t['pdfs_processados']} PDF(s), {t['paginas']} páginas, "
        f"{t['documentos']} documentos, {t['pdfs_com_erro']} PDF(s) com erro ==="
    )
    for a in relatorio["arquivos"]:
        print(f"\n{a['arquivo']}  [processo {a['processo_sei']}]")
        print(f"  páginas: {a['paginas_registradas']}/{a['total_paginas']}   documentos: {a['total_documentos']}")
        for d in a["documentos"]:
            numero = d["numero_documento"] or "-"
            print(f"    p{d['paginas']:>9}  {d['documento_sei_id'] or '?':>10}  {d['rotulo'] or '?'}  ({numero})")
        if a["paginas_por_flag"]:
            print("  flags:")
            for flag, paginas in a["paginas_por_flag"].items():
                print(f"    {flag}: {paginas}")
    if relatorio["alertas"]:
        print("\nALERTAS:")
        for alerta in relatorio["alertas"]:
            print(f"  - {alerta}")
    else:
        print("\nNenhum alerta.")


def main() -> None:
    resultados = []
    for caminho in sorted(PASTA_PROCESSED.glob("*.json")):
        with open(caminho, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        if isinstance(dados, dict) and "documentos" in dados:
            resultados.append(dados)
        else:
            print(f"Ignorando {caminho.name}: formato antigo; rode o loader novamente.")
    relatorio = gerar_relatorio(resultados, [])
    caminho = salvar_relatorio(relatorio)
    imprimir_resumo(relatorio)
    print(f"\nRelatório salvo em {caminho}")


if __name__ == "__main__":
    main()
