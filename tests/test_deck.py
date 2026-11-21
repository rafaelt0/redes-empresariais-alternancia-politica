from pathlib import Path

import polars as pl
import pytest

from redes import deck
from redes.config import Caminhos
from redes.etapas import Contexto
from redes.numeros import Numeros


def test_efeito_preserva_sinal_de_intervalos_pequenos() -> None:
    linha = {"estimativa": 0.0004, "ic_inf": -0.0002, "ic_sup": 0.0011}
    assert deck._efeito(linha, casas=2) == "0,04 (-0,02 a 0,11)"


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
    assert 540 <= sum(nota.segundos for nota in notas) < deck.LIMITE_SEGUNDOS
    assert {nota.pessoa for nota in notas} == set(deck.VOZES)
    for slide, nota in zip(prs.slides, notas, strict=True):
        assert slide.notes_slide.notes_text_frame.text == nota.texto()


def test_guia_equilibra_os_blocos_e_nao_define_pessoas(tmp_path: Path) -> None:
    prs, notas = deck.construir(_caminhos(tmp_path), Numeros({}))
    titulos = [slide.shapes[0].text_frame.text for slide in prs.slides]
    texto = deck.guia(notas, titulos)
    por_bloco: dict[str, int] = {}
    for nota in notas:
        por_bloco[nota.pessoa] = por_bloco.get(nota.pessoa, 0) + nota.segundos
    assert set(por_bloco) == set(deck.VOZES)
    assert set(por_bloco.values()) == {135}
    assert "2:15" in texto
    assert "1:00" in texto
    for autor in ("Felipe", "Andrei", "Rafael", "João Pedro"):
        assert autor not in texto


def test_guia_recusa_blocos_com_tempos_desiguais() -> None:
    notas = [
        deck.Nota("Voz 1", 10, "fala", ()),
        deck.Nota("Voz 2", 20, "fala", ()),
    ]
    with pytest.raises(ValueError, match="mesmo tempo"):
        deck.guia(notas, ["a", "b"])


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
    prs, notas = deck.construir(caminhos, numeros)
    textos = " ".join(
        forma.text_frame.text
        for slide in prs.slides
        for forma in slide.shapes
        if forma.has_text_frame
    )
    notas_texto = " ".join(nota.texto() for nota in notas)
    assert "1.234 empresas" in notas_texto
    assert "5.678 vértices de sócios/administradores PF/PJ" in notas_texto
    assert "-1,2 p.p." in textos
    assert "IC de 95% de -5,0 a 2,5 p.p." in textos


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
    assert linhas[0][1:] == [
        "10,0 (0,0 a 20,0)",
        "11,0 (1,0 a 21,0)",
        "12,0 (2,0 a 22,0)",
        "13,0 (3,0 a 23,0)",
    ]
    assert linhas[1][1] == "n.d."


def test_conversao_preserva_o_numero_de_slides(tmp_path: Path) -> None:
    from redes.portabilidade import ferramenta

    try:
        ferramenta("soffice")
    except FileNotFoundError as erro:
        pytest.skip(str(erro))
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
