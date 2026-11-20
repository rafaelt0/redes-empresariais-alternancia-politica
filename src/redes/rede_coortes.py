"""Concentração no maior componente e suporte fora dele para as categorias de H2."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from redes import config, schemas
from redes.estimate import h1_h2, rdd
from redes.sensibilidades import maior_componente

ARQUIVO = "concentracao_gigante_h2.csv"
LADOS = ("tratados", "controle")


def _publicavel(n: int) -> bool:
    return n == 0 or n >= config.SUPRESSAO_MINIMA


def _piso_publicavel(fracao: float, total: int, escala: int) -> float | None:
    # Mesmo com total conhecido, o limite precisa admitir um complemento de pelo menos cinco.
    nivel = min(fracao, 1 - config.SUPRESSAO_MINIMA / total, 0.99)
    piso = math.floor(nivel * escala) / escala
    return piso if piso > 0 else None


def concentracao(
    amostra: pl.DataFrame, id_gigante: str, banda: float | None
) -> dict[str, float | int | bool | None]:
    """Calcula agregados com os pesos unitários por município de rdd._amostra."""
    tratado = pl.col("x") < 0
    gigante = pl.col("rede") == id_gigante
    fora = ~gigante
    peso = pl.col("w")
    if banda is not None:
        amostra = amostra.filter(pl.col("x").abs() < banda)
        peso = peso * (1 - pl.col("x").abs() / banda)

    valores = amostra.select(
        gigante.sum().alias("obs_gigante"),
        peso.sum().alias("peso_total"),
        peso.filter(gigante).sum().alias("peso_gigante"),
        pl.col("rede").n_unique().alias("redes"),
        pl.col("rede").filter(fora).n_unique().alias("redes_sem_gigante"),
        *(
            (grupo & lado).sum().alias(f"{grupo_nome}_{lado_nome}")
            for grupo_nome, grupo in (("obs_gigante", gigante), ("obs_fora", fora))
            for lado_nome, lado in zip(LADOS, (tratado, ~tratado), strict=True)
        ),
        *(
            pl.col(unidade).filter(fora & lado).n_unique().alias(f"{nome}_{lado_nome}")
            for nome, unidade in (("redes", "rede"), ("municipios", "municipio"))
            for lado_nome, lado in zip(LADOS, (tratado, ~tratado), strict=True)
        ),
    ).row(0, named=True)

    publicas = all(
        _publicavel(valores[f"{grupo}_{lado}"])
        for grupo in ("obs_gigante", "obs_fora")
        for lado in LADOS
    )
    frac_obs = valores["obs_gigante"] / amostra.height if amostra.height else None
    piso_obs = None
    if frac_obs is not None:
        if frac_obs >= 0.99 and amostra.height >= 100 * config.SUPRESSAO_MINIMA:
            piso_obs = 0.99
        elif not publicas:
            piso_obs = _piso_publicavel(frac_obs, amostra.height, 20)
    frac_peso = (
        valores["peso_gigante"] / valores["peso_total"] if valores["peso_total"] > 0 else None
    )
    piso_peso = (
        _piso_publicavel(frac_peso, amostra.height, 100)
        if not publicas and frac_peso is not None
        else None
    )
    redes, outras = valores["redes"], valores["redes_sem_gigante"]
    suporte = {
        lado: valores[f"municipios_{lado}"] >= config.MINIMO_MUNICIPIOS_POR_LADO for lado in LADOS
    }
    return {
        "fracao_observacoes_gigante": frac_obs if publicas and piso_obs is None else None,
        "piso_fracao_observacoes": piso_obs,
        "fracao_peso_gigante": frac_peso if publicas else None,
        "piso_fracao_peso": piso_peso,
        "redes": redes if _publicavel(redes) and _publicavel(outras) else None,
        "redes_sem_gigante": outras if _publicavel(outras) else None,
        **{
            f"{unidade}_sem_gigante_{lado}": (
                valores[f"{unidade}_{lado}"] if _publicavel(valores[f"{unidade}_{lado}"]) else None
            )
            for unidade in ("redes", "municipios")
            for lado in LADOS
        },
        **{f"suporte_minimo_sem_gigante_{lado}": valido for lado, valido in suporte.items()},
        "suporte_minimo_sem_gigante": all(suporte.values()),
    }


def auditar(
    painel: pl.DataFrame, id_gigante: str, principal: pl.DataFrame, comparaveis: pl.DataFrame
) -> pl.DataFrame:
    comparavel, filtros = h1_h2.preparar_recorte_comparavel(painel)
    linhas = []
    for recorte, dados, categorias, tabela in (
        ("principal", painel, h1_h2.CATEGORIAS_H2, principal),
        ("comparaveis", comparavel, filtros, comparaveis),
    ):
        pos = tabela.filter(pl.col("resultado") == h1_h2.RESULTADO)
        for nome, filtro in categorias.items():
            _, grupo, faixa = nome.split("_")
            amostra = rdd._amostra(dados, h1_h2.RESULTADO, filtro)
            linha = pos.filter(categoria=nome).row(0, named=True)
            h = linha["banda"]
            if h is not None:
                contagem = rdd._contagem(amostra, h)
                if (contagem.unidades_tratadas, contagem.unidades_controle) != (
                    linha["unidades_tratadas"],
                    linha["unidades_controle"],
                ):
                    raise ValueError(f"A amostra local não coincide com {recorte}/{nome}")
            for janela, banda in (("antes_da_banda", None), ("h", h), ("b", linha["banda_vies"])):
                if janela == "antes_da_banda" or banda is not None:
                    linhas.append(
                        {
                            "recorte": recorte,
                            "faixa": faixa,
                            "grupo": grupo.upper(),
                            "janela": janela,
                            "banda": banda,
                            **concentracao(amostra, id_gigante, banda),
                        }
                    )
    return pl.DataFrame(linhas)


def executar(caminhos: config.Caminhos) -> Path:
    tabelas = caminhos.resultados / "tables"
    principal, comparavel = [
        pl.read_csv(tabelas / nome, schema=rdd.ESQUEMA) for nome in ("h2.csv", "h2_comparaveis.csv")
    ]
    painel = (
        schemas.ler(schemas.PAINEL_FIRMA, caminhos.dados)
        .filter(variante="PRINCIPAL")
        .collect(engine="streaming")
    )
    tabela = auditar(painel, str(maior_componente(caminhos.dados)), principal, comparavel)
    with TemporaryDirectory(prefix=".rede-coortes-", dir=tabelas) as tmp:
        provisorio = Path(tmp) / ARQUIVO
        tabela.write_csv(provisorio)
        return provisorio.replace(tabelas / ARQUIVO)


if __name__ == "__main__":
    print(executar(config.Caminhos.do_ambiente()))
