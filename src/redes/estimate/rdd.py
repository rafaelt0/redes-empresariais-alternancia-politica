"""Núcleo de RDD comum às hipóteses: estimativa, bandas b/2 e 2b, densidade, EMD (T13).

Especificação (5) do projeto: regressão linear local, núcleo triangular, banda MSE-ótima de
Calonico, Cattaneo e Titiunik (2014) e intervalo robusto com correção de viés, pelo `rdrobust`.

Convenções:
- o efeito estimado é o de T = 1 (o incumbente perde, M < 0). O `rdrobust` estima o lado
  x ≥ c menos o lado x < c, que é o efeito de T = 0; o sinal é invertido aqui. Empates (M = 0)
  ficam do lado de T = 0, como em `eleicoes`;
- a banda b do projeto é o `h` do rdrobust; o `b` do rdrobust é a banda do viés (`banda_vies`);
- cada município soma peso 1 em cada estimação: `peso` é renormalizado dentro do município
  depois do filtro de categoria, porque o filtro muda o total de cada município;
- a estimativa é a convencional; intervalo, erro-padrão e p-valor são os robustos.
"""

import contextlib
import io
import math
import warnings
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from statistics import NormalDist
from typing import Literal

import numpy as np
import polars as pl
from rddensity import rddensity
from rdrobust import rdrobust

from redes import config

Agrupamento = Literal["municipio", "rede"]

_NORMAL = NormalDist()
_Z_IC = _NORMAL.inv_cdf(0.975)
FATOR_EMD = _NORMAL.inv_cdf(1 - config.NIVEL_EMD / 2) + _NORMAL.inv_cdf(config.PODER_EMD)
_MINIMO = config.MINIMO_MUNICIPIOS_POR_LADO


@dataclass(frozen=True)
class Contagem:
    """Municípios e unidades de cada lado do corte; dentro da banda quando há estimativa."""

    municipios_tratados: int
    municipios_controle: int
    unidades_tratadas: int
    unidades_controle: int


@dataclass(frozen=True)
class Estimativa:
    """Efeito de T = 1. Nos contrastes, `ep_robusto` é o erro-padrão por reamostragem e as
    bandas e os p-valores de b/2 e 2b ficam NaN, porque cada categoria tem a própria banda."""

    estimativa: float
    ep_robusto: float
    ic_inf: float
    ic_sup: float
    p_valor: float
    banda: float
    banda_vies: float
    estimativa_meia_banda: float
    p_meia_banda: float
    estimativa_dobro_banda: float
    p_dobro_banda: float
    emd: float
    contagem: Contagem
    redes_por_lado: tuple[int, int] | None = None


@dataclass(frozen=True)
class NaoEstimavel:
    motivo: str
    contagem: Contagem
    redes_por_lado: tuple[int, int] | None = None


Resultado = Estimativa | NaoEstimavel


@dataclass(frozen=True)
class Densidade:
    """Teste de Cattaneo, Jansson e Ma (2020) da margem no nível do município."""

    estatistica_t: float
    p_valor: float
    banda_tratados: float
    banda_controle: float
    contagem: Contagem


@dataclass(frozen=True)
class Contraste:
    """Combinação linear dos efeitos de categorias de uma mesma tabela: Σ coeficiente × β."""

    nome: str
    coeficientes: dict[str, float]


def _amostra(painel: pl.DataFrame, resultado: str, categoria: pl.Expr | None) -> pl.DataFrame:
    """Colunas x (margem), y, w (peso renormalizado), municipio e rede, sem nulos."""
    frame = painel if categoria is None else painel.filter(categoria)
    rede = pl.col("id_rede").cast(pl.String)
    if "cnpj_basico" in frame.columns:
        # Empresa fora da rede societária forma um agrupamento só dela.
        rede = pl.coalesce(rede, pl.lit("empresa ") + pl.col("cnpj_basico"))
    return (
        frame.filter(pl.col(resultado).is_not_null())
        .select(
            pl.col("margem").alias("x"),
            pl.col(resultado).cast(pl.Float64).alias("y"),
            (pl.col("peso") / pl.col("peso").sum().over("cod_municipio_tse")).alias("w"),
            pl.col("cod_municipio_tse").alias("municipio"),
            rede.alias("rede"),
        )
        .filter(pl.col("w").is_finite() & (pl.col("w") > 0))
    )


