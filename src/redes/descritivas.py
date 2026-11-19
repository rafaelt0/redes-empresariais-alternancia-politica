"""Descritivas de rede da seção 5 do projeto: componentes, graus, articulação e distâncias.

Só agregados, uma linha por variante e categoria; contagens entre 1 e `SUPRESSAO_MINIMA - 1`
saem nulas. O erro de reconstrução é calculado na ingestão da Receita.
"""

from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import numpy as np
import polars as pl

from redes import config
from redes.schemas import FAIXA, VARIANTE

FAIXAS_TAMANHO = ("1", "2", "3+")
CORTES_TAMANHO = (2, 3)
FAIXAS_GRAU = ("0", "1", "2", "3-5", "6-10", "11+")
CORTES_GRAU = (1, 2, 3, 6, 11)
ARQUIVOS = ("rede_resumo", "rede_componentes", "rede_graus", "rede_distancias")


def suprimir(coluna: str) -> pl.Expr:
    contagem = pl.col(coluna)
    return (
        pl.when(contagem.is_between(1, config.SUPRESSAO_MINIMA - 1))
        .then(None)
        .otherwise(contagem)
        .alias(coluna)
    )


def suprimir_particao(
    tabela: pl.DataFrame,
    colunas: tuple[str, ...],
    *chaves: str,
    complementar_sempre: bool = False,
) -> pl.DataFrame:
    """Protege as contagens da partição e as colunas associadas contra subtração do total."""
    pequena = pl.any_horizontal(
        pl.col(c).is_null() | pl.col(c).is_between(1, config.SUPRESSAO_MINIMA - 1) for c in colunas
    )
    principal = pl.col(colunas[0])
    n_ocultas = pequena.sum()
    complemento = principal.filter(~pequena & (principal > 0)).min()
    if chaves:
        n_ocultas = n_ocultas.over(chaves)
        complemento = complemento.over(chaves)
    precisa_complemento = n_ocultas > 0 if complementar_sempre else n_ocultas == 1
    ocultar = pequena | (precisa_complemento & (principal == complemento)).fill_null(False)
    return tabela.with_columns(pl.when(~ocultar).then(pl.col(c)).alias(c) for c in colunas)


def _por_faixa(
    valores: np.ndarray,
    cortes: tuple[int, ...],
    rotulos: tuple[str, ...],
    nome: str,
    **somas: np.ndarray | None,
) -> pl.DataFrame:
    """Soma de cada vetor de `somas` por faixa de `valores` (`None` conta os valores), com zero
    nas faixas vazias."""
    faixa = np.searchsorted(cortes, valores, side="right")
    return pl.DataFrame(
        {
            nome: rotulos,
            **{
                coluna: np.bincount(faixa, weights=pesos, minlength=len(rotulos)).astype(np.int64)
                for coluna, pesos in somas.items()
            },
        }
    )


def componentes(rede: pl.DataFrame) -> pl.DataFrame:
    """`id_rede` numera os componentes de 0 em diante, sem lacunas."""
    tamanho = np.bincount(rede["id_rede"].to_numpy())
    return _por_faixa(
        tamanho,
        CORTES_TAMANHO,
        FAIXAS_TAMANHO,
        "faixa_tamanho",
        componentes=None,
        empresas=tamanho,
    )


def graus(grau_empresa: np.ndarray, grau_pessoa: np.ndarray) -> pl.DataFrame:
    """Grau de cada empresa do universo (pessoas distintas, zero inclusive) e de cada pessoa com
    algum vínculo na variante (empresas distintas)."""
    return pl.concat(
        _por_faixa(grau, CORTES_GRAU, FAIXAS_GRAU, "faixa_grau", vertices=None).select(
            pl.lit(tipo).alias("vertice"), pl.all()
        )
        for tipo, grau in (("empresa", grau_empresa), ("pessoa", grau_pessoa))
    )


def faixas_de_distancia(distancias: pl.DataFrame, origens: pl.DataFrame) -> pl.DataFrame:
    """Pares (fornecedora, município) por grupo e faixa de δ, onde há conexão direta ao grupo."""
    busca = ["cod_municipio_tse", "grupo"]
    contagem = (
        distancias.join(origens.select(busca).unique(), on=busca, how="semi")
        .group_by(pl.col("grupo").cast(pl.String), pl.col("faixa").cast(pl.String))
        .agg(pares_empresa_municipio=pl.len())
    )
    grade = pl.DataFrame({"grupo": ["A", "B"]}).join(
        pl.DataFrame({"faixa": FAIXA.categories}), how="cross"
    )
    return grade.join(contagem, on=["grupo", "faixa"], how="left").fill_null(0)


