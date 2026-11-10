"""Regras de interpretação de PDFs exportados do SEI-GDF.

Funções puras (sem dependência do PyMuPDF), para poderem ser testadas com
strings simples.

Todo PDF de processo exportado pelo SEI traz, no fim de cada página, um
rodapé padronizado:

    Memorando 131 (142739020)         SEI 04030-00001001/2024-23 / pg. 38
    Despacho 140494121                SEI 04030-00001001/2024-23 / pg. 36

Esse rodapé é a fonte confiável de: rótulo do documento, ID do documento no
SEI, número do processo e página. O número oficial do documento
(ex.: "98/2024 - UNDF/REIT/CEINTER") só aparece no cabeçalho da primeira
página de cada documento.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Rodapé
# --------------------------------------------------------------------------

RODAPE = re.compile(
    r"(?P<rotulo>[^\n]*?)\s*\(?(?P<documento_sei_id>\d{6,10})\)?"
    r"[ \t]+SEI[ \t]+(?P<processo_sei>\d{5}-\d{8}/\d{4}-\d{2})"
    r"[ \t]*/[ \t]*pg\.[ \t]*(?P<pagina>\d+)[ \t]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Rodape:
    rotulo: str
    documento_sei_id: str
    processo_sei: str
    pagina: int


def extrair_rodape(texto: str) -> Rodape | None:
    """Devolve o rodapé SEI da página (a última ocorrência), ou None."""
    ocorrencias = list(RODAPE.finditer(texto))
    if not ocorrencias:
        return None
    m = ocorrencias[-1]
    return Rodape(
        rotulo=re.sub(r"\s+", " ", m["rotulo"]).strip(),
        documento_sei_id=m["documento_sei_id"],
        processo_sei=m["processo_sei"],
        pagina=int(m["pagina"]),
    )


# --------------------------------------------------------------------------
# Tipo de documento (a partir do rótulo do rodapé)
# --------------------------------------------------------------------------

# Ordem importa: prefixos mais longos antes dos mais curtos.
TIPOS_CONHECIDOS = [
    "Termo de Aceite",
    "Termo de Outorga",
    "Termo",
    "Nota Jurídica",
    "Nota Técnica",
    "Declaração Simples",
    "Declaração",
    "Regimento Interno",
    "Regimento",
    "Relatório",
    "Memorando",
    "Ofício",
    "Despacho",
    "Edital",
    "Projeto",
    "Ata",
    "E-mail",
    "Apresentação",
    "Decreto",
    "Instrução",
    "Portaria",
    "Convênio",
    "Justificativa",
    "Parecer",
    "Anexo",
]


def tipo_do_rotulo(rotulo: str) -> str | None:
    """'Memorando 131' -> 'Memorando'; 'Despacho CONSEPE' -> 'Despacho'."""
    for tipo in TIPOS_CONHECIDOS:
        if re.match(rf"{re.escape(tipo)}\b", rotulo, re.IGNORECASE):
            return tipo
    # Fallback: rótulo sem o número final ("Circular 3" -> "Circular").
    base = re.sub(r"\s*\d[\w./-]*$", "", rotulo).strip()
    return base or None


def numero_do_rotulo(rotulo: str) -> str | None:
    """'Memorando 131' -> '131'; 'Termo de Aceite 19' -> '19'."""
    m = re.search(r"\b(\d+)$", rotulo)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Número oficial do documento (cabeçalho da 1ª página)
# --------------------------------------------------------------------------

# Como cada tipo de documento se apresenta no cabeçalho. Só procuramos o
# número com o MESMO tipo do documento: um despacho que cita "Memorando
# 131/2024" no assunto não pode herdar esse número.
TIPO_NO_CABECALHO = {
    "Memorando": r"memorando",
    "Ofício": r"of[ií]cio",
    "Despacho": r"despacho",
    "Termo de Aceite": r"termo\s+de\s+aceite",
    "Nota Jurídica": r"nota\s+jur[ií]dica",
    "Nota Técnica": r"nota\s+t[eé]cnica",
    "Edital": r"edital|chamada\s+p[uú]blica",
    "Ata": r"ata",
    "Portaria": r"portaria",
    "Parecer": r"parecer",
    "Instrução": r"instru[cç][aã]o",
    "Decreto": r"decreto",
    "Circular": r"circular",
}

NUMERO_CABECALHO = (
    r"\s*(?:[Nn]\.?\s*[º°oO]?\s*\.?\s*º?\s*)?"
    r"(?P<numero>\d{1,5}/\d{4})"
    r"(?:[ \t]*-[ \t]*(?P<sigla>[A-Z][A-Z0-9/\-]*[A-Z0-9]))?"
)

LINHAS_CABECALHO = 20


def extrair_numero_documento(texto_primeira_pagina: str, rotulo: str | None) -> str | None:
    """Número oficial do documento, procurado só no cabeçalho.

    - Só nas primeiras linhas, para não capturar números citados no corpo
      (ex.: "Termo de Outorga 500/2024" mencionado num despacho).
    - Só com o mesmo tipo do documento (vem do rótulo do rodapé).
    - Se o rótulo tiver número ("Memorando 131"), o número do cabeçalho
      precisa coincidir; caso contrário, é descartado.
    """
    if not rotulo:
        return None
    tipo = tipo_do_rotulo(rotulo)
    padrao_tipo = TIPO_NO_CABECALHO.get(tipo or "")
    if not padrao_tipo:
        return None
    regex = re.compile(rf"\b(?i:{padrao_tipo}){NUMERO_CABECALHO}")
    cabecalho = "\n".join(texto_primeira_pagina.splitlines()[:LINHAS_CABECALHO])
    esperado = numero_do_rotulo(rotulo)
    for m in regex.finditer(cabecalho):
        numero = m["numero"]
        if esperado and numero.split("/")[0].lstrip("0") != esperado.lstrip("0"):
            continue
        return f"{numero} - {m['sigla']}" if m["sigla"] else numero
    return None


# --------------------------------------------------------------------------
# Processo a partir do nome do arquivo
# --------------------------------------------------------------------------

NOME_ARQUIVO = re.compile(r"SEI_(\d{5})_(\d{8})_(\d{4})_(\d{2})")


def processo_do_nome_arquivo(nome: str) -> str | None:
    """'SEI_04030_00001001_2024_23 (2).pdf' -> '04030-00001001/2024-23'."""
    m = NOME_ARQUIVO.search(nome)
    if not m:
        return None
    return f"{m[1]}-{m[2]}/{m[3]}-{m[4]}"


# --------------------------------------------------------------------------
# Limpeza de texto
# --------------------------------------------------------------------------

# Glifos sem mapeamento Unicode viram caracteres de controle (\x01, \x02...)
# na extração: o PyMuPDF usa o ID do glifo no lugar do caractere. Os IDs são
# próprios da fonte embutida em cada documento, então o reparo é cadastrado
# por documento, depois de conferido manualmente.
REPAROS_GLIFOS: dict[str, dict[str, str]] = {
    # Edital FAPDF (Chamada Pública 53/2024), fonte Calibri com ligaduras.
    # Conferido em "Incen\x01var", "cien\x02ﬁca", "h\x03p://", "\x04sico-ﬁnanceiro", "h\x05ps://".
    "140334392": {"\x01": "ti", "\x02": "tí", "\x03": "tt", "\x04": "fí", "\x05": "tt"},
}

CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")
LIGADURAS = re.compile(r"[\ufb00-\ufb06]")
SUBSTITUICOES = {
    "\u200b": "",  # zero-width space
    "\u00ad": "",  # hífen condicional
    "\u00a0": " ",  # espaço inseparável
    "\uf0b7": "•",  # marcador de lista (área de uso privado, fonte Symbol)
    "\u0336": "-",  # traço combinante em "Despacho ̶ UNDF/REIT"
}

# Linhas que são apenas "moldura" do SEI e não carregam conteúdo.
LINHAS_BOILERPLATE = [
    re.compile(p)
    for p in (
        RODAPE.pattern,
        r"^A auten\w*cidade do documento pode ser conferida",
        r"^https?://sei\.df\.gov\.br/?(?:sei/controlador_externo\.php\?.*)?$",
        r"^/?sei/controlador_externo\.php\?",
        r"^acao=documento_conferir",
        r"^C[óo]digo Verificador:",
        r"^veri\w*cador\s*=",
        r'^"Bras[ií]lia - Patrim[ôo]nio Cultural da Humanidade"$',
        r"^.*\bCEP\s*[\d.\-]+\s*-\s*DF$",
        r"^Telefone\(s\):",
        r"^S[ií]\w*o\s+-\s+\S+$",
        r"^\d{5}-\d{8}/\d{4}-\d{2}$",
        r"^Doc\. SEI/GDF \d+$",
        # Artefatos de "imprimir para PDF" do navegador (ex.: edital da FAPDF)
        r"^SEI/GDF - \d+ - ",
        r"^https?://sei\.df\.gov\.br/sei/controlador\.php\?acao=documento_imprimir",
        r"^\d+ of \d+$",
        r"^\d{2}/\d{2}/\d{4}, \d{2}:\d{2}$",
    )
]


@dataclass
class TextoLimpo:
    texto: str
    glifos_reparados: int = 0
    glifos_desconhecidos: int = 0


def limpar_texto(texto: str, documento_sei_id: str | None = None) -> TextoLimpo:
    """Normaliza o texto de uma página e remove a moldura do SEI.

    Mantém as assinaturas ("Documento assinado eletronicamente por ..."),
    que são conteúdo útil (quem assinou e quando).
    """
    reparados = 0
    for glifo, troca in REPAROS_GLIFOS.get(documento_sei_id or "", {}).items():
        reparados += texto.count(glifo)
        texto = texto.replace(glifo, troca)

    desconhecidos = len(CONTROLE.findall(texto))
    texto = CONTROLE.sub("", texto)

    texto = LIGADURAS.sub(lambda m: unicodedata.normalize("NFKC", m.group()), texto)
    for antigo, novo in SUBSTITUICOES.items():
        texto = texto.replace(antigo, novo)

    linhas = []
    for linha in texto.splitlines():
        linha = linha.rstrip()
        conteudo = linha.strip()
        if conteudo and any(p.search(conteudo) for p in LINHAS_BOILERPLATE):
            continue
        linhas.append(linha)

    limpo = "\n".join(linhas)
    limpo = re.sub(r"[ \t]+\n", "\n", limpo)
    limpo = re.sub(r"\n{3,}", "\n\n", limpo).strip()
    return TextoLimpo(limpo, reparados, desconhecidos)
