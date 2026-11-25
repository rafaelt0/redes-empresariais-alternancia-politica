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
    assert deck._pp_sinal(None) == "n.d."
    assert deck._pp_sinal(0.01251, 2) == "+1,25 p.p."
    assert deck._pp_sinal(0.00001, 2) == "0,00 p.p."
    assert deck._pp_sinal(-0.0406, 2) == "-4,06 p.p."


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
    assert sum(nota.segundos for nota in notas) == 540
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
    assert set(por_bloco.values()) == {135}
    assert "9:00" in texto
    assert "1:00" in texto

    roteiros = deck.guias_individuais(notas, titulos)
    for i, (nome, slides) in enumerate(
        (("Andrei", "1–3"), ("Felipe", "4–5"), ("João Pedro", "6–7"), ("Rafael", "8–9")),
        start=1,
    ):
        arquivo = f"guia_voz_{i}.md"
        assert f"[Voz {i} · {nome}]({arquivo})" in texto
        assert f"| {slides} | 2:15 |" in texto
        roteiro = roteiros[arquivo]
        assert roteiro.startswith(f"# Voz {i} · {nome}\n")
        assert "2:15)" in roteiro
        assert "**Na fala**" in roteiro
        assert "**Se perguntarem**" in roteiro
        for j, nota in enumerate(notas, start=1):
            if nota.pessoa == f"Voz {i}":
                assert f"## Slide {j} · {titulos[j - 1]}" in roteiro
                assert nota.fala in roteiro
                for ponto in nota.apoio:
                    assert f"- {ponto}" in roteiro
            else:
                assert f"## Slide {j} ·" not in roteiro


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
    assert documento.xpath("//p[@class='duracao']/text()") == ["2:15 de fala"] * 4
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
        }
    ).write_csv(tabelas / "resumo_estimacao.csv")
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
    assert "H3" not in textos


def test_tema_hyperlink_e_marcadores_sem_estilo(tmp_path: Path) -> None:
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.oxml.ns import qn

    prs, _ = deck.construir(_caminhos(tmp_path), Numeros({}))
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    cores = []
    for rel in prs.slide_masters[0].part.rels.values():
        if "theme" in rel.reltype:
            raiz = etree.fromstring(rel.target_part.blob)
            for tag in ("hlink", "folHlink"):
                no = raiz.find(f".//a:clrScheme/a:{tag}/a:srgbClr", ns)
                assert no is not None
                cores.append(no.get("val"))
    assert cores == ["862F3D", "862F3D"]

    for idx in (6, 7, 8):
        ovais = [forma for forma in prs.slides[idx].shapes if forma.shape_type == MSO_SHAPE.OVAL]
        for oval in ovais:
            assert oval._element.find(qn("p:style")) is None


def test_deck_contextualiza_o_emd_de_h1_com_a_coorte_direta(tmp_path: Path) -> None:
    caminhos = _caminhos(tmp_path)
    tabelas = caminhos.resultados / "tables"
    tabelas.mkdir(parents=True)
    pl.DataFrame(
        {
            "hipotese": ["H1", "H1", "H1"],
            "categoria": [
                "conectada_incumbente",
                "sem_conexao",
                "conectada_menos_sem_conexao",
            ],
            "tipo": ["categoria", "categoria", "contraste"],
            "resultado": ["participacao_2025"] * 3,
            "estimativa": [-0.0157, 0.0014, -0.0171],
            "ic_inf": [-0.1236, -0.0009, -0.1619],
            "ic_sup": [0.0923, 0.0037, 0.1277],
            "banda": [20.5644, 24.2404, 20.5644],
            "municipios_tratados": [25, 122, None],
            "municipios_controle": [31, 159, None],
            "emd": [None, None, 0.20698382950514996],
        }
    ).write_csv(tabelas / "resumo_estimacao.csv")
    pl.DataFrame(
        {
            "categoria": ["faixa_b_0", "faixa_a_0"],
            "banda": [28.8055, 20.5644],
            "media_participacao_2025": [0.028357186282778078, 0.017703287989352376],
            "dp_participacao_2025": [0.14759152592236377, 0.09867751401605772],
        }
    ).write_csv(tabelas / "descritivas_estimacao.csv")
    prs, notas = deck.construir(caminhos, Numeros({}))
    slide = " ".join(
        forma.text_frame.text for forma in prs.slides[6].shapes if forma.has_text_frame
    )
    assert "Efeito mínimo detectável: 20,7 p.p." in slide
    assert "Equivale a 11,7 vezes a fatia média (1,77%)" in slide
    assert "Ligadas a A · 25 municípios com derrota e 31 com vitória" in slide
    assert "20,7 p.p., que equivale a 11,7 vezes a fatia média (1,77%)" in notas[6].fala
    assert "25 municípios com A derrotado e 31 com A vitorioso" in notas[6].fala

    (tabelas / "descritivas_estimacao.csv").unlink()
    prs, _ = deck.construir(caminhos, Numeros({}))
    slide_sem_contexto = " ".join(
        forma.text_frame.text for forma in prs.slides[6].shapes if forma.has_text_frame
    )
    assert "Efeito mínimo detectável: 20,7 p.p." in slide_sem_contexto
    assert "Equivale a" not in slide_sem_contexto


