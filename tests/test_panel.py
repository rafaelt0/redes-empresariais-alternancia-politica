from datetime import date

import duckdb
import polars as pl
import pytest

from redes import etapas, panel, schemas
from redes.schemas import (
    DISTANCIAS,
    ELEICOES,
    EMPENHOS,
    LICITACOES,
    PAINEL_FIRMA,
    PAINEL_REDE,
    REDE,
)

M1, M2, FORA = "90001", "90002", "90099"
F1, F2, F3, F4, F5 = (f"{n:08d}" for n in range(1, 6))


class Eventos:
    """Eventos de empenho montados à mão; cada chamada é um evento de um empenho novo."""

    def __init__(self) -> None:
        self.linhas: list[dict] = []

    def add(
        self,
        cnpj: str,
        data: date,
        valor: float,
        municipio: str = M1,
        elemento: str = "30",
        ajuste: str | None = None,
        empenho: str | None = None,
    ) -> str:
        empenho = empenho or f"E{len(self.linhas)}"
        evento = "ANULACAO" if valor < 0 else "EMISSAO"
        self.linhas.append(
            {
                "id_evento": f"{empenho}-{len(self.linhas)}",
                "id_empenho": empenho,
                "evento": evento,
                "data": data,
                "cod_municipio_tse": municipio,
                "cnpj_basico": cnpj,
                "elemento_despesa": elemento,
                "natureza_despesa": None,
                "tipo_orgao": None,
                "valor": valor,
                "id_ajuste": ajuste,
            }
        )
        return empenho

    def frame(self) -> pl.DataFrame:
        frame = pl.DataFrame(self.linhas, schema=EMPENHOS.esquema, orient="row")
        schemas.validar(frame, EMPENHOS)
        return frame


def licitacoes(*ajustes: tuple[str, date]) -> pl.DataFrame:
    return pl.DataFrame(
        [(a, M1, None, "CONTRATO", d, None) for a, d in ajustes],
        schema=LICITACOES.esquema,
        orient="row",
    )


def eleicoes(*municipios: str) -> pl.DataFrame:
    return pl.DataFrame(
        [(m, "PREFEITO", "1", "2", 1000, -1.0 + i, int(i < 1)) for i, m in enumerate(municipios)],
        schema=ELEICOES.esquema,
        orient="row",
    )


def distancias(*linhas: tuple[str, str, str, str]) -> pl.DataFrame:
    """(município, grupo, CNPJ, faixa) da variante principal."""
    return pl.DataFrame(
        [("PRINCIPAL", m, g, c, None, f) for m, g, c, f in linhas],
        schema=DISTANCIAS.esquema,
        orient="row",
    )


def rede(*linhas: tuple[str, int]) -> pl.DataFrame:
    return pl.DataFrame(
        [("PRINCIPAL", c, r, 1) for c, r in linhas], schema=REDE.esquema, orient="row"
    )


def agregar(
    eventos: Eventos, ajustes: pl.DataFrame | None = None, municipios=(M1, M2)
) -> pl.DataFrame:
    with duckdb.connect() as con:
        con.register("empenhos", eventos.frame())
        con.register("licitacoes", ajustes if ajustes is not None else licitacoes())
        con.register("eleicoes", eleicoes(*municipios))
        return panel.agregar_empenhos(con)


def firma(
    agregado: pl.DataFrame,
    dist: pl.DataFrame | None = None,
    componentes: pl.DataFrame | None = None,
    municipios=(M1, M2),
) -> pl.DataFrame:
    saida = panel.painel_firma(
        agregado,
        dist if dist is not None else distancias(),
        componentes if componentes is not None else rede(),
        eleicoes(*municipios),
        "PRINCIPAL",
    )
    schemas.validar(saida, PAINEL_FIRMA)
    return saida


def linha(frame: pl.DataFrame, **filtro) -> dict:
    (resultado,) = frame.filter(**filtro).iter_rows(named=True)
    return resultado


