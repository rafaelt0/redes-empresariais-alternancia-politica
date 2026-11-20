"""Sensibilidades em dados locais. Execute com `python -m redes.sensibilidades --help`."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import numpy as np
import polars as pl

from redes import config, descritivas, links, network, panel, schemas
from redes.estimate import estimar_variante, h3, h4, rdd, resumo, suprimir_contagens
from redes.ingest.tcesp import VERSAO as VERSAO_TC

M = panel.MUNICIPIO
CHAVE_FIRMA = (M, "elemento_despesa", "cnpj_basico")
CHAVE_DISTANCIA = (M, "grupo", "cnpj_basico")
PRINCIPAL = "PRINCIPAL"
SETEMBRO = "APENAS_SETEMBRO"
SEM_GIGANTE = "SEM_GIGANTE"
SEM_ARTICULACAO = "SEM_ARTICULACAO_SEMENTES_FIXAS"
SEM_AUTOFINANCIAMENTO = "SEM_AUTOFINANCIAMENTO"
ESCOPO_RESTRITO = "SEM_PESSOAL_OU_CREDOR_PUBLICO"


def ler_principal(dados: Path, tabela: schemas.Tabela) -> pl.LazyFrame:
    return schemas.ler(tabela, dados).filter(pl.col("variante") == PRINCIPAL)


def sem_gigante(redes: pl.DataFrame, id_gigante: int) -> pl.DataFrame:
    """Retira o componente da amostra, com denominadores e ranking original fixos."""
    return redes.filter(pl.col("id_rede") != id_gigante)


def maior_componente(dados: Path) -> int:
    return (
        ler_principal(dados, schemas.REDE)
        .select("id_rede", "empresas_na_rede")
        .top_k(1, by=["empresas_na_rede", "id_rede"], reverse=[False, True])
        .collect(engine="streaming")
        .item(0, "id_rede")
    )


def _anexar(con: duckdb.DuckDBPyConnection, nome: str, caminho: Path) -> None:
    protegido = str(caminho).replace("'", "''")
    con.execute(f"CREATE VIEW {nome} AS SELECT * FROM read_parquet('{protegido}')")


def empenhos_agregados(dados: Path, tmp: Path) -> pl.DataFrame:
    with duckdb.connect(
        config={"memory_limit": "800MB", "temp_directory": str(tmp), "threads": 2}
    ) as con:
        for tabela in (schemas.EMPENHOS, schemas.LICITACOES, schemas.ELEICOES):
            _anexar(con, tabela.nome, dados / tabela.arquivo)
        return panel.agregar_empenhos(con)


def _rede_no_painel(rede: pl.DataFrame) -> pl.DataFrame:
    return rede.select(
        pl.col("empresa").cast(pl.String).str.zfill(8).alias("cnpj_basico"), "id_rede"
    )


def _distancias_no_painel(distancias: pl.DataFrame) -> pl.DataFrame:
    return distancias.with_columns(
        pl.col("empresa").cast(pl.String).str.zfill(8).alias("cnpj_basico")
    ).select(*CHAVE_DISTANCIA, "faixa")


def _gravar_paineis(
    agregado: pl.DataFrame,
    rede: pl.DataFrame,
    distancias: pl.DataFrame,
    eleicoes: pl.DataFrame,
    pasta: Path,
    caso: str,
    *,
    firma_base: pl.DataFrame | None = None,
) -> None:
    for tabela, montar in (
        (schemas.PAINEL_FIRMA, panel.painel_firma),
        (schemas.PAINEL_REDE, panel.painel_rede),
    ):
        if tabela == schemas.PAINEL_FIRMA and firma_base is not None:
            painel = (
                firma_base.drop("id_rede", "faixa_a", "faixa_b")
                .pipe(panel.com_rede_e_faixas, distancias, rede)
                .select(tabela.esquema.names())
                .sort(tabela.chave)
            )
        else:
            painel = montar(agregado, distancias, rede, eleicoes, PRINCIPAL)
        painel.write_parquet(pasta / f"{tabela.nome}-{caso}.parquet")


def _paineis_grafo(
    dados: Path, pasta: Path, tmp: Path, grafo: network.Grafo, origens: pl.DataFrame, caso: str
) -> None:
    eleicoes = schemas.ler(schemas.ELEICOES, dados).collect()
    rede = network.redes(grafo, grafo.igraph().connected_components())
    agregado = empenhos_agregados(dados, tmp)
    alvos = network.alvos_dos_empenhos(agregado.lazy())
    distancias = _distancias_no_painel(network.distancias(grafo, rede, origens, alvos))
    empresas = agregado.select(pl.col("cnpj_basico").cast(pl.UInt32).alias("empresa")).unique()
    rede = _rede_no_painel(rede.join(empresas, on="empresa", how="semi"))
    firma = ler_principal(dados, schemas.PAINEL_FIRMA).collect(engine="streaming")
    _gravar_paineis(agregado, rede, distancias, eleicoes, pasta, caso, firma_base=firma)


def paineis_setembro(dados: Path, pasta: Path, tmp: Path) -> None:
    """Replica a rede somente com os vínculos documentados na pasta de setembro."""
    socios = schemas.ler(schemas.SOCIOS, dados).filter(pl.col("origem") == config.FOTOGRAFIA_RFB)
    conexoes = schemas.ler(schemas.CONEXOES_DIRETAS, dados)
    v = network.vinculos_da_fotografia(socios)
    mascara = np.ones(len(v.empresa), dtype=bool)
    origens = network.origens_da_variante(network.conexoes_com_chave(conexoes), v, mascara)
    grafo = network.montar_grafo(v, mascara)
    del v, mascara
    _paineis_grafo(dados, pasta, tmp, grafo, origens, SETEMBRO)


def paineis_sem_articulacao(dados: Path, pasta: Path, tmp: Path) -> None:
    """Retira pontos de articulação do grafo, preservando as sementes do desenho principal."""
    conexoes = schemas.ler(schemas.CONEXOES_DIRETAS, dados)
    origens = network.conexoes_com_chave(conexoes).drop("pessoa").unique()
    v = network.vinculos_da_fotografia(schemas.ler(schemas.SOCIOS, dados))
    cheio = network.montar_grafo(v, np.ones(len(v.empresa), dtype=bool))
    articulacao = network.pessoas_articulacao(cheio.igraph(), cheio.n_empresas, cheio.pessoas)
    del cheio
    mascara = network.mascara_da_variante(v, "SEM_ARTICULACAO", articulacao)
    grafo = network.montar_grafo(v, mascara)
    del v, mascara
    _paineis_grafo(dados, pasta, tmp, grafo, origens, SEM_ARTICULACAO)


def paineis_sem_autofinanciamento(dados: Path, pasta: Path, tmp: Path) -> None:
    """Retira doações de recursos próprios, preservando a rede societária."""
    eleicoes = schemas.ler(schemas.ELEICOES, dados)
    doacoes = schemas.ler(schemas.DOACOES, dados)
    terceiros = links.doadores(doacoes, eleicoes, ("PESSOA_FISICA",))
    conexoes = schemas.ler(schemas.CONEXOES_DIRETAS, dados)
    por_terceiros = conexoes.join(terceiros, on=[M, "grupo", "id_pessoa"], how="semi")
    origens = network.conexoes_com_chave(por_terceiros).drop("pessoa").unique()
    origens_principais = network.conexoes_com_chave(conexoes).drop("pessoa").unique()
    municipios = origens_principais.join(origens, on=[M, "grupo", "empresa"], how="anti").select(M)
    agregado = empenhos_agregados(dados, tmp)
    alvos = network.alvos_dos_empenhos(agregado.lazy()).join(municipios, on=M, how="semi")
    v = network.vinculos_da_fotografia(schemas.ler(schemas.SOCIOS, dados))
    grafo = network.montar_grafo(v, np.ones(len(v.empresa), dtype=bool))
    del v
    rede = (
        ler_principal(dados, schemas.REDE)
        .select(pl.col("cnpj_basico").cast(pl.UInt32).alias("empresa"), "id_rede")
        .sort("empresa")
        .collect(engine="streaming")
    )
    if not np.array_equal(rede["empresa"].to_numpy(), grafo.cnpjs):
        raise ValueError("O grafo e a rede de referência contêm empresas diferentes.")
    recalculadas = _distancias_no_painel(network.distancias(grafo, rede, origens, alvos))
    del grafo
    rede = _rede_no_painel(
        rede.join(
            agregado.select(pl.col("cnpj_basico").cast(pl.UInt32).alias("empresa")).unique(),
            on="empresa",
            how="semi",
        )
    )
    intactas = (
        ler_principal(dados, schemas.DISTANCIAS)
        .join(municipios.lazy(), on=M, how="anti")
        .select(*CHAVE_DISTANCIA, "faixa")
        .collect(engine="streaming")
    )
    distancias = pl.concat([recalculadas, intactas])
    firma = ler_principal(dados, schemas.PAINEL_FIRMA).collect(engine="streaming")
    _gravar_paineis(
        agregado,
        rede,
        distancias,
        eleicoes.collect(),
        pasta,
        SEM_AUTOFINANCIAMENTO,
        firma_base=firma,
    )


def _perto(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(pl.col("margem").abs() <= config.JANELA_DESCRITIVA_H4).with_columns(
        lado=pl.when(pl.col("tratamento") == 1)
        .then(pl.lit("derrota_incumbente"))
        .otherwise(pl.lit("vitoria_incumbente"))
    )


def origem_fornecedores(firma: pl.DataFrame, origens: pl.DataFrame) -> pl.DataFrame:
    """Recorte fixo de cinco pontos percentuais, uma linha por fornecedor e município."""
    perto = (
        _perto(firma)
        .group_by(M, "cnpj_basico", "lado")
        .agg(pl.col("faixa_a", "faixa_b").first(), pl.col("empenhado_pre").sum())
        .join(origens, on="cnpj_basico", how="left", validate="m:1")
        .with_columns(pl.col("origem").cast(pl.String).fill_null("SEM_QUADRO"))
    )
    coortes = {
        "fornecedores_anteriores": pl.lit(True),
        "conexao_direta_a": pl.col("faixa_a") == "0",
        "conexao_direta_b": pl.col("faixa_b") == "0",
    }
    por_origem = pl.concat(
        perto.filter(filtro)
        .group_by("lado", "origem")
        .agg(
            fornecedores_municipio=pl.len(),
            municipios=pl.col(M).n_unique(),
            empenho_pre=pl.col("empenhado_pre").sum(),
        )
        .with_columns(
            coorte=pl.lit(coorte),
            fracao_fornecedores=pl.col("fornecedores_municipio")
            / pl.col("fornecedores_municipio").sum().over("lado"),
            fracao_empenho_pre=pl.col("empenho_pre") / pl.col("empenho_pre").sum().over("lado"),
        )
        for coorte, filtro in coortes.items()
    )
    return (
        descritivas.suprimir_particao(
            por_origem,
            ("fornecedores_municipio", "municipios", "fracao_fornecedores", "fracao_empenho_pre"),
            "coorte",
            "lado",
        )
        .select(
            "coorte",
            "lado",
            "origem",
            "fornecedores_municipio",
            "municipios",
            "fracao_fornecedores",
            "fracao_empenho_pre",
        )
        .sort("coorte", "lado", "origem")
    )


def dominancia_gigante(
    redes: pl.DataFrame, id_gigante: int, banda_h3: float | None
) -> pl.DataFrame:
    """Peso do componente na banda estimada de H3 e nas coortes de H4 em ±5 p.p."""
    valor = pl.col("gasto_medio_pre") * pl.col("participacao_pre")
    gigante = pl.col("id_rede") == id_gigante
    ambos = pl.col("ligacao") == "AMBOS"
    exclusivas = pl.col("ligacao").is_in(["A", "B"])
    janela = config.JANELA_DESCRITIVA_H4
    recortes = [
        ("H3_ambos", ambos, banda_h3),
        ("H3_demais", ~ambos, banda_h3),
        *(
            (f"H4_{coorte}_{p}", pl.col(f"principal_{p}") & filtro, janela)
            for coorte, filtro in (("principais", pl.lit(True)), ("exclusivas", exclusivas))
            for p in panel.LIMIARES
        ),
    ]
    tabelas = []
    for nome, filtro, banda in recortes:
        no_recorte = (
            (
                pl.col("margem").abs() < banda
                if nome.startswith("H3")
                else pl.col("margem").abs() <= banda
            )
            if banda is not None
            else pl.lit(False)
        )
        por_municipio = (
            redes.filter(filtro & no_recorte)
            .group_by(M, "tratamento")
            .agg(
                n_redes=pl.len(),
                gigante=gigante.sum(),
                outras=(~gigante).any(),
                valor=valor.sum(),
                valor_gigante=valor.filter(gigante).sum(),
            )
        )
        tabelas.append(
            por_municipio.select(
                coorte=pl.lit(nome),
                banda=pl.lit(banda, pl.Float64),
                municipios=pl.len(),
                municipios_tratados=(pl.col("tratamento") == 1).sum(),
                municipios_controle=(pl.col("tratamento") == 0).sum(),
                redes_municipio=pl.col("n_redes").sum(),
                municipios_com_gigante=pl.col("gigante").sum(),
                municipios_sem_gigante=pl.col("outras").sum(),
                fracao_peso_gigante=(pl.col("gigante") / pl.col("n_redes")).mean(),
                fracao_empenho_gigante=pl.col("valor_gigante").sum() / pl.col("valor").sum(),
            )
        )
    tabela = pl.concat(tabelas)
    n = pl.col("municipios").cast(pl.Int64)
    g = pl.col("municipios_com_gigante").cast(pl.Int64)
    outros = pl.col("municipios_sem_gigante").cast(pl.Int64)

    def pequena(c: pl.Expr) -> pl.Expr:
        return c.is_between(1, config.SUPRESSAO_MINIMA - 1)

    suporte = pl.min_horizontal("municipios_tratados", "municipios_controle")
    suficiente = suporte >= config.MINIMO_MUNICIPIOS_POR_LADO
    publica = (
        pl.when(pl.col("coorte").str.starts_with("H3")).then(suficiente).otherwise(True)
        & ~pequena(n)
        & ~pequena(g)
    )
    outras_redes = pl.col("redes_municipio").cast(pl.Int64) - g
    peso_publicavel = publica & ~pequena(n - g) & ~pequena(outras_redes) & ~pequena(n - outros)
    lados_publicaveis = ~(
        pequena(pl.col("municipios_tratados")) | pequena(pl.col("municipios_controle"))
    )
    return tabela.with_columns(
        pl.when(peso_publicavel).then(pl.col("fracao_peso_gigante")).alias("fracao_peso_gigante"),
        pl.when(publica).then(pl.col("fracao_empenho_gigante")).alias("fracao_empenho_gigante"),
        pl.when(publica & ~pequena(n - g) & ~pequena(outras_redes))
        .then(g)
        .alias("municipios_com_gigante"),
        pl.when(~(pequena(outros) | pequena(n - outros)))
        .then(outros)
        .alias("municipios_sem_gigante"),
        *(
            pl.when(lados_publicaveis).then(descritivas.suprimir(c)).alias(c)
            for c in ("municipios", "municipios_tratados", "municipios_controle")
        ),
        descritivas.suprimir("redes_municipio"),
    )


def diagnosticos(dados: Path, tabelas: Path) -> None:
    firma = (
        ler_principal(dados, schemas.PAINEL_FIRMA)
        .select(M, "cnpj_basico", "margem", "tratamento", "faixa_a", "faixa_b", "empenhado_pre")
        .collect(engine="streaming")
    )
    alvos = firma.filter(pl.col("margem").abs() <= config.JANELA_DESCRITIVA_H4)
    origens = (
        schemas.ler(schemas.SOCIOS, dados)
        .select("cnpj_basico", "origem")
        .join(alvos.lazy().select("cnpj_basico").unique(), on="cnpj_basico", how="semi")
        .unique()
        .collect(engine="streaming")
    )
    origem_fornecedores(firma, origens).write_csv(tabelas / "sensibilidade_origem.csv")
    redes = ler_principal(dados, schemas.PAINEL_REDE).collect(engine="streaming")
    banda_h3 = (
        pl.read_csv(tabelas / "h3.csv")
        .filter((pl.col("categoria") == "ambos") & (pl.col("resultado") == "variacao_total"))
        .item(0, "banda")
    )
    dominancia_gigante(redes, maior_componente(dados), banda_h3).write_csv(
        tabelas / "sensibilidade_gigante.csv"
    )


def estimativas(dados: Path, pasta: Path, tabelas: Path, caso: str) -> None:
    """Estima com o mesmo código das tabelas principais e Holm por especificação."""
    if caso == SEM_GIGANTE:
        redes = ler_principal(dados, schemas.PAINEL_REDE).collect(engine="streaming")
        redes = sem_gigante(redes, maior_componente(dados))
        # H1 e H2 são os da especificação principal; seus valores-p entram na mesma família.
        firmas = [pl.read_csv(tabelas / f"h{i}.csv", schema_overrides=rdd.ESQUEMA) for i in (1, 2)]
        resultado = pl.concat([*firmas, h3.h3(redes), h4.h4(redes)])
    else:
        firma, redes = (
            pl.read_parquet(pasta / f"{tabela.nome}-{caso}.parquet")
            for tabela in (schemas.PAINEL_FIRMA, schemas.PAINEL_REDE)
        )
        resultado = pl.concat([estimar_variante(firma, redes), h4.h4(redes)])
    densidade = pl.read_csv(tabelas / "densidade.csv")
    publico = suprimir_contagens(resumo(resultado, densidade))
    if caso == SEM_GIGANTE:
        publico = publico.filter(pl.col("hipotese").is_in(["H3", "H4"]))
    publico.write_csv(tabelas / f"sensibilidade_{caso.lower()}.csv")


def auditoria_escopo(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Valores líquidos na amostra e por lado em ±5 p.p., antes e depois da eleição."""
    flags = {
        "pessoal": "pessoal",
        "credor_publico": "credor_publico",
        "intersecao": "pessoal AND credor_publico",
        "excluido": "pessoal OR credor_publico",
    }
    piso = config.SUPRESSAO_MINIMA
    celula_publicavel = f"COUNT(DISTINCT {M}) >= {piso}"
    particao = (
        "pessoal AND credor_publico",
        "pessoal AND NOT credor_publico",
        "NOT pessoal AND credor_publico",
        "NOT pessoal AND NOT credor_publico",
    )
    publicavel = " AND ".join(
        [celula_publicavel]
        + [f"COUNT(*) FILTER (WHERE {f}) NOT BETWEEN 1 AND {piso - 1}" for f in particao]
    )
    fracoes = ", ".join(
        f"""CASE WHEN {publicavel}
             THEN COALESCE(SUM(valor) FILTER (WHERE {f}), 0) / NULLIF(SUM(valor), 0)
             END AS fracao_{nome}"""
        for nome, f in flags.items()
    )
    return con.sql(
        f"""
        WITH registros AS (
            SELECT e.*,
                CASE WHEN year(e.data) = {config.ANO_RESULTADO} THEN '2025' ELSE 'pre' END
                    AS periodo,
                CASE WHEN l.tratamento = 1 THEN 'derrota_incumbente' ELSE 'vitoria_incumbente' END
                    AS lado,
                abs(l.margem) <= {config.JANELA_DESCRITIVA_H4} AS perto
            FROM classificados e
            INNER JOIN eleicoes l USING ({M})
            WHERE e.data BETWEEN DATE '{config.INICIO_PRE_ELEICAO}'
                             AND DATE '{config.FIM_PRE_ELEICAO}'
               OR year(e.data) = {config.ANO_RESULTADO}
        )
        SELECT periodo, COALESCE(lado, 'amostra') AS recorte,
            CASE WHEN {celula_publicavel} THEN COUNT(DISTINCT {M}) END AS municipios,
            CASE WHEN {celula_publicavel} THEN COUNT(*) END AS eventos,
            CASE WHEN {celula_publicavel} THEN SUM(valor) END AS empenho_liquido,
            {fracoes}
        FROM registros
        GROUP BY GROUPING SETS ((periodo), (periodo, lado, perto))
        HAVING COALESCE(perto, true)
        ORDER BY periodo, recorte
        """
    ).pl()


