from pathlib import Path

import polars as pl

from redes.config import SUPRESSAO_MINIMA
from redes.descritivas import FAIXAS_TAMANHO

PASTA = Path(__file__).resolve().parents[1] / "results" / "tables"


def test_resultados_versionados_nao_divulgam_contagens_pequenas():
    contagens = {
        "ambiguidade_rfb": ("pessoas", "vinculos"),
        "qualificacoes_rfb": ("linhas",),
        "rede_componentes": ("componentes", "empresas"),
        "rede_distancias": ("pares_empresa_municipio",),
        "rede_graus": ("vertices",),
        "permanencia_h4": ("n_municipios",),
        "mercados_sem_empenho": ("observacoes", "sem_empenho"),
        "validacao_rfb": ("valor",),
        "validacao_tse": ("valor",),
    }
    for arquivo in PASTA.glob("*.csv"):
        tabela = pl.read_csv(arquivo, infer_schema_length=None)
        colunas = contagens.get(arquivo.stem, ())
        colunas += tuple(
            c for c in tabela.columns if c.startswith(("municipios_", "unidades_", "redes_"))
        )
        indicador = None
        if arquivo.stem in ("links_pc1", "rede_resumo"):
            indicador = ~pl.col("indicador").str.contains(r"^(taxa_|fracao_)")
        elif arquivo.stem == "reconstrucao":
            indicador = ~pl.col("medida").str.starts_with("fracao_")
        elif arquivo.stem == "validacao_panel":
            indicador = pl.col("medida").str.starts_with("n_")
        elif arquivo.stem == "validacao_tcesp":
            indicador = ~pl.col("medida").str.contains(
                r"^(valor($|_)|descarte_valor$|escopo_|vinculacao_)"
            )
        if indicador is not None:
            tabela = tabela.filter(indicador)
            colunas += ("valor",)
        for coluna in colunas:
            assert tabela.filter(
                pl.col(coluna).cast(pl.Float64, strict=False).is_between(1, SUPRESSAO_MINIMA - 1)
            ).is_empty(), (arquivo.name, coluna)


def test_suprimir_uma_faixa_de_rede_nao_deixa_um_resto_exato():
    medidas = (
        ("rede_componentes", ("variante",), "componentes"),
        ("rede_componentes", ("variante",), "empresas"),
        ("rede_graus", ("variante", "vertice"), "vertices"),
        ("rede_distancias", ("variante", "grupo"), "pares_empresa_municipio"),
        ("qualificacoes_rfb", ("vinculo",), "linhas"),
        ("ambiguidade_rfb", ("tipo_socio",), "pessoas"),
    )
    for arquivo, chaves, coluna in medidas:
        tabela = pl.read_csv(PASTA / f"{arquivo}.csv")
        nulas = tabela.group_by(*chaves).agg(
            ocultas=pl.col(coluna).null_count(), publicadas=pl.col(coluna).sum()
        )
        assert nulas.filter((pl.col("ocultas") == 1) & (pl.col("publicadas") > 0)).is_empty()


def test_perfil_publicado_de_componentes_usa_faixas_agregadas_sem_lacunas():
    tabela = pl.read_csv(PASTA / "rede_componentes.csv")
    for _, perfil in tabela.group_by("variante"):
        assert tuple(perfil["faixa_tamanho"]) == FAIXAS_TAMANHO
        assert perfil["componentes"].null_count() in (0, perfil.height)
        assert perfil["empresas"].is_null().equals(perfil["componentes"].is_null())


def test_totais_da_receita_nao_revelam_soma_pequena_das_qualificacoes_ocultas():
    qualificacoes = pl.read_csv(PASTA / "qualificacoes_rfb.csv")
    validacao = pl.read_csv(PASTA / "validacao_rfb.csv").filter(pl.col("medida") == "socios_linhas")
    for (vinculo,), grupo in qualificacoes.group_by("vinculo"):
        if not grupo["linhas"].null_count():
            continue
        totais = validacao.filter(
            pl.col("categoria").str.split_exact("_", 1).struct.field("field_1") == vinculo
        )["valor"]
        if totais.len() and not totais.null_count():
            assert totais.sum() - grupo["linhas"].sum() >= SUPRESSAO_MINIMA
