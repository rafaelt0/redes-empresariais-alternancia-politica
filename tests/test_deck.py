from pathlib import Path

import polars as pl
import pytest
from lxml import html

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
    assert sum(nota.segundos for nota in notas) == 580
    assert [nota.pessoa for nota in notas] == [
        voz
        for voz, quantidade in zip(deck.VOZES, (3, 2, 2, 2), strict=True)
        for _ in range(quantidade)
    ]
    for slide, nota in zip(prs.slides, notas, strict=True):
        assert slide.notes_slide.notes_text_frame.text == nota.texto()


def test_guias_atribuem_os_slides_e_equilibram_os_blocos(tmp_path: Path) -> None:
    prs, notas = deck.construir(_caminhos(tmp_path), Numeros({}))
    titulos = [slide.shapes[0].text_frame.text for slide in prs.slides]
    texto = deck.guia(notas, titulos)
    por_bloco: dict[str, int] = {}
    for nota in notas:
        por_bloco[nota.pessoa] = por_bloco.get(nota.pessoa, 0) + nota.segundos
    assert set(por_bloco) == set(deck.VOZES)
    assert set(por_bloco.values()) == {145}
    assert "9:40" in texto
    assert "0:20" in texto

    roteiros = deck.guias_individuais(notas, titulos)
    for i, (nome, slides) in enumerate(
        (("Andrei", "1–3"), ("Felipe", "4–5"), ("João Pedro", "6–7"), ("Rafael", "8–9")),
        start=1,
    ):
        arquivo = f"guia_voz_{i}.md"
        assert f"[Voz {i} · {nome}]({arquivo})" in texto
        assert f"| {slides} | 2:25 |" in texto
        roteiro = roteiros[arquivo]
        assert roteiro.startswith(f"# Voz {i} · {nome}\n")
        assert "2:25)" in roteiro
        for j, nota in enumerate(notas, start=1):
            if nota.pessoa == f"Voz {i}":
                assert f"## Slide {j} · {titulos[j - 1]}" in roteiro
                assert nota.fala in roteiro
            else:
                assert f"## Slide {j} ·" not in roteiro
        assert "Se perguntarem" not in roteiro


def test_guia_recusa_blocos_com_tempos_desiguais() -> None:
    notas = [
        deck.Nota("Voz 1", 10, "fala", ()),
        deck.Nota("Voz 2", 20, "fala", ()),
    ]
    with pytest.raises(ValueError, match="mesmo tempo"):
        deck.guia(notas, ["a", "b"])


def test_guia_html_reune_as_falas_e_os_links_de_cada_voz(tmp_path: Path) -> None:
    prs, notas = deck.construir(_caminhos(tmp_path), Numeros({}))
    titulos = [slide.shapes[0].text_frame.text for slide in prs.slides]
    titulos[0] = "<título> & texto"
    documento = html.fromstring(deck.guia_html(notas, titulos, amostra=True))
    assert documento.get("lang") == "pt-BR"
    assert documento.xpath("//p[@class='amostra']/text()") == ["Amostra sintética para teste."]
    assert documento.xpath("//nav//a/@href") == ["#voz-1", "#voz-2", "#voz-3", "#voz-4"]
    assert documento.xpath("//main/section/@id") == ["voz-1", "voz-2", "voz-3", "voz-4"]
    assert documento.xpath("//main/section/header//h2/text()") == list(deck.APRESENTADORES.values())
    assert documento.xpath("//p[@class='duracao']/text()") == ["2:25 de fala"] * 4
    assert documento.xpath("//div[@class='slide']/h3/text()", smart_strings=False) == titulos
    for bloco, nota in zip(documento.xpath("//div[@class='slide']"), notas, strict=True):
        paragrafos = bloco.xpath("./p[not(@class)]/text()", smart_strings=False)
        assert paragrafos == nota.fala.split("\n\n")
    assert not documento.xpath("//link[@href] | //script | //img[@src]")


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
            "emd": [0.207],
        }
    ).write_csv(tabelas / "resumo_estimacao.csv")
    pl.DataFrame(
        {"categoria": ["faixa_a_0"], "media_participacao_2025": [0.017703287989352376]}
    ).write_csv(tabelas / "descritivas_estimacao.csv")
    pl.DataFrame({"coorte": ["H3_ambos"], "fracao_empenho_gigante": [0.9987]}).write_csv(
        tabelas / "sensibilidade_gigante.csv"
    )
    pl.DataFrame(
        {
            "hipotese": ["H3"],
            "tipo": ["contraste"],
            "resultado": ["variacao_total"],
            "estimavel": [False],
        }
    ).write_csv(tabelas / "sensibilidade_sem_gigante.csv")
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
    rede_slide = " ".join(metricas)
    assert {"20,0%", "5,0%", "38", "32"} <= metricas
    assert all(termo in rede_slide for termo in ("1.234", "5.678", "9.999", "250"))
    assert "De 50 municípios analisáveis." in metricas
    assert {
        "X (semente) — Y — Z",
        "X — Y (semente) — Z",
    } <= metricas
    assert all(trecho in notas[5].fala for trecho in ("sócia de X doou a A", "sócio de Y doou a A"))
    assert "1.427,072 vínculo por milhão" in textos
    assert "r = -0,1200" in textos
    assert "-1,2 p.p." in textos
    assert "IC de 95% de -5,0 a 2,5 p.p." in textos
    assert "Efeito mínimo detectável: 20,7 p.p." in textos
    assert "Média em 2025 (ligadas a A): 1,77%" in textos
    assert "H3" not in textos


