"""Figuras do relatório e do deck: estilo comum, registro e ajudantes de gráfico.

Cada figura é uma função `Tabelas -> matplotlib.figure.Figure` registrada com `@figura`. O
registro sabe quais tabelas de `results/tables` cada figura exige; `gerar_todas` pula, com aviso,
as que ainda não têm entrada, então o relatório e o deck compilam com o que existir.

A etapa `estimate` usa `rdd_plot` e `salvar` para as figuras de descontinuidade (arquivos
`rdd_*.pdf` e `.png` em `results/figures`, que o relatório e o deck procuram pelo nome).
Todas as figuras saem em PDF (relatório) e PNG (deck), em escala de cinza e sem identificadores.
"""

import math
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullFormatter  # noqa: E402

from redes.config import SUPRESSAO_MINIMA, Caminhos  # noqa: E402
from redes.descritivas import FAIXAS_GRAU, FAIXAS_TAMANHO  # noqa: E402

CINZAS = ("#1a1a1a", "#7a7a7a", "#c4c4c4")
HACHURAS = ("", "////", "....")
LARGURA_COLUNA = 3.4
"""Meia largura útil do relatório, em polegadas; as figuras do relatório partem dela."""


def estilo() -> dict[str, object]:
    """rcParams: serifa tipo Times, texto pequeno, sem moldura superior e direita."""
    return {
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "font.size": 8,
        "axes.titlesize": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.fontsize": 7,
        "legend.frameon": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "axes.prop_cycle": matplotlib.cycler(color=list(CINZAS)),
        "figure.dpi": 100,
        "savefig.dpi": 220,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
        "pdf.fonttype": 42,
    }


def formato_br(valor: float, _posicao: int | None = None) -> str:
    """Rótulo de eixo em convenção brasileira: 1.234,5."""
    if valor == int(valor):
        texto = f"{int(valor):,}".replace(",", ".")
    else:
        casas = max(2, 2 - math.floor(math.log10(abs(valor))))
        texto = f"{valor:,.{casas}f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",")
        texto = texto.replace("X", ".")
    return texto


def suprimir(valor: float | None) -> float:
    """Célula com menos de `SUPRESSAO_MINIMA` unidades não aparece (SPEC, Limites)."""
    if valor is None or 0 < valor < SUPRESSAO_MINIMA:
        return math.nan
    return float(valor)


# --- registro --------------------------------------------------------------------------------


class Tabelas(Mapping[str, pl.DataFrame]):
    """Leitura preguiçosa dos CSV de `results/tables`, por nome sem extensão."""

    def __init__(self, pasta: Path):
        self._pasta = pasta

    def __getitem__(self, nome: str) -> pl.DataFrame:
        caminho = self._pasta / f"{nome}.csv"
        if not caminho.exists():
            raise KeyError(nome)
        return pl.read_csv(caminho)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(p.stem for p in self._pasta.glob("*.csv")))

    def __len__(self) -> int:
        return sum(1 for _ in self._pasta.glob("*.csv"))

    def __contains__(self, nome: object) -> bool:
        return (self._pasta / f"{nome}.csv").exists()


@dataclass(frozen=True)
class Figura:
    nome: str
    requer: tuple[str, ...]
    desenhar: Callable[[Tabelas], Figure]


FIGURAS: dict[str, Figura] = {}


def figura(nome: str, requer: tuple[str, ...] = ()):
    def registrar(funcao: Callable[[Tabelas], Figure]) -> Callable[[Tabelas], Figure]:
        if nome in FIGURAS:
            raise ValueError(f"figura duplicada: {nome}")
        FIGURAS[nome] = Figura(nome, requer, funcao)
        return funcao

    return registrar


def salvar(fig: Figure, nome: str, pasta: Path) -> list[Path]:
    """Grava `nome.pdf` e `nome.png` de forma atômica e sem carimbo de data (diffs estáveis)."""
    pasta.mkdir(parents=True, exist_ok=True)
    gravados = []
    for formato, metadados in (("pdf", {"CreationDate": None}), ("png", {"Software": None})):
        final = pasta / f"{nome}.{formato}"
        provisorio = pasta / f".{nome}.{os.getpid()}.{formato}"
        fig.savefig(provisorio, format=formato, metadata=metadados)
        os.replace(provisorio, final)
        gravados.append(final)
    plt.close(fig)
    return gravados