def resumo(
    rede: pl.DataFrame,
    grau_pessoa: np.ndarray,
    origens: pl.DataFrame,
    articulacao: int,
    componentes_de_um_socio: int,
) -> pl.DataFrame:
    maior = rede["empresas_na_rede"].max() or 0
    linhas = {
        "empresas": rede.height,
        "pessoas": len(grau_pessoa),
        "vinculos": int(grau_pessoa.sum()),
        "componentes": rede["id_rede"].n_unique(),
        "empresas_no_maior_componente": maior,
        "pessoas_ponto_de_articulacao": articulacao,
        "componentes_duas_empresas_um_socio": componentes_de_um_socio,
        "municipios_com_conexao_a": origens.filter(pl.col("grupo") == "A")[
            "cod_municipio_tse"
        ].n_unique(),
        "municipios_com_conexao_b": origens.filter(pl.col("grupo") == "B")[
            "cod_municipio_tse"
        ].n_unique(),
    }
    contagens = pl.DataFrame(
        {"indicador": list(linhas), "valor": list(linhas.values())},
        schema={"indicador": pl.String, "valor": pl.Int64},
    ).with_columns(suprimir("valor").cast(pl.Float64))
    fracao = maior / rede.height if rede.height and maior >= config.SUPRESSAO_MINIMA else None
    return pl.concat(
        [
            contagens,
            pl.DataFrame(
                {"indicador": ["fracao_no_maior_componente"], "valor": [fracao]},
                schema=contagens.schema,
            ),
        ]
    )


def da_variante(
    rede: pl.DataFrame,
    grau_empresa: np.ndarray,
    grau_pessoa: np.ndarray,
    distancias: pl.DataFrame,
    origens: pl.DataFrame,
    articulacao: int,
    componentes_de_um_socio: int,
) -> dict[str, pl.DataFrame]:
    """As quatro tabelas de uma variante, já com supressão, na ordem de `ARQUIVOS`.

    `grau_empresa` vale para cada empresa de `rede`; `grau_pessoa`, para cada pessoa com algum
    vínculo na variante."""
    faixas = componentes(rede)
    tabelas = (
        resumo(rede, grau_pessoa, origens, articulacao, componentes_de_um_socio),
        faixas,
        suprimir_particao(graus(grau_empresa, grau_pessoa), ("vertices",), "vertice"),
        suprimir_particao(
            faixas_de_distancia(distancias, origens), ("pares_empresa_municipio",), "grupo"
        ),
    )
    if faixas["componentes"].is_between(1, config.SUPRESSAO_MINIMA - 1).any():
        # Totais, graus e faixas vazias podem reconstituir uma célula rara em conjunto.
        # Oculta todo o perfil numérico da variante, inclusive os zeros.
        tabelas = tuple(
            tabela.with_columns(pl.lit(None, dtype=tabela.schema[c]).alias(c) for c in colunas)
            for tabela, colunas in zip(
                tabelas,
                (
                    ("valor",),
                    ("componentes", "empresas"),
                    ("vertices",),
                    ("pares_empresa_municipio",),
                ),
                strict=True,
            )
        )
    return dict(zip(ARQUIVOS, tabelas, strict=True))


def gravar(por_variante: dict[str, dict[str, pl.DataFrame]], diretorio: Path) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    publicadas = {
        arquivo: pl.concat(
            tabelas[arquivo].select(pl.lit(variante, dtype=VARIANTE).alias("variante"), pl.all())
            for variante, tabelas in por_variante.items()
        )
        for arquivo in ARQUIVOS
    }
    publicadas["rede_graus"] = graus_publicos(publicadas["rede_graus"], publicadas["rede_resumo"])
    for arquivo, tabela in publicadas.items():
        tabela.write_csv(diretorio / f"{arquivo}.csv")


def graus_publicos(tabela: pl.DataFrame, resumo_publico: pl.DataFrame) -> pl.DataFrame:
    """Protege caudas quase iguais, inclusive as recuperáveis pelos totais do resumo."""
    totais = {
        (variante, indicador): int(valor)
        for variante, indicador, valor in resumo_publico.select(
            "variante", "indicador", "valor"
        ).iter_rows()
        if indicador in ("empresas", "pessoas") and valor is not None
    }
    caudas = defaultdict(list)
    for (variante, vertice), grupo in tabela.group_by("variante", "vertice"):
        da_variante = {}
        contagens = dict(grupo.select("faixa_grau", "vertices").iter_rows())
        soma = 0
        for faixa in reversed(FAIXAS_GRAU):
            n = contagens.get(faixa)
            if n is None:
                break
            soma += n
            da_variante[faixa] = soma
        restante = totais.get((variante, f"{vertice}s"))
        if restante is not None:
            for faixa_anterior, faixa in pairwise(FAIXAS_GRAU):
                n = contagens.get(faixa_anterior)
                if n is None:
                    break
                restante -= n
                da_variante[faixa] = restante
        for faixa, soma in da_variante.items():
            caudas[vertice, faixa].append(soma)
    ocultar = {
        vertice
        for (vertice, _), contagens in caudas.items()
        if any(0 < b - a < config.SUPRESSAO_MINIMA for a, b in pairwise(sorted(contagens)))
    }
    return tabela.with_columns(
        vertices=pl.when(~pl.col("vertice").is_in(ocultar)).then(pl.col("vertices"))
    )