def test_slides_h2_separam_contraste_em_2025_do_pos_menos_pre(tmp_path: Path) -> None:
    caminhos = _caminhos(tmp_path)
    tabelas = caminhos.resultados / "tables"
    tabelas.mkdir(parents=True)
    pl.DataFrame(
        {
            "hipotese": ["H2", "H2", "H2", "H2"],
            "categoria": ["vencedor_faixa_1", "faixa_b_1", "faixa_a_1", "vencedor_faixa_3+"],
            "tipo": ["contraste", "categoria", "categoria", "contraste"],
            "resultado": ["participacao_2025"] * 4,
            "estimavel": [True, True, True, True],
            "estimativa": [-0.0406, -0.0807, 0.0006, 0.0005],
            "ic_inf": [-0.0716, -0.1355, -0.0076, 0.0000],
            "ic_sup": [-0.0097, -0.0260, 0.0087, 0.0011],
            "municipios_tratados": [None, 11, 12, None],
            "municipios_controle": [None, 17, 13, None],
            "placebo_estimativa": [-0.0505, -0.1100, -0.0090, None],
        }
    ).write_csv(tabelas / "resumo_estimacao.csv")
    pl.DataFrame(
        {
            "hipotese": ["H2", "H2"],
            "categoria": ["vencedor_faixa_1", "faixa_b_1"],
            "tipo": ["contraste", "categoria"],
            "resultado": ["variacao_pre_periodos"] * 2,
            "placebo": [True, True],
            "estimavel": [True, True],
            "estimativa": [-0.0312, -0.0768],
            "ic_inf": [-0.0800, -0.1350],
            "ic_sup": [0.0200, -0.0186],
        }
    ).write_csv(tabelas / "sensibilidade_pre_periodos.csv")
    pl.DataFrame(
        {
            "hipotese": ["H2"],
            "categoria": ["vencedor_faixa_1"],
            "tipo": ["contraste"],
            "resultado": ["variacao_participacao"],
            "placebo": [False],
            "estimavel": [True],
            "estimativa": [0.0125],
            "ic_inf": [-0.0408],
            "ic_sup": [0.0658],
        }
    ).write_csv(tabelas / "sensibilidade_placebo.csv")
    pl.DataFrame(
        {
            "hipotese": ["H2"],
            "categoria": ["vencedor_faixa_1"],
            "tipo": ["contraste"],
            "resultado": ["participacao_2025"],
            "estimavel": [True],
            "estimativa": [-0.0285],
            "ic_inf": [-0.0625],
            "ic_sup": [0.0055],
        }
    ).write_csv(tabelas / "sensibilidade_sem_autofinanciamento.csv")
    pl.DataFrame(
        {
            "recorte": ["principal", "principal", "principal"],
            "faixa": ["1", "1", "3+"],
            "grupo": ["B", "A", "A"],
            "janela": ["h", "h", "h"],
            "fracao_peso_gigante": [0.6668, 0.6046, 0.9999],
            "piso_fracao_observacoes": [None, None, 0.99],
        }
    ).write_csv(tabelas / "concentracao_gigante_h2.csv")
    pl.DataFrame(
        {
            "hipotese": ["H2"],
            "categoria": ["vencedor_faixa_1"],
            "tipo": ["contraste"],
            "resultado": ["participacao_2025"],
            "placebo": [False],
            "estimavel": [False],
            "motivo": ["menos de 10 municípios de um lado do corte"],
        }
    ).write_csv(tabelas / "h2_comparaveis.csv")
    prs, notas = deck.construir(caminhos, Numeros({}))
    distancia = " ".join(
        forma.text_frame.text for forma in prs.slides[7].shapes if forma.has_text_frame
    )
    conclusao = " ".join(
        forma.text_frame.text for forma in prs.slides[8].shapes if forma.has_text_frame
    )
    assert "A um passo" in distancia
    assert "-4,06 p.p." in distancia
    assert "IC de 95% de -7,16 a -0,97 p.p." in distancia
    assert "Sinal oposto ao previsto" in distancia
    assert "A coorte B já apresentava um salto negativo antes da eleição." in distancia
    assert "-8,07 p.p." not in distancia
    assert "11/17 em B e 12/13 em A" in notas[7].texto()
    assert "estratos comparáveis" in notas[7].texto()
    assert "A 1 passo, pós − pré (2025 − 2021–24)" in conclusao
    assert "+1,25 p.p." in conclusao
    assert "IC de 95% de -4,08 a 6,58 p.p." in conclusao
    assert "O intervalo inclui zero. O efeito da distância segue em aberto." in conclusao
    assert "-4,06 p.p." not in conclusao
    assert "o recorte comparável por estratos fica sem suporte a um passo" in notas[7].fala
    assert "vira +1,25 p.p. na variação pós menos pré" in notas[8].fala

    (tabelas / "sensibilidade_placebo.csv").unlink()
    prs_fallback, _ = deck.construir(caminhos, Numeros({}))
    conclusao_fallback = " ".join(
        forma.text_frame.text for forma in prs_fallback.slides[8].shapes if forma.has_text_frame
    )
    assert "A 1 passo, variação pré-eleitoral (2023–24 vs. 2021–22)" in conclusao_fallback
    assert "-3,12 p.p." in conclusao_fallback
    assert "IC de 95% de -8,00 a 2,00 p.p." in conclusao_fallback


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
            "Distância ao incumbente e ao adversário (H2)",
            "Vínculos antes da eleição de 2024",
            "ADI 4650",
            "doações de sócios ou administradores (PF)",
            "Para cada fornecedora anterior",
            "fatia no saldo líquido dos empenhos de 2025",
            "entrantes no denominador",
        )
    )
    rede = " ".join(forma.text_frame.text for forma in prs.slides[5].shapes if forma.has_text_frame)
    assert all(termo in rede for termo in ("Receita Federal", "TSE", "TCESP", "maior componente"))
    assert "Órgãos municipais cobertos pelo TCESP, exceto a capital" in rede
    assert "saldo líquido por elemento" in rede
    assert "entrantes no denominador" in rede
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
    assert (
        "Categorias: IC robusto analítico (CCT); contraste: reamostragem municipal (999 réplicas)."
        in resultados
    )
    assert "H3" not in " ".join((hipoteses, resultados, distancia, conclusao))
    assert "H4" not in " ".join((hipoteses, resultados, distancia, conclusao))
    assert "H4" not in notas[6].fala
    assert any("H4" in ponto for ponto in notas[6].apoio)
    assert "análise exploratória" in distancia.lower()
    assert "Testar o gradiente exige comparar as faixas entre si." in distancia
    assert "pontos percentuais da fatia dos empenhos no elemento de despesa" in distancia
    assert "pontos percentuais da fatia dos empenhos no elemento de despesa" in conclusao
    assert "H1 / Ligação direta" in conclusao
    assert "H2 / Distância ao vencedor" in conclusao
    assert "LIMITAÇÕES" in conclusao
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