def test_empenho_liquido_de_anulacao_e_reforco_na_janela():
    e = Eventos()
    # F1: anulação parcial e reforço em outro ano do mesmo empenho.
    emp = e.add(F1, date(2022, 3, 1), 100.0)
    e.add(F1, date(2022, 3, 10), -40.0, empenho=emp)
    e.add(F1, date(2023, 5, 2), 10.0, empenho=emp)
    # F2: anulação maior que a emissão; não é fornecedora anterior.
    emp = e.add(F2, date(2021, 6, 1), 100.0)
    e.add(F2, date(2021, 7, 1), -130.0, empenho=emp)
    # F3: o último dia da janela entra, outubro de 2024 não.
    e.add(F3, date(2024, 9, 30), 50.0)
    e.add(F3, date(2024, 10, 1), 999.0)
    e.add(F3, date(2022, 1, 5), 25.0, municipio=FORA)

    agregado = agregar(e)
    f1 = linha(agregado, cnpj_basico=F1)
    assert (f1["pre_2022"], f1["pre_2023"]) == (60.0, 10.0)
    assert linha(agregado, cnpj_basico=F2)["pre_2021"] == -30.0
    assert linha(agregado, cnpj_basico=F3)["pre_2024"] == 50.0
    assert agregado.filter(cod_municipio_tse=FORA).is_empty()

    painel = firma(agregado)
    assert painel["cnpj_basico"].to_list() == [F1, F3]
    assert linha(painel, cnpj_basico=F1)["empenhado_pre"] == 70.0
    assert linha(painel, cnpj_basico=F1)["participacao_pre"] == pytest.approx(70 / 120)


def test_empenho_novo_e_o_vinculado_a_ajuste_a_partir_da_posse():
    e = Eventos()
    e.add(F1, date(2023, 2, 1), 100.0)
    novo = e.add(F1, date(2025, 3, 1), 80.0, ajuste="NOVO")
    e.add(F1, date(2025, 4, 1), -10.0, ajuste="NOVO", empenho=novo)
    e.add(F1, date(2025, 3, 1), 20.0, ajuste="ANTIGO")
    e.add(F1, date(2025, 5, 1), 5.0)
    ajustes = licitacoes(("NOVO", date(2025, 1, 1)), ("ANTIGO", date(2024, 12, 20)))

    agregado = agregar(e, ajustes)
    f1 = linha(agregado, cnpj_basico=F1)
    assert (f1["empenhado_2025"], f1["vinculado_2025"], f1["empenhado_novo_2025"]) == (
        95.0,
        90.0,
        70.0,
    )
    suporte = dict(ligados=2, sem_ajuste=1, novos=1, nao_novos=2, anteriores=1)
    taxas = dict(panel.vinculacao(agregado, suporte).select("medida", "valor").iter_rows())
    assert taxas == {"vinculacao_valor_2025": None, "novo_valor_2025": None}
    assert linha(firma(agregado), cnpj_basico=F1)["empenhado_novo_2025"] == 70.0


def test_taxa_de_novos_oculta_valor_de_poucos_empenhos_ligados_a_ajustes_anteriores():
    e = Eventos()
    for _ in range(5):
        e.add(F1, date(2025, 3, 1), 100.0, ajuste="NOVO")
        e.add(F1, date(2025, 3, 1), 20.0)
    antigo = e.add(F1, date(2025, 3, 1), 60.0, ajuste="ANTIGO")
    for _ in range(5):
        e.add(F1, date(2025, 4, 1), -1.0, ajuste="ANTIGO", empenho=antigo)
    e.add(F1, date(2025, 3, 1), 40.0, ajuste="ANTIGO", municipio=FORA)
    with duckdb.connect() as con:
        con.register("empenhos", e.frame())
        con.register(
            "licitacoes", licitacoes(("NOVO", date(2025, 1, 1)), ("ANTIGO", date(2024, 12, 20)))
        )
        con.register("eleicoes", eleicoes(M1))
        agregado = panel.agregar_empenhos(con)
        suporte = panel.suporte_vinculacao(con)
    assert suporte == dict(ligados=6, sem_ajuste=5, novos=5, nao_novos=6, anteriores=1)
    taxas = dict(panel.vinculacao(agregado, suporte).select("medida", "valor").iter_rows())
    assert taxas == {"vinculacao_valor_2025": 555 / 655, "novo_valor_2025": None}
    taxas = dict(
        panel.vinculacao(agregado, dict.fromkeys(suporte, 5)).select("medida", "valor").iter_rows()
    )
    assert taxas["novo_valor_2025"] == 500 / 655


