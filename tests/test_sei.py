"""Testes unitários das regras de interpretação do SEI (sem PDFs)."""

from app.ingestion import sei

# --------------------------------------------------------------------------
# Rodapé
# --------------------------------------------------------------------------


def test_rodape_com_parenteses():
    texto = "corpo\nMemorando 131 (142739020)         SEI 04030-00001001/2024-23 / pg. 38\n"
    r = sei.extrair_rodape(texto)
    assert r == sei.Rodape("Memorando 131", "142739020", "04030-00001001/2024-23", 38)


def test_rodape_sem_parenteses():
    texto = "Despacho 140494121         SEI 04030-00001001/2024-23 / pg. 36\n"
    r = sei.extrair_rodape(texto)
    assert r.rotulo == "Despacho"
    assert r.documento_sei_id == "140494121"
    assert r.pagina == 36


def test_rodape_rotulo_composto():
    texto = "Despacho CONSEPE (213940949)         SEI 04030-00001179/2025-55 / pg. 183"
    r = sei.extrair_rodape(texto)
    assert r.rotulo == "Despacho CONSEPE"
    assert r.documento_sei_id == "213940949"


def test_rodape_usa_ultima_ocorrencia():
    texto = (
        "citação: Projeto (140362209) SEI 04030-00001001/2024-23 / pg. 9\n"
        "texto\n"
        "Memorando 6 (194797531)  SEI 04030-00001001/2024-23 / pg. 57\n"
    )
    assert sei.extrair_rodape(texto).documento_sei_id == "194797531"


def test_pagina_sem_rodape():
    assert sei.extrair_rodape("Governo do Distrito Federal\nMemorando Nº 98/2024 - UNDF/REIT") is None


# --------------------------------------------------------------------------
# Tipo e número do documento
# --------------------------------------------------------------------------


def test_tipo_do_rotulo():
    assert sei.tipo_do_rotulo("Memorando 131") == "Memorando"
    assert sei.tipo_do_rotulo("Termo de Aceite 19") == "Termo de Aceite"
    assert sei.tipo_do_rotulo("Despacho CONSEPE") == "Despacho"
    assert sei.tipo_do_rotulo("Regimento Interno V3") == "Regimento Interno"
    assert sei.tipo_do_rotulo("Nota Jurídica 115") == "Nota Jurídica"
    assert sei.tipo_do_rotulo("Circular 3") == "Circular"


CABECALHO_MEMORANDO = (
    "Governo do Distrito Federal\nUniversidade do Distrito Federal\nReitoria\n"
    "Centros Interdisciplinares\n \nMemorando Nº 98/2024 - UNDF/REIT/CEINTER\n"
    "Brasília-DF, 07 de maio de 2024.\n"
)


def test_numero_memorando():
    assert sei.extrair_numero_documento(CABECALHO_MEMORANDO, "Memorando 98") == "98/2024 - UNDF/REIT/CEINTER"


def test_numero_nota_juridica_com_n_ponto():
    texto = "Procuradoria Jurídica\nNota Jurídica N.º 115/2025 - UNDF/REIT/PROJUR\nBrasília-DF"
    assert sei.extrair_numero_documento(texto, "Nota Jurídica 115") == "115/2025 - UNDF/REIT/PROJUR"


def test_numero_sigla_com_hifen():
    texto = "Vice-Reitoria\nOfício Nº 20/2026 - UNDF/REIT/VICE-REIT/CEINTER\nBrasília-DF"
    assert sei.extrair_numero_documento(texto, "Ofício 20") == "20/2026 - UNDF/REIT/VICE-REIT/CEINTER"


def test_numero_quebrado_em_duas_linhas():
    texto = "Centros Interdisciplinares\n \n \nTERMO DE ACEITE\n19/2026\nTERMO DE ANUÊNCIA"
    assert sei.extrair_numero_documento(texto, "Termo de Aceite 19") == "19/2026"