def gerar_todas(caminhos: Caminhos, nomes: tuple[str, ...] | None = None) -> list[str]:
    """Gera as figuras registradas cujas tabelas existem; devolve os nomes gerados."""
    tabelas = Tabelas(caminhos.resultados / "tables")
    geradas = []
    with plt.rc_context(estilo()):
        for fig in FIGURAS.values():
            if nomes is not None and fig.nome not in nomes:
                continue
            faltam = [t for t in fig.requer if t not in tabelas]
            if faltam:
                print(f"aviso: figura {fig.nome} pulada, faltam {faltam}", file=sys.stderr)
                continue
            salvar(fig.desenhar(tabelas), fig.nome, caminhos.resultados / "figures")
            geradas.append(fig.nome)
    return geradas


# --- ajudantes de RDD ------------------------------------------------------------------------


def ajuste_local(
    margem: np.ndarray, y: np.ndarray, peso: np.ndarray, banda: float
) -> tuple[float, float] | None:
    """Regressão linear local, núcleo triangular, num lado do corte.

    Devolve (intercepto em 0, inclinação), ou None com menos de dois pontos distintos na banda.
    O peso de cada observação é o da amostra vezes o núcleo, como na especificação (5).
    """
    dentro = np.abs(margem) < banda
    x, v = margem[dentro], y[dentro]
    w = peso[dentro] * (1 - np.abs(x) / banda)
    if len(np.unique(x)) < 2 or w.sum() <= 0:
        return None
    raiz = np.sqrt(w)
    A = np.column_stack([np.ones_like(x), x]) * raiz[:, None]
    coef, *_ = np.linalg.lstsq(A, v * raiz, rcond=None)
    return float(coef[0]), float(coef[1])


def pontos_por_faixa(dados: pl.DataFrame, janela: float, n_faixas: int) -> pl.DataFrame:
    """Média ponderada de `y` por faixa de margem; faixas com menos de 5 observações somem."""
    largura = 2 * janela / n_faixas
    return (
        dados.filter(pl.col("margem").abs() <= janela)
        .with_columns(
            faixa=((pl.col("margem") + janela) / largura)
            .floor()
            .clip(0, n_faixas - 1)
            .cast(pl.Int32)
        )
        .group_by("faixa")
        .agg(
            n=pl.len(),
            x=((pl.col("margem") * pl.col("peso")).sum() / pl.col("peso").sum()),
            y=((pl.col("y") * pl.col("peso")).sum() / pl.col("peso").sum()),
        )
        .filter(pl.col("n") >= SUPRESSAO_MINIMA)
        .sort("faixa")
    )


def rdd_plot(
    dados: pl.DataFrame,
    *,
    banda: float | None = None,
    janela: float | None = None,
    n_faixas: int = 20,
    rotulo_x: str = "Margem do incumbente (p.p.)",
    rotulo_y: str = "Resultado em 2025",
    tamanho: tuple[float, float] = (LARGURA_COLUNA, 2.5),
) -> Figure:
    """Dispersão por faixas e ajuste linear local de cada lado do corte.

    `dados` tem as colunas `margem` (p.p.; negativa quando o incumbente perde), `y` e `peso`
    (município com o mesmo peso total). A janela mostrada é `janela`, ou duas bandas, ou todo o
    suporte; o ajuste usa só |margem| <= banda. Faixas com menos de cinco observações não
    aparecem, em respeito à regra de supressão.
    """
    suporte = float(dados["margem"].abs().max() or 0)
    janela = janela or (2 * banda if banda else suporte) or 1.0
    fig, ax = plt.subplots(figsize=tamanho)
    pontos = pontos_por_faixa(dados, janela, n_faixas)
    ax.scatter(pontos["x"], pontos["y"], s=14, color=CINZAS[0], zorder=3)
    margem, y, peso = (dados[c].to_numpy().astype(float) for c in ("margem", "y", "peso"))
    for sinal in (-1, 1) if banda is not None else ():
        no_lado = margem < 0 if sinal < 0 else margem >= 0
        ajuste = ajuste_local(margem[no_lado], y[no_lado], peso[no_lado], banda)
        if ajuste is None:
            continue
        a, b = ajuste
        xs = np.linspace(0, sinal * min(banda, janela), 50)
        ax.plot(xs, a + b * xs, color=CINZAS[0], lw=1.2, zorder=2)
    ax.axvline(0, color=CINZAS[1], lw=0.7, ls="--", zorder=1)
    ax.set_xlim(-janela, janela)
    ax.set_xlabel(rotulo_x)
    ax.set_ylabel(rotulo_y)
    ax.xaxis.set_major_formatter(FuncFormatter(formato_br))
    ax.yaxis.set_major_formatter(FuncFormatter(formato_br))
    if pontos.is_empty() and not ax.lines[:-1]:
        ax.text(0.5, 0.55, "Sem médias publicáveis", transform=ax.transAxes, ha="center")
    return fig