def paineis_escopo(dados: Path, parciais: Path, pasta: Path, tmp: Path, tabelas: Path) -> None:
    """Exclui despesas de pessoal e encargos (3.1) ou com credor público pelo nome do TCESP."""
    for ano in config.ANOS_EMPENHO:
        arquivo = parciais / f"empenhos-{ano}.v{VERSAO_TC}.parquet"
        if not arquivo.is_file():
            raise FileNotFoundError(arquivo)
    with duckdb.connect(
        config={"memory_limit": "800MB", "temp_directory": str(tmp), "threads": 2}
    ) as con:
        for tabela in (schemas.LICITACOES, schemas.ELEICOES):
            _anexar(con, tabela.nome, dados / tabela.arquivo)
        _anexar(con, "empenhos_original", dados / schemas.EMPENHOS.arquivo)
        _anexar(con, "parciais", parciais / f"empenhos-*.v{VERSAO_TC}.parquet")
        con.execute("""
            CREATE VIEW classificados AS
            SELECT e.*, coalesce(starts_with(e.natureza_despesa, '31'), false) AS pessoal,
                p.id_evento IS NOT NULL AS credor_publico
            FROM empenhos_original e
            LEFT JOIN (SELECT DISTINCT id_evento, data FROM parciais WHERE credor_publico) p
            USING (id_evento, data)
        """)
        auditoria_escopo(con).write_csv(tabelas / "sensibilidade_escopo_tcesp.csv")
        con.execute("""
            CREATE VIEW empenhos AS
            SELECT * FROM classificados WHERE NOT pessoal AND NOT credor_publico
        """)
        agregado = panel.agregar_empenhos(con)
    eleicoes = schemas.ler(schemas.ELEICOES, dados).collect()
    rede = (
        ler_principal(dados, schemas.REDE)
        .join(agregado.lazy().select("cnpj_basico").unique(), on="cnpj_basico", how="semi")
        .select("cnpj_basico", "id_rede")
        .collect(engine="streaming")
    )
    distancias = (
        ler_principal(dados, schemas.DISTANCIAS)
        .select(*CHAVE_DISTANCIA, "faixa")
        .collect(engine="streaming")
    )
    _gravar_paineis(agregado, rede, distancias, eleicoes, pasta, ESCOPO_RESTRITO)


