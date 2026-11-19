"""Etapa `network`: grafo bipartido, componentes e δ_ik por município e grupo (T09, T10).

Seção 4 do projeto: duas empresas são vizinhas quando compartilham ao menos um sócio, a rede
societária é o componente conexo dessa vizinhança e δ_ik é o menor número de vizinhanças entre
a empresa i e uma empresa diretamente conectada ao grupo k.

O sócio pessoa jurídica entra como vértice-pessoa identificado pelo CNPJ básico dele, distinto do
vértice-empresa de mesmo CNPJ. Assim "compartilhar um sócio" vale ao pé da letra: duas empresas
com a mesma sócia PJ são vizinhas, mas a sócia não é vizinha das empresas de que participa (a
menos que compartilhe com elas algum outro sócio).

A fotografia tem 20 milhões de vínculos e a máquina, 7 GB: os vínculos viram vetores numpy de
índices densos (empresa e pessoa em int32), cada variante é uma máscara sobre eles e as saídas
de cada variante vão para o disco antes da seguinte. O grafo do igraph só guarda pessoas com
duas ou mais empresas e as empresas delas: uma pessoa com uma só empresa não liga empresas nem é
ponto de articulação, e empresas fora desse grafo são redes de uma empresa só.

`distancias` só traz as empresas com empenho no município: num grafo com pessoas que são sócias
de milhares de empresas, três vizinhanças a partir de vinte origens alcançam uma fração grande de
todas as empresas, e gravar δ para todas elas em cada município e grupo não cabe em disco.
"""

import shutil
from collections.abc import Iterator
from dataclasses import dataclass

import igraph as ig
import numpy as np
import polars as pl

from redes import config, descritivas, schemas
from redes.etapas import Contexto, Etapa
from redes.schemas import CONEXOES_DIRETAS, DISTANCIAS, EMPENHOS, FAIXA, REDE, SOCIOS, VARIANTE

ETAPA = Etapa(
    nome="network",
    depende=("ingest-rfb", "ingest-tcesp", "links"),
    le=(SOCIOS, CONEXOES_DIRETAS, EMPENHOS),
    grava=(REDE, DISTANCIAS),
    artefatos=("resultados/tables/rede_*.csv",),
)


@dataclass(frozen=True)
class Vinculos:
    """Vínculos distintos empresa–pessoa da fotografia, um por posição dos vetores.

    `empresa` indexa `cnpjs` (o universo, ordenado). `pessoa` é um id denso em ordem de
    (pj, chave): as pessoas físicas e estrangeiras vêm antes, ordenadas pelo pseudônimo, e os
    sócios PJ depois, pelo CNPJ básico. `administrador` marca o vínculo que só existe como
    administrador não sócio.
    """

    cnpjs: np.ndarray
    empresa: np.ndarray
    pessoa: np.ndarray
    administrador: np.ndarray
    pessoa_pj: np.ndarray
    chave: np.ndarray

    @property
    def n_pessoas(self) -> int:
        return len(self.pessoa_pj)

    def posicoes(self, cnpjs: np.ndarray) -> np.ndarray:
        """Posição de cada CNPJ no universo, ou -1 para empresas sem sócio na fotografia."""
        return _posicoes(self.cnpjs, cnpjs)

    def pessoas_fisicas(self, chaves: np.ndarray) -> np.ndarray:
        """Id de cada pseudônimo de pessoa física ou estrangeira, ou -1 se não for sócio."""
        return _posicoes(self.chave[: np.count_nonzero(~self.pessoa_pj)], chaves)


def _posicoes(ordenados: np.ndarray, valores: np.ndarray) -> np.ndarray:
    if not len(ordenados):
        return np.full(len(valores), -1, dtype=np.int64)
    pos = np.minimum(np.searchsorted(ordenados, valores), len(ordenados) - 1)
    return np.where(ordenados[pos] == valores, pos, -1)