def _contrastes(t: Tabelas, hipotese: str, chave: str, rotulos: dict[str, str]) -> Figure:
    resumo = t["resumo_estimacao"].filter(
        (pl.col("hipotese") == hipotese) & (pl.col("tipo") == "contraste")
    )
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 2.25))
    for i, valor in enumerate(rotulos):
        recorte = resumo.filter(pl.col(chave) == valor)
        linha = recorte.row(0, named=True) if recorte.height else {}
        efeito, inferior, superior = (linha.get(c) for c in ("estimativa", "ic_inf", "ic_sup"))
        if all(x is not None for x in (efeito, inferior, superior)):
            ax.errorbar(
                i,
                efeito,
                yerr=[[efeito - inferior], [superior - efeito]],
                fmt="o",
                markersize=3,
                capsize=3,
                color=CINZAS[0],
            )
        else:
            ax.text(i, 0.08, "n.d.", ha="center", transform=ax.get_xaxis_transform())
    ax.axhline(0, color=CINZAS[1], lw=0.7, ls="--")
    if not ax.containers:
        ax.set(ylim=(-0.1, 1), yticks=[0])
    ax.set_xticks(range(len(rotulos)), list(rotulos.values()))
    ax.set_xlim(-0.5, len(rotulos) - 0.5)
    ax.set_ylabel("Contraste no corte")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.4g}".replace(".", ",")))
    return fig


@figura("gradiente_h2", ("resumo_estimacao",))
def fig_gradiente(t: Tabelas) -> Figure:
    return _contrastes(
        t, "H2", "categoria", {f"vencedor_faixa_{d}": f"δ = {d}" for d in ("0", "1", "2", "3+")}
    )


@figura("decomposicao_h3", ("resumo_estimacao",))
def fig_decomposicao(t: Tabelas) -> Figure:
    return _contrastes(
        t,
        "H3",
        "resultado",
        {"termo_r1": "R1", "termo_r2": "R2", "termo_r3": "R3", "variacao_total": "Total"},
    )


# --- descritivas da rede ---------------------------------------------------------------------

_FAIXAS_DISTANCIA = ["0", "1", "2", "3+", "inf"]


def _barras_agrupadas(
    ax, rotulos: list[str], series: list[tuple[str, list[float]]], largura_total: float = 0.8
) -> None:
    n = len(series)
    passo = largura_total / n
    x = np.arange(len(rotulos))
    for i, (nome, valores) in enumerate(series):
        ax.bar(
            x - largura_total / 2 + passo * (i + 0.5),
            valores,
            width=passo * 0.92,
            label=nome,
            color=CINZAS[i % 3] if HACHURAS[i % 3] == "" else "white",
            edgecolor=CINZAS[0],
            hatch=HACHURAS[i % 3],
            linewidth=0.6,
        )
    ax.set_xticks(x, rotulos)


def _por_faixa(
    frame: pl.DataFrame, faixas: list[str], coluna_faixa: str, valor: str
) -> list[float]:
    achado = {str(r[coluna_faixa]): r[valor] for r in frame.iter_rows(named=True)}
    return [suprimir(achado.get(f)) for f in faixas]