def _contagem(amostra: pl.DataFrame, banda: float = math.inf) -> Contagem:
    """Unidades com peso de núcleo positivo, |x| < banda, como no rdrobust."""
    tratado = pl.col("x") < 0
    linha = (
        amostra.filter(pl.col("x").abs() < banda)
        .select(
            municipios_tratados=pl.col("municipio").filter(tratado).n_unique(),
            municipios_controle=pl.col("municipio").filter(~tratado).n_unique(),
            unidades_tratadas=tratado.sum(),
            unidades_controle=(~tratado).sum(),
        )
        .row(0, named=True)
    )
    return Contagem(**{k: int(v) for k, v in linha.items()})


def _poucos_municipios(contagem: Contagem) -> bool:
    return min(contagem.municipios_tratados, contagem.municipios_controle) < _MINIMO


def _redes_por_lado(amostra: pl.DataFrame, banda: float) -> tuple[int, int]:
    return (
        amostra.filter(pl.col("x").abs() < banda)
        .select(
            pl.col("rede").filter(pl.col("x") < 0).drop_nulls().n_unique().alias("tratadas"),
            pl.col("rede").filter(pl.col("x") >= 0).drop_nulls().n_unique().alias("controle"),
        )
        .row(0)
    )


def _rdrobust(amostra: pl.DataFrame, agrupamento: Agrupamento, h: float | None, b: float | None):
    """O rdrobust imprime o aviso de pontos de massa (a margem se repete dentro do município) e
    emite warnings de poucos agrupamentos; aqui a contagem dentro da banda decide."""
    grupos = np.unique(amostra[agrupamento].to_numpy(), return_inverse=True)[1]
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return rdrobust(
            amostra["y"].to_numpy(),
            amostra["x"].to_numpy(),
            c=0,
            p=1,
            kernel="triangular",
            bwselect="mserd",
            weights=amostra["w"].to_numpy(),
            cluster=grupos,
            h=h,
            b=b,
        )


def _salto(saida) -> tuple[float, float, float, float, float]:
    """(estimativa convencional, ep robusto, ic inferior, ic superior, p robusto) do efeito de
    T = 1, com o sinal invertido em relação ao rdrobust."""
    inferior, superior = saida.ci.loc["Robust"]
    return (
        -float(saida.coef.loc["Conventional"].iloc[0]),
        float(saida.se.loc["Robust"].iloc[0]),
        -float(superior),
        -float(inferior),
        float(saida.pv.loc["Robust"].iloc[0]),
    )


def _com_banda(amostra: pl.DataFrame, agrupamento: Agrupamento, h: float) -> tuple[float, float]:
    """(estimativa, p robusto) com banda fixa h, e banda do viés igual a h; NaN quando a banda
    deixa poucos municípios de um lado."""
    if _poucos_municipios(_contagem(amostra, h)):
        return math.nan, math.nan
    try:
        estimativa, _, _, _, p = _salto(_rdrobust(amostra, agrupamento, h, h))
    except Exception:  # o rdrobust levanta Exception genérica nos casos degenerados
        return math.nan, math.nan
    return estimativa, p


