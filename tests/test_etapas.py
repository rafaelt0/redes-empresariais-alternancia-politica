import re
from pathlib import Path

import pytest

from redes import deck, etapas, report, schemas
from redes.etapas import Contexto

RAIZ = Path(__file__).resolve().parents[1]
ETAPAS_DA_SPEC = [
    "fetch", "ingest-rfb", "ingest-tse", "ingest-tcesp", "elections", "links",
    "network", "panel", "estimate", "report", "deck",
]  # fmt: skip
POS_INGESTAO = ETAPAS_DA_SPEC[4:]


def _declaracoes() -> dict[str, etapas.Etapa]:
    return {nome: etapas.modulo(nome).ETAPA for nome in etapas.MODULOS}


def test_registro_tem_as_etapas_da_spec_em_ordem():
    assert list(etapas.MODULOS) == ETAPAS_DA_SPEC
    assert all(e.nome == nome for nome, e in _declaracoes().items())


def test_makefile_espelha_as_dependencias():
    regra = re.compile(r"^\$\(FEITO\)/(\S+):(.*)$", re.MULTILINE)
    makefile = (RAIZ / "Makefile").read_text()
    deps = {
        alvo: tuple(re.findall(r"\$\(FEITO\)/(\S+)", resto))
        for alvo, resto in regra.findall(makefile)
        if alvo != "%"
    }
    assert deps == {nome: e.depende for nome, e in _declaracoes().items()}


def test_cada_tabela_tem_uma_produtora_anterior_a_quem_le():
    declaracoes = _declaracoes()
    produtoras = [(t.nome, nome) for nome, e in declaracoes.items() for t in e.grava]
    assert sorted(t for t, _ in produtoras) == sorted(schemas.TABELAS)
    produtora = dict(produtoras)

    def anteriores(nome: str) -> set[str]:
        diretas = set(declaracoes[nome].depende)
        return diretas.union(*(anteriores(d) for d in diretas))

    for nome, e in declaracoes.items():
        for tabela in e.le:
            assert produtora[tabela.nome] in anteriores(nome), (nome, tabela.nome)


def test_contexto_recusa_leitura_nao_declarada(caminhos_amostra):
    ctx = Contexto(etapas.modulo("elections").ETAPA, caminhos_amostra)
    ctx.ler(schemas.CANDIDATOS)
    with pytest.raises(KeyError):
        ctx.ler(schemas.SOCIOS)


def test_etapa_falha_quando_entrada_falta(caminhos_amostra):
    (caminhos_amostra.dados / schemas.VOTOS.arquivo).unlink()
    with pytest.raises(FileNotFoundError, match="votos"):
        etapas.rodar("elections", caminhos_amostra)


def test_pipeline_percorre_a_amostra(caminhos_amostra):
    for nome in POS_INGESTAO:
        etapas.rodar(nome, caminhos_amostra)
    for tabela in schemas.TABELAS.values():
        assert (caminhos_amostra.dados / tabela.arquivo).exists(), tabela.nome
    saida = caminhos_amostra.saida
    assert 0 < report.contar_paginas(saida / "relatorio.pdf") <= report.MAXIMO_PAGINAS
    slides = deck.contar_slides(saida / "deck.pptx")
    assert deck.MINIMO_SLIDES <= slides <= deck.MAXIMO_SLIDES
    assert slides == deck.contar_paginas(saida / "deck.pdf")
    assert (saida / "guia_de_fala.md").stat().st_size > 0
    for arquivo in (
        "resumo_estimacao.csv",
        "validacao.csv",
        "comparabilidade_h2.csv",
        "h2_comparaveis.csv",
        "mercados_sem_empenho.csv",
        "permanencia_h4.csv",
    ):
        assert (caminhos_amostra.resultados / "tables" / arquivo).stat().st_size > 0