def vinculos_da_fotografia(socios: pl.LazyFrame) -> Vinculos:
    pj = pl.col("tipo_socio") == "PJ"
    frame = (
        socios.select(
            pl.col("cnpj_basico").cast(pl.UInt32).alias("empresa"),
            pj.alias("pj"),
            pl.when(pj)
            .then(pl.col("id_socio").cast(pl.UInt64, strict=False))
            .otherwise(pl.col("id_socio").str.to_integer(base=16, dtype=pl.UInt64))
            .alias("pessoa"),
            (pl.col("vinculo") == "ADMINISTRADOR_NAO_SOCIO").alias("administrador"),
        )
        .group_by("empresa", "pj", "pessoa")
        .agg(pl.col("administrador").all())
        .collect(engine="streaming")
    )
    chave, eh_pj = frame["pessoa"].to_numpy(), frame["pj"].to_numpy()
    ordem = np.lexsort((chave, eh_pj))
    chave, eh_pj = chave[ordem], eh_pj[ordem]
    nova = np.ones(len(ordem), dtype=bool)
    nova[1:] = (chave[1:] != chave[:-1]) | (eh_pj[1:] != eh_pj[:-1])
    pessoa = np.empty(len(ordem), dtype=np.int32)
    pessoa[ordem] = np.cumsum(nova, dtype=np.int32) - 1
    del ordem
    cnpjs, empresa = np.unique(frame["empresa"].to_numpy(), return_inverse=True)
    return Vinculos(
        cnpjs=cnpjs,
        empresa=empresa.astype(np.int32),
        pessoa=pessoa,
        administrador=frame["administrador"].to_numpy(),
        pessoa_pj=eh_pj[nova],
        chave=chave[nova],
    )


def mascara_da_variante(v: Vinculos, variante: str, articulacao: np.ndarray) -> np.ndarray:
    """Seção 5: as robustezas tiram vínculos da rede principal; `articulacao` vem da principal."""
    match variante:
        case "PRINCIPAL":
            return np.ones(len(v.pessoa), dtype=bool)
        case "SEM_ARTICULACAO":
            retirada = np.zeros(v.n_pessoas, dtype=bool)
            retirada[articulacao] = True
            return ~retirada[v.pessoa]
        case "SEM_PJ":
            return ~v.pessoa_pj[v.pessoa]
        case "SEM_ADMINISTRADOR":
            return ~v.administrador
    raise ValueError(variante)


BLOCO_DE_ARESTAS = 2_000_000


@dataclass(frozen=True)
class Grafo:
    """Grafo bipartido reduzido de uma variante.

    Vértices 0..n_empresas-1 são empresas, em ordem de CNPJ; os seguintes são pessoas, em ordem
    de id. `local` dá o vértice de cada empresa do universo (-1 fora do grafo) e `pessoas`, o id
    de cada vértice-pessoa. As listas de adjacência (CSR) servem à busca em largura.
    """

    cnpjs: np.ndarray
    local: np.ndarray
    pessoas: np.ndarray
    ptr_empresa: np.ndarray
    adj_empresa: np.ndarray
    ptr_pessoa: np.ndarray
    adj_pessoa: np.ndarray

    @property
    def n_empresas(self) -> int:
        return len(self.ptr_empresa) - 1

    def indices(self, empresas: np.ndarray) -> np.ndarray:
        """Vértice de cada CNPJ, ou -1 para empresas fora do grafo."""
        pos = _posicoes(self.cnpjs, empresas)
        return np.where(pos >= 0, self.local[pos], -1)

    def igraph(self) -> ig.Graph:
        """As arestas entram em blocos: na rede principal (9 milhões de arestas), passar todas
        de uma vez custou 1,7 GB além do grafo; em blocos de 2 milhões, 0,8 GB."""
        n_e = self.n_empresas
        empresa = np.repeat(np.arange(n_e, dtype=np.int32), np.diff(self.ptr_empresa))
        grafo = ig.Graph(n=n_e + len(self.pessoas))
        for inicio in range(0, len(empresa), BLOCO_DE_ARESTAS):
            bloco = slice(inicio, inicio + BLOCO_DE_ARESTAS)
            grafo.add_edges(np.column_stack((empresa[bloco], self.adj_empresa[bloco] + n_e)))
        return grafo