def estimar(
    painel: pl.DataFrame,
    resultado: str,
    categoria: pl.Expr | None = None,
    *,
    agrupamento: Agrupamento = "municipio",
    banda: tuple[float, float] | None = None,
    sensibilidades: bool = True,
) -> Resultado:
    """Efeito de T = 1 sobre `resultado` nas linhas de `painel` que satisfazem `categoria`.

    `painel` traz `margem`, `peso`, `cod_municipio_tse` e `id_rede` (mais `cnpj_basico` no painel
    de empresas). `banda` = (h, banda do viés) impõe as bandas em vez de escolhê-las.
    Casos degenerados viram `NaoEstimavel` com o motivo, sem exceção.
    """
    amostra = _amostra(painel, resultado, categoria)
    contagem = _contagem(amostra)
    if _poucos_municipios(contagem):
        return NaoEstimavel(f"menos de {_MINIMO} municípios de um lado do corte", contagem)
    if amostra["y"].n_unique() < 2:
        return NaoEstimavel("resultado sem variação", contagem)
    h, b = banda or (None, None)
    redes = None
    minimo_redes = config.MINIMO_REDES_POR_LADO
    motivo_redes = f"menos de {minimo_redes} redes de um lado"
    if agrupamento == "rede":
        corte = h if h is not None else math.inf
        redes = _redes_por_lado(amostra, corte)
        if min(redes) < minimo_redes:
            return NaoEstimavel(motivo_redes, _contagem(amostra, corte), redes)
    try:
        saida = _rdrobust(amostra, agrupamento, h, b)
    except Exception as erro:  # o rdrobust levanta Exception genérica nos casos degenerados
        return NaoEstimavel(f"rdrobust: {erro}", contagem, redes)
    h_escolhida = float(saida.bws.loc["h", "left"])
    if redes is not None and h != h_escolhida:
        redes = _redes_por_lado(amostra, h_escolhida)
        if min(redes) < minimo_redes:
            return NaoEstimavel(motivo_redes, _contagem(amostra, h_escolhida), redes)
    h = h_escolhida
    contagem = _contagem(amostra, h)
    if _poucos_municipios(contagem):
        return NaoEstimavel(
            f"menos de {_MINIMO} municípios de um lado dentro da banda", contagem, redes
        )
    estimativa, ep, inferior, superior, p = _salto(saida)
    if not (math.isfinite(ep) and ep > 0):
        return NaoEstimavel("erro-padrão degenerado", contagem, redes)
    return Estimativa(
        estimativa,
        ep,
        inferior,
        superior,
        p,
        h,
        float(saida.bws.loc["b", "left"]),
        *(_com_banda(amostra, agrupamento, h / 2) if sensibilidades else (math.nan, math.nan)),
        *(_com_banda(amostra, agrupamento, 2 * h) if sensibilidades else (math.nan, math.nan)),
        FATOR_EMD * ep,
        contagem,
        redes,
    )


def _momentos(amostra: pl.DataFrame, h: float) -> pl.DataFrame:
    """Somas por município que bastam para a regressão linear local ponderada de cada lado."""
    k = (1 - pl.col("x").abs() / h).clip(lower_bound=0) * pl.col("w")
    x, y = pl.col("x"), pl.col("y")
    return amostra.group_by("municipio").agg(
        tratado=(x < 0).first(),
        s0=k.sum(),
        s1=(k * x).sum(),
        s2=(k * x * x).sum(),
        ty=(k * y).sum(),
        txy=(k * x * y).sum(),
    )


def _intercepto(somas: np.ndarray) -> np.ndarray:
    s0, s1, s2, ty, txy = somas.T
    determinante = s0 * s2 - s1**2
    # Réplicas com um único valor da margem têm determinante zero em aritmética exata.
    valido = determinante > 32 * np.finfo(float).eps * np.maximum(s0 * s2, s1**2)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.divide(
            s2 * ty - s1 * txy, determinante, out=np.full_like(s0, np.nan), where=valido
        )