def test_edital_aceita_chamada_publica():
    texto = "Gabinete\nChamada Pública n.º 53/2024 - FAPDF/PRES/GAB\nBrasília-DF"
    assert sei.extrair_numero_documento(texto, "Edital") == "53/2024 - FAPDF/PRES/GAB"


def test_numero_de_outro_tipo_e_ignorado():
    # Despacho que responde ao Memorando 131: o número é do memorando, não do despacho.
    texto = "Reitoria\nDespacho - UNDF/REIT\nAssunto: resposta ao Memorando Nº 131/2024 - UNDF/REIT/CEINTER\n"
    assert sei.extrair_numero_documento(texto, "Despacho") is None


def test_numero_citado_no_corpo_e_ignorado():
    # Armadilha real: Termo de Outorga 500/2024 citado num despacho do CONSEPE.
    corpo = "\n".join(f"linha {i}" for i in range(sei.LINHAS_CABECALHO))
    texto = "Despacho - CONSEPE\n" + corpo + "\nDespacho nº 500/2024 - FAPDF/SUCTI/COOTI\n"
    assert sei.extrair_numero_documento(texto, "Despacho CONSEPE") is None


def test_numero_divergente_do_rotulo_e_descartado():
    texto = "Memorando Nº 22/2024 - UNDF/REIT/CEINTER/COETI"
    assert sei.extrair_numero_documento(texto, "Memorando 11") is None


def test_tipo_sem_numeracao_oficial():
    texto = "PROPOSTA EDITAL 06/2024 PROGRAMA FAPDF LEARNING"
    assert sei.extrair_numero_documento(texto, "Projeto") is None


def test_processo_do_nome_arquivo():
    assert sei.processo_do_nome_arquivo("SEI_04030_00001001_2024_23 (2).pdf") == "04030-00001001/2024-23"
    assert sei.processo_do_nome_arquivo("qualquer.pdf") is None


# --------------------------------------------------------------------------
# Limpeza
# --------------------------------------------------------------------------


def test_ligaduras_normalizadas():
    assert sei.limpar_texto("cientiﬁca, ﬂuxo").texto == "cientifica, fluxo"


def test_reparo_de_glifos_por_documento():
    r = sei.limpar_texto("Incen\x01var a pesquisa cien\x02ﬁca", "140334392")
    assert r.texto == "Incentivar a pesquisa científica"
    assert r.glifos_reparados == 2
    assert r.glifos_desconhecidos == 0


def test_glifo_sem_reparo_e_removido_e_contado():
    r = sei.limpar_texto("Incen\x01var", "999")
    assert r.texto == "Incenvar"
    assert r.glifos_desconhecidos == 1


def test_remove_moldura_sei_e_mantem_assinatura():
    texto = (
        "Atenciosamente,\n"
        "Documento assinado eletronicamente por FULANO DE TAL - Matr.123, em 06/06/2024.\n"
        "A autenticidade do documento pode ser conferida no site:\n"
        "https://sei.df.gov.br/sei/controlador_externo.php?\n"
        "acao=documento_conferir&id_orgao_acesso_externo=0 \n"
        "Código Verificador: 142739020 Código CRC: CABB585A.\n"
        '"Brasília - Patrimônio Cultural da Humanidade"\n'
        "Edifício Governança Bloco B 2º Andar - Bairro Granja do Torto - CEP 70.636-000 - DF\n"
        "Telefone(s): 34628866\n"
        "Sítio  - https://undf.edu.br/\n"
        "04030-00001001/2024-23\n"
        "Doc. SEI/GDF 142739020\n"
        "Memorando 131 (142739020)         SEI 04030-00001001/2024-23 / pg. 38\n"
    )
    limpo = sei.limpar_texto(texto).texto
    assert limpo == (
        "Atenciosamente,\n"
        "Documento assinado eletronicamente por FULANO DE TAL - Matr.123, em 06/06/2024."
    )


def test_substituicoes_de_caracteres():
    assert sei.limpar_texto("​Despacho ̶ UNDF\n item").texto == "Despacho - UNDF\n• item"