def main() -> None:
    montadores = {
        SETEMBRO: paineis_setembro,
        SEM_ARTICULACAO: paineis_sem_articulacao,
        SEM_AUTOFINANCIAMENTO: paineis_sem_autofinanciamento,
    }
    casos = (*montadores, SEM_GIGANTE, ESCOPO_RESTRITO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", type=Path, required=True, help="Parquets do pipeline principal")
    parser.add_argument("--cache", type=Path, required=True, help="Parquets locais de trabalho")
    parser.add_argument("--parciais-tcesp", type=Path, help="Pasta tcesp da ingestão")
    parser.add_argument("--tabelas", type=Path, default=config.RAIZ / "results" / "tables")
    parser.add_argument("--caso", choices=casos, help="Uma sensibilidade. Por padrão, roda todas.")
    parser.add_argument(
        "--etapa",
        choices=("todas", "paineis", "estimativas", "diagnosticos"),
        default="todas",
    )
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.tabelas.mkdir(parents=True, exist_ok=True)
    if args.etapa in ("todas", "diagnosticos"):
        diagnosticos(args.dados, args.tabelas)
    if args.etapa == "diagnosticos":
        return

    for caso in (args.caso,) if args.caso else casos:
        print(f"sensibilidades: {caso}", flush=True)
        if args.etapa in ("todas", "paineis") and caso != SEM_GIGANTE:
            with TemporaryDirectory(dir=args.cache) as tmp:
                if caso == ESCOPO_RESTRITO:
                    parciais = args.parciais_tcesp or (args.dados / "tcesp")
                    paineis_escopo(args.dados, parciais, args.cache, Path(tmp), args.tabelas)
                else:
                    montadores[caso](args.dados, args.cache, Path(tmp))
        if args.etapa in ("todas", "estimativas"):
            estimativas(args.dados, args.cache, args.tabelas, caso)


if __name__ == "__main__":
    main()
