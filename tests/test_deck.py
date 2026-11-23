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


def test_deck_tem_nove_slides(tmp_path: Path) -> None:
    prs, notas = deck.construir(_caminhos(tmp_path), Numeros({}))
    assert len(prs.slides) == 9
    assert len(notas) == len(prs.slides)
    assert sum(nota.segundos for nota in notas) == 520
    assert [nota.pessoa for nota in notas] == [
        voz
        for voz, quantidade in zip(deck.VOZES, (4, 1, 2, 2), strict=True)
        for _ in range(quantidade)
    ]
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
    assert set(por_bloco.values()) == {130}
    assert "2:10" in texto
    assert "1:20" in texto
    assert "| Voz 1 | Economia política e hipóteses | 1–4 | 2:10 |" in texto
    assert "| Voz 2 | Desenho empírico e fontes | 5 | 2:10 |" in texto
    assert "| Voz 4 | Resultados de H2 e conclusão | 8–9 | 2:10 |" in texto
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
    tabelas = caminhos.resultados / "tables"
    tabelas.mkdir(parents=True)
    pl.DataFrame(
        {
            "variante": ["PRINCIPAL"] * 8 + ["SEM_ARTICULACAO"],
            "indicador": [
                "empresas",
                "pessoas",
                "vinculos",
                "assortatividade_grau",
                "componentes",
                "fracao_no_maior_componente",
                "municipios_com_conexao_a",
                "municipios_com_conexao_b",
                "fracao_no_maior_componente",
            ],
            "valor": [1234.0, 5678.0, 9999.0, -0.12, 250.0, 0.2, 38.0, 32.0, 0.05],
        }
    ).write_csv(tabelas / "rede_resumo.csv")
    pl.DataFrame(
        {"indicador": ["municipios_analisaveis"], "grupo": [""], "valor": [50.0]}
    ).write_csv(tabelas / "links_pc1.csv")
    pl.DataFrame(
        {
            "hipotese": ["H1"],
            "tipo": ["contraste"],
            "estimativa": [-0.01234],
            "ic_inf": [-0.050],
            "ic_sup": [0.025],
        }
    ).write_csv(tabelas / "resumo_estimacao.csv")
    numeros = Numeros.ler(tabelas)
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
    metricas = {forma.text_frame.text for forma in prs.slides[5].shapes if forma.has_text_frame}
    assert {"1.234", "5.678", "9.999", "250", "20,0%", "5,0%", "38", "32"} <= metricas
    assert "De 50 municípios analisáveis." in metricas
    assert "1.427,072 vínculo por milhão" in textos
    assert "r = -0,1200" in textos
    assert "-1,2 p.p." in textos
    assert "IC de 95% de -5,0 a 2,5 p.p." in textos


def test_deck_ordena_os_cinco_blocos_e_destaca_h2(tmp_path: Path) -> None:
    prs, _ = deck.construir(_caminhos(tmp_path), Numeros({}))
    secoes = [slide.shapes[1].text_frame.text for slide in prs.slides]
    assert prs.slides[0].shapes[0].text_frame.text == deck.TITULO
    assert secoes[1:] == [
        deck.CONTEXTO,
        deck.CONTEXTO,
        deck.HIPOTESES,
        deck.DESENHO,
        deck.REDE,
        deck.RESULTADOS,
        f"{deck.RESULTADOS}  /  H2",
        f"{deck.RESULTADOS}  /  H2",
    ]
    teoria = " ".join(
        forma.text_frame.text for forma in prs.slides[1].shapes if forma.has_text_frame
    )
    assert all(termo in teoria for termo in ("conflito social", "de jure", "de facto", "Acemoglu"))
    assert "Para Acemoglu, Johnson e Robinson (2005)" in teoria
    assert "Regras econômicas  →  Distribuição de recursos  →  Poder de fato futuro" in teoria
    assert "empenhos" not in teoria
    aplicacao = " ".join(
        forma.text_frame.text for forma in prs.slides[2].shapes if forma.has_text_frame
    )
    assert all(
        termo in aplicacao
        for termo in (
            "incumbente",
            "mesma rede",
            "ligada ao vencedor, pode compensar",
            "doações de campanha",
            "fatia de empresas e redes nos empenhos de 2025",
        )
    )
    rede = " ".join(forma.text_frame.text for forma in prs.slides[5].shapes if forma.has_text_frame)
    assert all(termo in rede for termo in ("Receita Federal", "TSE", "TCESP", "maior componente"))
    titulos = [slide.shapes[0].text_frame.text for slide in list(prs.slides)[-2:]]
    assert "distância" in titulos[0]
    assert "especificação" in titulos[1]


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