def _csr(origem: np.ndarray, destino: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(np.bincount(origem, minlength=n), out=ptr[1:])
    return ptr, destino[np.argsort(origem, kind="stable")]


def montar_grafo(v: Vinculos, mascara: np.ndarray) -> Grafo:
    pessoa, empresa = v.pessoa[mascara], v.empresa[mascara]
    ligadas = np.bincount(pessoa, minlength=v.n_pessoas) >= 2
    na_rede = ligadas[pessoa]
    pessoa, empresa = pessoa[na_rede], empresa[na_rede]
    del na_rede

    no_grafo = np.zeros(len(v.cnpjs), dtype=bool)
    no_grafo[empresa] = True
    local = np.full(len(v.cnpjs), -1, dtype=np.int32)
    local[no_grafo] = np.arange(np.count_nonzero(no_grafo), dtype=np.int32)
    pessoas = np.flatnonzero(ligadas).astype(np.int32)
    vertice_pessoa = np.cumsum(ligadas, dtype=np.int32) - 1
    e, p = local[empresa], vertice_pessoa[pessoa]
    del pessoa, empresa, vertice_pessoa

    ptr_e, adj_e = _csr(e, p, np.count_nonzero(no_grafo))
    ptr_p, adj_p = _csr(p, e, len(pessoas))
    return Grafo(v.cnpjs, local, pessoas, ptr_e, adj_e, ptr_p, adj_p)


def componentes_de_um_socio(grafo: Grafo) -> int:
    """Componentes de duas empresas e um único sócio compartilhado, no grafo reduzido."""
    grau_empresa = np.diff(grafo.ptr_empresa)
    pessoas_com_duas = grafo.ptr_pessoa[:-1][np.diff(grafo.ptr_pessoa) == 2]
    primeira = grafo.adj_pessoa[pessoas_com_duas]
    segunda = grafo.adj_pessoa[pessoas_com_duas + 1]
    return int(np.count_nonzero((grau_empresa[primeira] == 1) & (grau_empresa[segunda] == 1)))


def pessoas_articulacao(grafo: ig.Graph, n_empresas: int, pessoas: np.ndarray) -> np.ndarray:
    """Ids das pessoas cuja retirada divide um componente do grafo bipartido."""
    vertices = np.array(grafo.articulation_points(), dtype=np.int64)
    return pessoas[vertices[vertices >= n_empresas] - n_empresas]


def redes(grafo: Grafo, componentes: ig.VertexClustering) -> pl.DataFrame:
    """`id_rede` e tamanho por empresa do universo; fora do grafo, rede só sua."""
    membros = np.array(componentes.membership[: grafo.n_empresas], dtype=np.int64)
    tamanhos = np.bincount(membros)
    no_grafo = grafo.local >= 0
    id_rede = np.empty(len(grafo.cnpjs), dtype=np.int64)
    id_rede[no_grafo] = membros
    id_rede[~no_grafo] = len(tamanhos) + np.arange(np.count_nonzero(~no_grafo))
    tamanho = np.ones(len(grafo.cnpjs), dtype=np.int64)
    tamanho[no_grafo] = tamanhos[membros]
    return pl.DataFrame({"empresa": grafo.cnpjs, "id_rede": id_rede, "empresas_na_rede": tamanho})


def _vizinhos(
    ptr: np.ndarray, adj: np.ndarray, linhas: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Vizinhos de cada linha da CSR e, para cada vizinho, a posição da linha em `linhas`."""
    inicio = ptr[linhas]
    n = ptr[linhas + 1] - inicio
    deslocamento = np.repeat(inicio - np.cumsum(n) + n, n) + np.arange(n.sum())
    return adj[deslocamento], np.repeat(np.arange(len(linhas)), n)


SEM_CAMINHO = np.iinfo(np.int8).max


class Busca:
    """Busca em largura com várias origens; os vetores de marcação servem a todas as buscas."""

    def __init__(self, grafo: Grafo) -> None:
        self.grafo = grafo
        self._profundidade = np.full(grafo.n_empresas, SEM_CAMINHO, dtype=np.int8)
        self._pessoa_vista = np.zeros(len(grafo.pessoas), dtype=bool)

    def distancias(self, origens: np.ndarray, alvos: np.ndarray) -> np.ndarray:
        """δ de cada alvo até o conjunto `origens` (CNPJs), ou -1 além de `LIMITE_DISTANCIA`.

        Um passo entre empresas são dois no grafo bipartido (empresa → pessoa → empresa). A busca
        anda `LIMITE_DISTANCIA - 1` passos a partir das origens e o último a partir dos alvos,
        que são poucos, em vez de expandir a fronteira mais larga.
        """
        g, profundidade = self.grafo, self._profundidade
        fronteira = g.indices(np.unique(origens))
        fronteira = fronteira[fronteira >= 0]
        profundidade[fronteira] = 0
        vistas_empresa, vistas_pessoa = [fronteira], []
        for passo in range(1, config.LIMITE_DISTANCIA):
            pessoas = np.unique(_vizinhos(g.ptr_empresa, g.adj_empresa, fronteira)[0])
            pessoas = pessoas[~self._pessoa_vista[pessoas]]
            self._pessoa_vista[pessoas] = True
            empresas = np.unique(_vizinhos(g.ptr_pessoa, g.adj_pessoa, pessoas)[0])
            fronteira = empresas[profundidade[empresas] == SEM_CAMINHO]
            profundidade[fronteira] = passo
            vistas_empresa.append(fronteira)
            vistas_pessoa.append(pessoas)

        delta = np.where(np.isin(alvos, origens), 0, SEM_CAMINHO).astype(np.int16)
        local = g.indices(alvos)
        linhas = np.flatnonzero(local >= 0)
        delta[linhas] = np.minimum(delta[linhas], profundidade[local[linhas]])
        pessoas, de_alvo = _vizinhos(g.ptr_empresa, g.adj_empresa, local[linhas])
        empresas, de_pessoa = _vizinhos(g.ptr_pessoa, g.adj_pessoa, pessoas)
        np.minimum.at(
            delta, linhas[de_alvo[de_pessoa]], profundidade[empresas].astype(np.int16) + 1
        )

        profundidade[np.concatenate(vistas_empresa)] = SEM_CAMINHO
        if vistas_pessoa:
            self._pessoa_vista[np.concatenate(vistas_pessoa)] = False
        return np.where(delta <= config.LIMITE_DISTANCIA, delta, -1).astype(np.int8)


def _por_chave(frame: pl.DataFrame, chave: list[str]) -> dict[tuple, np.ndarray]:
    agrupado = frame.group_by(chave).agg("empresa")
    return {
        tuple(linha[:-1]): np.array(linha[-1], dtype=np.uint32)
        for linha in agrupado.select(*chave, "empresa").iter_rows()
    }


def distancias(
    grafo: Grafo, rede: pl.DataFrame, origens: pl.DataFrame, alvos: pl.DataFrame
) -> pl.DataFrame:
    """δ e faixa de cada alvo (município, empresa) até cada grupo, com as origens do município.

    Além do limite, a faixa é 3+ quando o alvo está na rede de alguma origem e inf caso contrário.
    """
    busca = Busca(grafo)
    id_rede = rede["id_rede"].to_numpy()

    def rede_de(cnpjs: np.ndarray) -> np.ndarray:
        pos = _posicoes(grafo.cnpjs, cnpjs)
        return np.where(pos >= 0, id_rede[pos], -1)

    origens_de = _por_chave(origens, ["cod_municipio_tse", "grupo"])
    blocos = []
    for (municipio,), empresas in sorted(_por_chave(alvos, ["cod_municipio_tse"]).items()):
        redes_alvo = rede_de(empresas)
        for grupo in ("A", "B"):
            fonte = origens_de.get((municipio, grupo), np.zeros(0, dtype=np.uint32))
            ligada = (redes_alvo >= 0) & np.isin(redes_alvo, rede_de(fonte))
            blocos.append(
                pl.DataFrame(
                    {
                        "cod_municipio_tse": municipio,
                        "grupo": grupo,
                        "empresa": empresas,
                        "distancia": busca.distancias(fonte, empresas),
                        "ligada": ligada,
                    }
                )
            )
    if not blocos:
        return pl.DataFrame(
            schema={
                "cod_municipio_tse": pl.String,
                "grupo": DISTANCIAS.esquema["grupo"],
                "empresa": pl.UInt32,
                "distancia": pl.Int8,
                "faixa": FAIXA,
            }
        )
    distancia = pl.col("distancia")
    return (
        pl.concat(blocos)
        .with_columns(
            pl.col("grupo").cast(DISTANCIAS.esquema["grupo"]),
            distancia.replace(-1, None),
        )
        .with_columns(
            faixa=pl.when(distancia < 3)
            .then(distancia.cast(pl.String))
            .when(distancia.is_not_null() | pl.col("ligada"))
            .then(pl.lit("3+"))
            .otherwise(pl.lit("inf"))
            .cast(FAIXA)
        )
        .drop("ligada")
    )


@dataclass(frozen=True)
class Resultado:
    """Saídas de uma variante, com CNPJ ainda inteiro, e as descritivas dela."""

    rede: pl.DataFrame
    distancias: pl.DataFrame
    descritivas: dict[str, pl.DataFrame]


def origens_da_variante(conexoes: pl.DataFrame, v: Vinculos, mascara: np.ndarray) -> pl.DataFrame:
    """Conexões diretas cujo vínculo doador–empresa sobrevive na variante."""
    chave = pl.DataFrame(
        {
            "e": v.posicoes(conexoes["empresa"].to_numpy()),
            "p": v.pessoas_fisicas(conexoes["pessoa"].to_numpy()),
        }
    )
    candidatos = np.flatnonzero(mascara & np.isin(v.empresa, chave["e"].to_numpy()))
    vivos = pl.DataFrame(
        {"e": v.empresa[candidatos], "p": v.pessoa[candidatos]}, schema=chave.schema
    )
    return (
        pl.concat([conexoes, chave], how="horizontal")
        .join(vivos, on=["e", "p"], how="semi")
        .select("cod_municipio_tse", "grupo", "empresa")
    )


def calcular_variante(
    v: Vinculos, mascara: np.ndarray, conexoes: pl.DataFrame, alvos: pl.DataFrame
) -> tuple[Resultado, np.ndarray]:
    """Resultado da variante e as pessoas que são pontos de articulação no grafo dela."""
    grafo = montar_grafo(v, mascara)
    g = grafo.igraph()
    articulacao = pessoas_articulacao(g, grafo.n_empresas, grafo.pessoas)
    rede = redes(grafo, g.connected_components())
    del g
    origens = origens_da_variante(conexoes, v, mascara)
    delta = distancias(grafo, rede, origens, alvos)
    motivos = componentes_de_um_socio(grafo)
    del grafo
    grau_pessoa = np.bincount(v.pessoa[mascara], minlength=v.n_pessoas)
    resultado = Resultado(
        rede=rede,
        distancias=delta,
        descritivas=descritivas.da_variante(
            rede,
            np.bincount(v.empresa[mascara], minlength=len(v.cnpjs)),
            grau_pessoa[grau_pessoa > 0],
            delta,
            origens,
            len(articulacao),
            motivos,
        ),
    )
    return resultado, articulacao


def variantes(
    v: Vinculos, conexoes: pl.DataFrame, alvos: pl.DataFrame
) -> Iterator[tuple[str, Resultado]]:
    """As quatro variantes, uma de cada vez; a principal vem antes porque dá a articulação."""
    articulacao = np.zeros(0, dtype=np.int32)
    for variante in VARIANTE.categories:
        mascara = mascara_da_variante(v, variante, articulacao)
        resultado, articulacao_da_variante = calcular_variante(v, mascara, conexoes, alvos)
        del mascara
        if variante == "PRINCIPAL":
            articulacao = articulacao_da_variante
        yield variante, resultado
        del resultado


def calcular(v: Vinculos, conexoes: pl.DataFrame, alvos: pl.DataFrame) -> dict[str, Resultado]:
    """As quatro variantes a partir de `vinculos_da_fotografia`, `conexoes_com_chave` e `alvos`."""
    return dict(variantes(v, conexoes, alvos))


def conexoes_com_chave(conexoes: pl.LazyFrame) -> pl.DataFrame:
    return conexoes.select(
        "cod_municipio_tse",
        "grupo",
        pl.col("cnpj_basico").cast(pl.UInt32).alias("empresa"),
        pl.col("id_pessoa").str.to_integer(base=16, dtype=pl.UInt64).alias("pessoa"),
    ).collect()


def alvos_dos_empenhos(empenhos: pl.LazyFrame) -> pl.DataFrame:
    """Empresas com algum empenho no município, de 2021 a 2025: o painel só usa δ delas."""
    return (
        empenhos.select("cod_municipio_tse", pl.col("cnpj_basico").cast(pl.UInt32).alias("empresa"))
        .unique()
        .collect(engine="streaming")
    )


def saida(tabela: schemas.Tabela, variante: str, resultado: Resultado) -> pl.DataFrame:
    """`rede` ou `distancias` de uma variante no esquema da tabela, com o CNPJ de volta a texto."""
    return (
        getattr(resultado, tabela.nome)
        .with_columns(
            pl.col("empresa").cast(pl.String).str.zfill(8).alias("cnpj_basico"),
            pl.lit(variante, dtype=VARIANTE).alias("variante"),
        )
        .select(tabela.esquema.names())
    )


def tabelas(resultados: dict[str, Resultado]) -> dict[str, pl.DataFrame]:
    """`rede` e `distancias` com as variantes empilhadas."""
    return {
        tabela.nome: pl.concat(saida(tabela, v, r) for v, r in resultados.items())
        for tabela in (REDE, DISTANCIAS)
    }


def executar(ctx: Contexto) -> None:
    """Cada variante vai para um Parquet parcial antes da seguinte; as tabelas finais são a
    concatenação deles, gravada em fluxo: a `rede` tem 45 milhões de linhas."""
    vinculos = vinculos_da_fotografia(ctx.ler(SOCIOS))
    conexoes = conexoes_com_chave(ctx.ler(CONEXOES_DIRETAS))
    alvos = alvos_dos_empenhos(ctx.ler(EMPENHOS))
    pasta = ctx.caminhos.dados / "tmp" / "network"
    shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True)
    por_variante = {}
    for variante, resultado in variantes(vinculos, conexoes, alvos):
        for tabela in (REDE, DISTANCIAS):
            saida(tabela, variante, resultado).write_parquet(
                pasta / f"{tabela.nome}-{variante}.parquet"
            )
        por_variante[variante] = resultado.descritivas
        del resultado
    del vinculos
    for tabela in (REDE, DISTANCIAS):
        partes = [pasta / f"{tabela.nome}-{v}.parquet" for v in VARIANTE.categories]
        schemas.gravar_em_fluxo(pl.scan_parquet(partes), tabela, ctx.caminho(tabela))
    shutil.rmtree(pasta)
    descritivas.gravar(por_variante, ctx.caminhos.resultados / "tables")
