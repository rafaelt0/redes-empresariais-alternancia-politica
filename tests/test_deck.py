import shutil
from pathlib import Path

import polars as pl
import pytest

from redes import deck
from redes.config import Caminhos
from redes.etapas import Contexto
from redes.numeros import Numeros


def _caminhos(tmp_path: Path) -> Caminhos:
    return Caminhos(
        dados=tmp_path / "dados",
        resultados=tmp_path / "results",
        saida=tmp_path / "output",
        chave=tmp_path / "chave",
    )


def test_deck_tem_de_10_a_12_slides(tmp_path: Path) -> None:
    prs, notas = deck.construir(_caminhos(tmp_path), Numeros({}))
    assert deck.MINIMO_SLIDES <= len(prs.slides) <= deck.MAXIMO_SLIDES
    assert len(notas) == len(prs.slides)
    assert 540 <= sum(nota.segundos for nota in notas) <= 660
    assert {nota.pessoa for nota in notas} == {
        "Felipe",
        "Andrei",
        "Rafael",
        "João Pedro",
    }


def test_deck_usa_os_numeros_das_tabelas(tmp_path: Path) -> None:
    caminhos = _caminhos(tmp_path)
    (caminhos.resultados / "tables").mkdir(parents=True)
    pl.DataFrame(
        {
            "variante": ["PRINCIPAL"] * 3,
            "medida": ["empresas", "pessoas", "vinculos"],
            "valor": [1234, 5678, 9999],
        }
    ).write_csv(caminhos.resultados / "tables" / "rede_resumo.csv")
    pl.DataFrame(
        {
            "hipotese": ["H1"],
            "tipo": ["contraste"],
            "estimativa": [-0.01234],
            "ic_inf": [-0.050],
            "ic_sup": [0.025],
        }
    ).write_csv(caminhos.resultados / "tables" / "resumo_estimacao.csv")
    numeros = Numeros.ler(caminhos.resultados / "tables")
    prs, _ = deck.construir(caminhos, numeros)
    textos = " ".join(
        forma.text_frame.text
        for slide in prs.slides
        for forma in slide.shapes
        if forma.has_text_frame
    )
    assert "1.234 empresas" in textos
    assert "5.678 pessoas" in textos
    assert "Estimativa: -0,012 (IC 95%: -0,050 a 0,025)" in textos


def test_tabela_de_robustez_usa_as_quatro_variantes() -> None:
    robustez = pl.DataFrame(
        {
            "hipotese": ["H1", "H1", "H1", "H1"],
            "categoria": ["conectada_menos_sem_conexao"] * 4,
            "tipo": ["contraste"] * 4,
            "resultado": ["participacao_2025"] * 4,
            "estimativa_principal": [0.1, 0.2, 0.3, 0.4],
            "ic_inf_principal": [0.0, 0.1, 0.2, 0.3],
            "ic_sup_principal": [0.2, 0.3, 0.4, 0.5],
            "estimativa_sem_articulacao": [0.11, None, None, None],
            "ic_inf_sem_articulacao": [0.01, None, None, None],
            "ic_sup_sem_articulacao": [0.21, None, None, None],
            "estimativa_sem_pj": [0.12, None, None, None],
            "ic_inf_sem_pj": [0.02, None, None, None],
            "ic_sup_sem_pj": [0.22, None, None, None],
            "estimativa_sem_administrador": [0.13, None, None, None],
            "ic_inf_sem_administrador": [0.03, None, None, None],
            "ic_sup_sem_administrador": [0.23, None, None, None],
        }
    )
    linhas = deck._linhas_robustez(robustez)
    assert [linha[0] for linha in linhas] == ["H1", "H2", "H3"]
    assert linhas[0][1].startswith("0,100")
    assert linhas[1][1] == "n.d."


def test_conversao_preserva_o_numero_de_slides(tmp_path: Path) -> None:
    if shutil.which("soffice") is None:
        pytest.skip("LibreOffice não instalado")
    prs, _ = deck.construir(_caminhos(tmp_path), Numeros({}))
    pptx = tmp_path / "deck.pptx"
    prs.save(str(pptx))
    pdf = deck.converter(pptx, tmp_path / "deck.pdf")
    assert deck.contar_slides(pptx) == deck.contar_paginas(pdf)


def test_deck_falha_sem_os_resultados_e_preserva_a_entrega_anterior(tmp_path: Path) -> None:
    caminhos = _caminhos(tmp_path)
    caminhos.saida.mkdir()
    anterior = caminhos.saida / "guia_de_fala.md"
    anterior.write_text("versão anterior", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="resumo_estimacao"):
        deck.executar(Contexto(deck.ETAPA, caminhos))
    assert anterior.read_text(encoding="utf-8") == "versão anterior"
    assert not (caminhos.saida / "deck.pptx").exists()