def contraste(
    painel: pl.DataFrame,
    resultado: str,
    componentes: Sequence[tuple[float, pl.Expr | None, Resultado]],
    *,
    repeticoes: int = config.REPETICOES_BOOTSTRAP,
    semente: int = config.SEMENTE_BOOTSTRAP,
) -> Resultado:
    """Σ c_j β_j sobre (c_j, categoria_j, resultado de `estimar` na categoria_j), com incerteza
    por reamostragem de municípios (seção 6 do projeto).

    Cada β_j é a estimativa convencional com a banda da própria categoria, fixa nas réplicas.
    A reamostragem é estratificada pelo lado do corte, para que toda réplica tenha os dois
    lados, e um município sorteado k vezes entra k vezes em todas as categorias, o que preserva
    a dependência entre categorias de um mesmo município. O intervalo é normal com o
    erro-padrão das réplicas.
    """
    coeficientes = [c for c, _, _ in componentes]
    amostras = [_amostra(painel, resultado, categoria) for _, categoria, _ in componentes]
    estimados = [r for _, _, r in componentes if isinstance(r, Estimativa)]
    if len(estimados) < len(componentes):
        return NaoEstimavel("alguma categoria não é estimável", _contagem(pl.concat(amostras)))
    contagem = _contagem(
        pl.concat(
            a.filter(pl.col("x").abs() < r.banda) for a, r in zip(amostras, estimados, strict=True)
        )
    )
    momentos = [_momentos(a, r.banda) for a, r in zip(amostras, estimados, strict=True)]
    municipios = (
        pl.concat(m.select("municipio", "tratado") for m in momentos).unique().sort("municipio")
    )
    matrizes = [
        municipios.join(m, on=["municipio", "tratado"], how="left")
        .select("s0", "s1", "s2", "ty", "txy")
        .fill_null(0)
        .to_numpy()
        for m in momentos
    ]
    rng = np.random.default_rng(semente)
    lados = []
    for tratado in (True, False):
        indices = np.flatnonzero(municipios["tratado"].to_numpy() == tratado)
        sorteio = rng.multinomial(len(indices), np.full(len(indices), 1 / len(indices)), repeticoes)
        lados.append((indices, sorteio))
    (ind_t, sorteio_t), (ind_c, sorteio_c) = lados
    replicas = sum(
        c * (_intercepto(sorteio_t @ m[ind_t]) - _intercepto(sorteio_c @ m[ind_c]))
        for c, m in zip(coeficientes, matrizes, strict=True)
    )
    ep = float(np.nanstd(replicas, ddof=1))
    if not (math.isfinite(ep) and ep > 0):
        return NaoEstimavel("erro-padrão degenerado", contagem)

    def combinacao(campo: str) -> float:
        return sum(c * getattr(r, campo) for c, r in zip(coeficientes, estimados, strict=True))

    estimativa = combinacao("estimativa")
    return Estimativa(
        estimativa,
        ep,
        estimativa - _Z_IC * ep,
        estimativa + _Z_IC * ep,
        2 * (1 - _NORMAL.cdf(abs(estimativa / ep))),
        math.nan,
        math.nan,
        combinacao("estimativa_meia_banda"),
        math.nan,
        combinacao("estimativa_dobro_banda"),
        math.nan,
        FATOR_EMD * ep,
        contagem,
    )


def densidade(eleicoes: pl.DataFrame) -> Densidade | NaoEstimavel:
    """Teste de densidade da margem entre os municípios da amostra principal (`rddensity`)."""
    margem = eleicoes["margem"].drop_nulls().to_numpy()
    tratados, controle = int((margem < 0).sum()), int((margem >= 0).sum())
    contagem = Contagem(tratados, controle, tratados, controle)
    if _poucos_municipios(contagem):
        return NaoEstimavel(f"menos de {_MINIMO} municípios de um lado do corte", contagem)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            saida = rddensity(margem, c=0)
    except Exception as erro:  # o rddensity também levanta Exception genérica
        return NaoEstimavel(f"rddensity: {erro}", contagem)
    p = float(saida.test["p_jk"])
    if not math.isfinite(p):
        return NaoEstimavel("rddensity sem estatística", contagem)
    return Densidade(
        float(saida.test["t_jk"]), p, float(saida.h["left"]), float(saida.h["right"]), contagem
    )


_CAMPOS_ESTIMATIVA = [
    f.name for f in fields(Estimativa) if f.name not in ("contagem", "redes_por_lado")
]
_CAMPOS_CONTAGEM = [f.name for f in fields(Contagem)]