def test_participacoes_somam_1_por_municipio_e_elemento():
    e = Eventos()
    for cnpj, pre, em_2025 in ((F1, 300.0, 100.0), (F2, 100.0, 50.0), (F3, 200.0, -20.0)):
        e.add(cnpj, date(2022, 4, 1), pre)
        emp = e.add(cnpj, date(2025, 4, 1), max(em_2025, 0) + 30)
        e.add(cnpj, date(2025, 6, 1), min(em_2025, 0) - 30, empenho=emp)
    # F4 só entra em 2025: fica fora do painel, mas no denominador de 2025.
    e.add(F4, date(2025, 2, 1), 50.0)
    # Elemento sem empenho em 2025: a fornecedora anterior segue na amostra, com participação zero.
    e.add(F1, date(2023, 4, 1), 10.0, elemento="39")

    painel = firma(agregar(e))
    elemento_30 = painel.filter(elemento_despesa="30")
    assert elemento_30["cnpj_basico"].to_list() == [F1, F2, F3]
    assert elemento_30["participacao_pre"].sum() == pytest.approx(1)
    assert elemento_30["participacao_2025"].to_list() == pytest.approx([0.5, 0.25, 0.0])
    assert elemento_30["participacao_2025"].sum() + 50 / 200 == pytest.approx(1)
    assert linha(painel, cnpj_basico=F3)["empenhado_2025"] == -20.0
    sem_empenho = linha(painel, elemento_despesa="39")
    assert sem_empenho["participacao_2025"] == 0.0
    assert sem_empenho["participacao_pre"] == 1.0


def test_pesos_dao_a_cada_municipio_o_mesmo_total():
    e = Eventos()
    for i, cnpj in enumerate((F1, F2, F3)):
        e.add(cnpj, date(2022, 1, 3), 100.0 + i, municipio=M1)
        e.add(cnpj, date(2022, 1, 3), 50.0, municipio=M1, elemento="39")
    e.add(F4, date(2022, 1, 3), 70.0, municipio=M2)
    painel = firma(agregar(e))
    pesos = painel.group_by("cod_municipio_tse").agg(pl.col("peso").sum())
    assert pesos["peso"].to_list() == pytest.approx([1.0, 1.0])
    assert painel.group_by("cod_municipio_tse").len().sort("len")["len"].to_list() == [1, 6]


def test_faixas_e_rede_de_quem_falta_na_rede_ou_nas_distancias():
    e = Eventos()
    for cnpj in (F1, F2, F5):
        e.add(cnpj, date(2022, 1, 3), 100.0)
    dist = distancias(
        (M1, "A", F1, "0"), (M1, "B", F1, "2"), (M1, "A", F2, "3+"), (M1, "B", F2, "inf")
    )
    painel = firma(agregar(e), dist, rede((F1, 7), (F2, 7)))
    assert linha(painel, cnpj_basico=F1) | {} == linha(painel, cnpj_basico=F1)
    assert [(r["id_rede"], r["faixa_a"], r["faixa_b"]) for r in painel.iter_rows(named=True)] == [
        (7, "0", "2"),
        (7, "3+", "inf"),
        (-6, "inf", "inf"),
    ]


def test_paineis_da_amostra(caminhos_amostra):
    for nome in ("elections", "links", "network", "panel"):
        etapas.rodar(nome, caminhos_amostra)
    firma_ = schemas.ler(PAINEL_FIRMA, caminhos_amostra.dados).collect()
    rede_ = schemas.ler(PAINEL_REDE, caminhos_amostra.dados).collect()
    assert set(firma_["variante"]) == set(rede_["variante"]) == set(schemas.VARIANTE.categories)

    somas = firma_.group_by("variante", "cod_municipio_tse", "elemento_despesa").agg(
        pl.col("participacao_pre").sum()
    )
    assert somas["participacao_pre"].to_numpy() == pytest.approx(1)
    for painel in (firma_, rede_):
        pesos = painel.group_by("variante", "cod_municipio_tse").agg(pl.col("peso").sum())
        assert pesos["peso"].to_numpy() == pytest.approx(1)

    # Figura 1: X, Y e Z formam uma rede ligada aos dois grupos; X é R1.
    figura = firma_.filter(variante="PRINCIPAL", cod_municipio_tse="90001")
    redes_xyz = figura.filter(pl.col("cnpj_basico").is_in(["00000001", "00000002", "00000003"]))
    (id_xyz,) = redes_xyz["id_rede"].unique().to_list()
    assert linha(rede_, variante="PRINCIPAL", cod_municipio_tse="90001", id_rede=id_xyz)[
        "ligacao"
    ] == ("AMBOS")
    validacao = pl.read_csv(caminhos_amostra.resultados / "tables" / "validacao_panel.csv")
    assert {"vinculacao_valor_2025", "novo_valor_2025", "n_principais_50"} <= set(
        validacao["medida"]
    )