def test_deck_ordena_os_cinco_blocos_e_preserva_hierarquia(tmp_path: Path) -> None:
    prs, notas = deck.construir(_caminhos(tmp_path), Numeros({}))
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
        f"{deck.RESULTADOS}  /  CONCLUSÃO",
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
            "Distância a A e B",
            "Vínculos antes da eleição de 2024",
            "doações de seus sócios ou administradores",
            "Para cada fornecedora anterior",
            "fatia dos empenhos de 2025",
        )
    )
    rede = " ".join(forma.text_frame.text for forma in prs.slides[5].shapes if forma.has_text_frame)
    assert all(termo in rede for termo in ("Receita Federal", "TSE", "TCESP", "maior componente"))
    assert "Calculamos as ligações com A e B em cada município" in rede
    hipoteses, resultados, distancia, conclusao = (
        " ".join(
            forma.text_frame.text for forma in prs.slides[indice].shapes if forma.has_text_frame
        )
        for indice in (3, 6, 7, 8)
    )
    assert all(
        termo in hipoteses
        for termo in ("Prefeito candidato", "ruptura", "Adversário mais votado", "1º turno")
    )
    assert "A e B são definidos em cada município" in hipoteses
    assert hipoteses.index("H1") < hipoteses.index("H2")
    assert "teste principal" in resultados.lower()
    assert "contraste h1" in resultados.lower()
    assert "pontos percentuais da fatia dos empenhos de 2025 no elemento de despesa" in resultados
    assert "H3" not in " ".join((hipoteses, resultados, distancia, conclusao))
    assert "H4" not in " ".join((hipoteses, resultados, distancia, conclusao))
    assert "H4" not in notas[6].fala
    assert any("H4" in ponto for ponto in notas[6].apoio)
    assert "exploratóri" not in distancia.lower()
    assert "sinal negativo" in distancia.lower()
    assert "oposto à vantagem prevista por h2" in distancia.lower()
    assert "Testar se o efeito diminui exige comparar as faixas entre si." in distancia
    assert "pontos percentuais da fatia dos empenhos no elemento de despesa" in distancia
    assert "pontos percentuais da fatia dos empenhos no elemento de despesa" in conclusao
    assert conclusao.count("EM ABERTO") == 2
    assert "exploratóri" not in conclusao.lower()
    assert "Contraste entre coortes a 1 passo em 2025" in conclusao
    assert "PLACEBO PRÉ-ELEITORAL · SÓ A COORTE B" in conclusao
    titulos = [slide.shapes[0].text_frame.text for slide in list(prs.slides)[-2:]]
    assert "distância" in titulos[0]
    assert "concluir" in titulos[1]


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