ESQUEMA = pl.Schema(
    {
        "hipotese": pl.String,
        "categoria": pl.String,
        "tipo": pl.String,
        "resultado": pl.String,
        "placebo": pl.Boolean,
        "estimavel": pl.Boolean,
        "motivo": pl.String,
        **dict.fromkeys(_CAMPOS_ESTIMATIVA, pl.Float64),
        **dict.fromkeys(_CAMPOS_CONTAGEM, pl.Int64),
        "ep_robusto_rede": pl.Float64,
        "p_valor_rede": pl.Float64,
        "redes_tratadas": pl.Int64,
        "redes_controle": pl.Int64,
    }
)
"""Colunas das tabelas por hipótese. `tipo` é `categoria` (rdrobust) ou `contraste`
(combinação de categorias com reamostragem); `*_rede` repete o erro-padrão e o p-valor robustos
com agrupamento por rede e as mesmas bandas, só nas categorias."""


def _finito(valor: float) -> float | None:
    return valor if math.isfinite(valor) else None


def linha(resultado: Resultado) -> dict[str, object]:
    contagem = asdict(resultado.contagem)
    if isinstance(resultado, NaoEstimavel):
        vazio = dict.fromkeys(_CAMPOS_ESTIMATIVA)
        return {"estimavel": False, "motivo": resultado.motivo, **vazio, **contagem}
    valores = {c: _finito(getattr(resultado, c)) for c in _CAMPOS_ESTIMATIVA}
    return {"estimavel": True, "motivo": None, **valores, **contagem}


def tabela(
    painel: pl.DataFrame,
    hipotese: str,
    categorias: dict[str, pl.Expr],
    resultados: Sequence[str],
    placebo: str,
    contrastes: Sequence[Contraste] = (),
    *,
    banda_comum: bool = False,
) -> pl.DataFrame:
    """Uma linha por categoria e por contraste, para cada resultado e para o placebo.

    Com `banda_comum`, o primeiro de `resultados` escolhe as bandas de cada categoria e os demais
    as herdam (H3: termos e total com a mesma amostra, banda e pesos). O placebo escolhe a própria.
    """
    estimados: dict[tuple[str, str], Resultado] = {}
    linhas = []
    for resultado in (*resultados, placebo):
        e_placebo = resultado == placebo
        herda = banda_comum and resultado in resultados[1:]
        for nome, filtro in categorias.items():
            base = estimados.get((nome, resultados[0]))
            if herda and isinstance(base, NaoEstimavel):
                r: Resultado = base
            else:
                bandas = (base.banda, base.banda_vies) if herda else None
                r = estimar(painel, resultado, filtro, banda=bandas)
            estimados[(nome, resultado)] = r
            rede = dict.fromkeys(
                ("ep_robusto_rede", "p_valor_rede", "redes_tratadas", "redes_controle")
            )
            if isinstance(r, Estimativa) and not e_placebo:
                por_rede = estimar(
                    painel,
                    resultado,
                    filtro,
                    agrupamento="rede",
                    banda=(r.banda, r.banda_vies),
                    sensibilidades=False,
                )
                if por_rede.redes_por_lado is not None:
                    rede["redes_tratadas"], rede["redes_controle"] = por_rede.redes_por_lado
                if isinstance(por_rede, Estimativa):
                    rede.update(ep_robusto_rede=por_rede.ep_robusto, p_valor_rede=por_rede.p_valor)
            linhas.append(
                {
                    "hipotese": hipotese,
                    "categoria": nome,
                    "tipo": "categoria",
                    "resultado": resultado,
                    "placebo": e_placebo,
                    **linha(r),
                    **rede,
                }
            )
        for c in contrastes:
            componentes = [
                (coeficiente, categorias[nome], estimados[(nome, resultado)])
                for nome, coeficiente in c.coeficientes.items()
            ]
            linhas.append(
                {
                    "hipotese": hipotese,
                    "categoria": c.nome,
                    "tipo": "contraste",
                    "resultado": resultado,
                    "placebo": e_placebo,
                    **linha(contraste(painel, resultado, componentes)),
                    "ep_robusto_rede": None,
                    "p_valor_rede": None,
                }
            )
    return pl.DataFrame(linhas, schema=ESQUEMA)