def _distribuicao_indisponivel(ax) -> None:
    ax.set_axis_off()
    ax.text(0.5, 0.5, "Distribuição indisponível", ha="center", va="center", transform=ax.transAxes)


@figura("rede_componentes", requer=("rede_componentes", "rede_resumo"))
def fig_componentes(t: Tabelas) -> Figure:
    tabela = t["rede_componentes"].with_columns(pl.col("faixa_tamanho").cast(pl.Utf8))
    nomes = {"PRINCIPAL": "Rede principal", "SEM_ARTICULACAO": "Sem pontos de articulação"}
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 2.5))
    faixas = list(FAIXAS_TAMANHO)
    series = []
    for variante, rotulo in nomes.items():
        sub = tabela.filter(pl.col("variante") == variante)
        total = (
            t["rede_resumo"]
            .filter((pl.col("variante") == variante) & (pl.col("indicador") == "empresas"))["valor"]
            .item()
        )
        if total:
            valores = _por_faixa(sub, faixas, "faixa_tamanho", "empresas")
            series.append((rotulo, [100 * v / total for v in valores]))
    if not series:
        _distribuicao_indisponivel(ax)
        return fig
    _barras_agrupadas(ax, faixas, series)
    ax.set_yscale("log")
    ax.set_xlabel("Tamanho do componente (empresas)")
    ax.set_ylabel("Empresas (% do total)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: formato_br(v)))
    ax.yaxis.set_minor_formatter(NullFormatter())
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    ax.legend(loc="upper right")
    return fig


@figura("rede_distancias", requer=("rede_distancias",))
def fig_distancias(t: Tabelas) -> Figure:
    tabela = t["rede_distancias"].with_columns(pl.col("faixa").cast(pl.Utf8))
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 2.5))
    series = []
    for grupo in ("A", "B"):
        sub = tabela.filter((pl.col("variante") == "PRINCIPAL") & (pl.col("grupo") == grupo))
        series.append(
            (
                f"Grupo {grupo}",
                _por_faixa(sub, _FAIXAS_DISTANCIA, "faixa", "pares_empresa_municipio"),
            )
        )
    if not any(v > 0 for _, valores in series for v in valores):
        _distribuicao_indisponivel(ax)
        return fig
    _barras_agrupadas(ax, ["0", "1", "2", "3+", "∞"], series)
    ax.set_yscale("log")
    ax.set_xlabel(r"Distância $\delta$ até o grupo (vizinhanças)")
    ax.set_ylabel("Pares empresa–município")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: formato_br(v)))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.legend(loc="upper left")
    return fig


@figura("rede_graus", requer=("rede_graus",))
def fig_graus(t: Tabelas) -> Figure:
    tabela = t["rede_graus"].with_columns(pl.col("faixa_grau").cast(pl.Utf8))
    fig, eixos = plt.subplots(1, 2, figsize=(2 * LARGURA_COLUNA, 2.3), sharey=True)
    for ax, vertice, titulo in zip(
        eixos,
        ("empresa", "pessoa"),
        ("Empresas (sócios por empresa)", "Pessoas (empresas por pessoa)"),
        strict=True,
    ):
        sub = tabela.filter((pl.col("variante") == "PRINCIPAL") & (pl.col("vertice") == vertice))
        faixas = list(FAIXAS_GRAU)
        valores = _por_faixa(sub, faixas, "faixa_grau", "vertices")
        if not any(v > 0 for v in valores):
            _distribuicao_indisponivel(ax)
            continue
        _barras_agrupadas(ax, faixas, [(titulo, valores)], largura_total=0.7)
        ax.set_yscale("log")
        ax.set_title(titulo)
        ax.set_xlabel("Grau")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: formato_br(v)))
        ax.yaxis.set_minor_formatter(NullFormatter())
    eixos[0].set_ylabel("Vértices")
    return fig


