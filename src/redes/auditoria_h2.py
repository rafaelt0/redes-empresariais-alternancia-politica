"""Sobreposição e covariância na faixa 3+ do recorte comparável de H2."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import polars as pl

from redes import config, schemas
from redes.estimate import h1_h2, rdd

FAIXA = "3+"
ARQUIVO = "auditoria_h2_comparaveis.csv"


def sobreposicao(painel: pl.DataFrame, a: pl.Expr, b: pl.Expr) -> dict[str, float | int | None]:
    """Conta linhas empresa–município–elemento, sem publicar estratos individuais."""
    n_a, n_b, n_ambas, estratos = painel.select(
        a.sum(),
        b.sum(),
        (a & b).sum().alias("ambas"),
        pl.struct(h1_h2.ESTRATOS_H2).filter(a | b).n_unique().alias("estratos"),
    ).row(0)
    uniao = n_a + n_b - n_ambas
    publicar = all(
        n == 0 or n >= config.SUPRESSAO_MINIMA for n in (n_ambas, n_a - n_ambas, n_b - n_ambas)
    )
    return {
        "estratos": estratos if estratos == 0 or estratos >= config.SUPRESSAO_MINIMA else None,
        "observacoes_a": n_a if publicar else None,
        "observacoes_b": n_b if publicar else None,
        "observacoes_ambas": n_ambas if publicar else None,
        "jaccard": n_ambas / uniao if publicar and uniao else None,
    }


def resumo_bootstrap(replicas: np.ndarray) -> dict[str, float | int | None]:
    """Compara a variância conjunta com a que resultaria de covariância zero."""
    validas = replicas[np.isfinite(replicas).all(axis=1)]
    medidas = {
        "ep_a_bootstrap": None,
        "ep_b_bootstrap": None,
        "correlacao_bootstrap": None,
        "ep_contraste_bootstrap": None,
        "ep_contraste_sem_covariancia": None,
    }
    if len(validas) >= 2:
        a, b = validas.T
        ep_a, ep_b = validas.std(axis=0, ddof=1)
        medidas.update(
            ep_a_bootstrap=float(ep_a),
            ep_b_bootstrap=float(ep_b),
            correlacao_bootstrap=float(np.corrcoef(a, b)[0, 1]) if ep_a > 0 and ep_b > 0 else None,
            ep_contraste_bootstrap=float(np.std((b - a) / 2, ddof=1)),
            ep_contraste_sem_covariancia=math.hypot(ep_a, ep_b) / 2,
        )
    return {"replicas": len(replicas), "replicas_validas": len(validas), **medidas}


def auditar(painel: pl.DataFrame, referencia: pl.DataFrame) -> pl.DataFrame:
    painel, categorias = h1_h2.preparar_recorte_comparavel(painel)
    pos = referencia.filter(pl.col("resultado") == h1_h2.RESULTADO)
    bandas = []
    amostras = []
    filtros = []
    filtros_h = []
    for grupo in ("a", "b"):
        nome = f"faixa_{grupo}_{FAIXA}"
        linha = pos.filter(categoria=nome).row(0, named=True)
        h, b = linha["banda"], linha["banda_vies"]
        if h is None or b is None:
            raise ValueError(f"Bandas indisponíveis para {nome}")
        filtro = categorias[nome] & pl.col(h1_h2.RESULTADO).is_not_null()
        amostra = rdd._amostra(painel, h1_h2.RESULTADO, filtro)
        contagem = rdd._contagem(amostra, h)
        if (contagem.unidades_tratadas, contagem.unidades_controle) != (
            linha["unidades_tratadas"],
            linha["unidades_controle"],
        ):
            raise ValueError(f"A amostra local não coincide com a referência de {nome}")
        filtros.append(filtro)
        filtros_h.append(filtro & (pl.col("margem").abs() < h))
        amostras.append(amostra)
        bandas.append((h, b))
    recorte = sobreposicao(painel, *filtros)
    dentro_h = sobreposicao(painel, *filtros_h)
    bootstrap = resumo_bootstrap(rdd.replicas_por_categoria(amostras, bandas))
    ep_publicado = pos.filter(categoria=f"vencedor_faixa_{FAIXA}")["ep_robusto"].item()
    ep_auditado = bootstrap["ep_contraste_bootstrap"]
    if ep_auditado is None or ep_publicado is None:
        raise ValueError("Erro-padrão indisponível para o contraste")
    if not math.isclose(ep_auditado, ep_publicado, abs_tol=1e-12):
        raise ValueError("O erro-padrão da auditoria difere do contraste publicado")
    return pl.DataFrame(
        {
            "faixa": FAIXA,
            **recorte,
            **{f"na_banda_{nome}": valor for nome, valor in dentro_h.items()},
            **bootstrap,
        }
    )


def executar(caminhos: config.Caminhos) -> Path:
    tabelas = caminhos.resultados / "tables"
    referencia = pl.read_csv(tabelas / "h2_comparaveis.csv", schema=rdd.ESQUEMA)
    painel = (
        schemas.ler(schemas.PAINEL_FIRMA, caminhos.dados)
        .filter(variante="PRINCIPAL")
        .collect(engine="streaming")
    )
    with TemporaryDirectory(prefix=".auditoria-h2-", dir=tabelas) as tmp:
        provisorio = Path(tmp) / ARQUIVO
        auditar(painel, referencia).write_csv(provisorio)
        return provisorio.replace(tabelas / ARQUIVO)


if __name__ == "__main__":
    print(executar(config.Caminhos.do_ambiente()))