@figura("rede_exemplo_observado", ("rede_resumo",))
def fig_exemplo_observado(t: Tabelas) -> Figure:
    recorte = t["rede_resumo"].filter(
        (pl.col("variante") == "PRINCIPAL")
        & (pl.col("indicador") == "componentes_duas_empresas_um_socio")
    )
    n = recorte["valor"].item() if recorte.height else None
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 1.85))
    ax.set(xlim=(-1.5, 1.5), ylim=(-0.4, 1.45), aspect="equal")
    ax.axis("off")
    if n is None or 0 < n < SUPRESSAO_MINIMA:
        ax.text(0, 0.5, "Frequência indisponível", ha="center")
        return fig
    caixa = {"boxstyle": "round", "facecolor": "white"}
    for x in (-0.9, 0.9):
        ax.plot([0, x], [1, 0.15], color=CINZAS[1], zorder=1)
        ax.text(x, 0.15, "Empresa", ha="center", va="center", bbox=caixa)
    ax.text(0, 1, "Sócio em comum", ha="center", va="center", bbox=caixa)
    ax.text(0, -0.25, f"Padrão em {formato_br(n)} componentes", ha="center")
    return fig


@figura("figura1_exemplo")
def fig_exemplo(_t: Tabelas) -> Figure:
    """Redesenho da Figura 1 do projeto: X, Y, Z; Ana, Bruno, Carla, Daniel; rótulos de δ."""
    fig, ax = plt.subplots(figsize=(6.2, 2.7))
    ax.set_xlim(-0.2, 10.2)
    ax.set_ylim(-1.2, 4.6)
    ax.set_aspect("equal")
    ax.axis("off")
    pessoas = {"Ana": 1.0, "Bruno": 3.6, "Carla": 6.4, "Daniel": 9.0}
    empresas = {"X": 2.3, "Y": 5.0, "Z": 7.7}
    deltas = {
        "X": (r"$\delta_{XA}=0$", r"$\delta_{XB}=2$"),
        "Y": (r"$\delta_{YA}=1$", r"$\delta_{YB}=1$"),
        "Z": (r"$\delta_{ZA}=2$", r"$\delta_{ZB}=0$"),
    }
    socios = [
        ("Ana", "X"),
        ("Bruno", "X"),
        ("Bruno", "Y"),
        ("Carla", "Y"),
        ("Carla", "Z"),
        ("Daniel", "Z"),
    ]
    y_pessoa, y_empresa = 2.4, 0.9
    for p, e in socios:
        ax.plot([pessoas[p], empresas[e]], [y_pessoa - 0.5, y_empresa + 0.3], color="black", lw=0.8)
    for nome, x in pessoas.items():
        ax.add_patch(
            Circle((x, y_pessoa), 0.62, facecolor="white", edgecolor="black", lw=0.8, zorder=3)
        )
        ax.text(x, y_pessoa, nome, ha="center", va="center", zorder=4)
    for nome, x in empresas.items():
        ax.add_patch(
            FancyBboxPatch(
                (x - 0.5, y_empresa - 0.3), 1.0, 0.6, boxstyle="round,pad=0.02,rounding_size=0.08",
                facecolor="white", edgecolor="black", lw=0.8, zorder=3,
            )
        )  # fmt: skip
        ax.text(x, y_empresa, nome, ha="center", va="center", style="italic", zorder=4)
        for i, rotulo in enumerate(deltas[nome]):
            ax.text(x, y_empresa - 0.75 - 0.55 * i, rotulo, ha="center", va="center", fontsize=7.5)
    for grupo, x_pessoa in (("A", pessoas["Ana"]), ("B", pessoas["Daniel"])):
        ax.add_patch(
            FancyBboxPatch(
                (x_pessoa - 0.75, 4.0), 1.5, 0.55, boxstyle="square,pad=0",
                facecolor=CINZAS[2], edgecolor="black", lw=0.8, zorder=3,
            )
        )  # fmt: skip
        ax.text(x_pessoa, 4.27, rf"Grupo $\mathit{{{grupo}}}$", ha="center", va="center", zorder=4)
        ax.annotate(
            "", xy=(x_pessoa, 4.0), xytext=(x_pessoa, y_pessoa + 0.65),
            arrowprops={"arrowstyle": "-|>", "ls": "--", "lw": 0.7, "color": "black"},
        )  # fmt: skip
    return fig
