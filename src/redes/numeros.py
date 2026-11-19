"""Números do relatório e do deck: lidos de `resultados/tables/*.csv`, nunca digitados à mão.

Convenção das tabelas (CSV em formato longo, uma linha por combinação de chaves):

- colunas de chave são as que não são numéricas, mais as listadas em `CHAVES_NUMERICAS`;
- colunas de valor são as numéricas restantes; célula vazia vale "n.d.".

Cada valor vira uma macro de nome determinístico, `\\n` + codificação de
(tabela, chaves da linha..., coluna). Nomes de macro só podem ter letras, então a codificação
usa letras minúsculas como símbolos literais e maiúsculas como marcadores:

    minúscula       ela mesma
    maiúscula       `X` + minúscula        (PRINCIPAL vira Xpxrxixnxcxixpxaxl)
    dígito d        `Z` + letra a..j       (0 vira Za, 9 vira Zj)
    `_ - + . espaço`  `Yu Yh Yp Yd Ys`
    outro caractere `YY` + ordinal com três letras a..j
    separador       `Q`

A análise é livre de prefixo (X, Y, Z e Q nunca aparecem sozinhos como literal), logo a
codificação é injetiva e `decodificar` a inverte. Os testes conferem isso.

Além das macros brutas há apelidos semânticos (`DESTAQUES`), com formato escolhido, que são os
que o texto do relatório e do deck usam.
"""

import csv
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ND = "n.d."

CHAVES_NUMERICAS = frozenset({"ano", "faixa", "limiar", "fator_banda", "k", "hipotese"})

_ESPECIAIS = {"_": "u", "-": "h", "+": "p", ".": "d", " ": "s"}
_INVERSO_ESPECIAIS = {v: k for k, v in _ESPECIAIS.items()}
_LETRAS_DIGITO = "abcdefghij"


def _codificar_texto(texto: str) -> str:
    saida: list[str] = []
    for c in texto:
        if "a" <= c <= "z":
            saida.append(c)
        elif "A" <= c <= "Z":
            saida.append("X" + c.lower())
        elif "0" <= c <= "9":
            saida.append("Z" + _LETRAS_DIGITO[int(c)])
        elif c in _ESPECIAIS:
            saida.append("Y" + _ESPECIAIS[c])
        elif ord(c) < 1000:
            saida.append("YY" + "".join(_LETRAS_DIGITO[int(d)] for d in f"{ord(c):03d}"))
        else:
            raise ValueError(f"caractere fora do alfabeto de macros: {c!r}")
    return "".join(saida)


def nome_macro(tabela: str, chaves: Sequence[str], coluna: str) -> str:
    partes = [_codificar_texto(p) for p in (tabela, *chaves, coluna)]
    return "n" + "Q".join(partes)


def decodificar(nome: str) -> tuple[str, tuple[str, ...], str]:
    """Inverso de `nome_macro`; levanta ValueError para nome fora da codificação."""
    if not nome.startswith("n"):
        raise ValueError(nome)
    partes: list[str] = [""]
    i = 1
    corpo = nome
    while i < len(corpo):
        c = corpo[i]
        if c == "Q":
            partes.append("")
            i += 1
        elif c == "X":
            partes[-1] += corpo[i + 1].upper()
            i += 2
        elif c == "Z":
            partes[-1] += str(_LETRAS_DIGITO.index(corpo[i + 1]))
            i += 2
        elif c == "Y" and corpo[i + 1] == "Y":
            digitos = "".join(str(_LETRAS_DIGITO.index(d)) for d in corpo[i + 2 : i + 5])
            partes[-1] += chr(int(digitos))
            i += 5
        elif c == "Y":
            partes[-1] += _INVERSO_ESPECIAIS[corpo[i + 1]]
            i += 2
        elif "a" <= c <= "z":
            partes[-1] += c
            i += 1
        else:
            raise ValueError(nome)
    if len(partes) < 2:
        raise ValueError(nome)
    return partes[0], tuple(partes[1:-1]), partes[-1]


# --- formatação, convenção brasileira -------------------------------------------------------


def _agrupar_milhares(digitos: str) -> str:
    grupos: list[str] = []
    while digitos:
        grupos.append(digitos[-3:])
        digitos = digitos[:-3]
    return ".".join(reversed(grupos))


def inteiro(v: float) -> str:
    """12345678 vira `12.345.678`."""
    r = round(v)
    return ("-" if r < 0 else "") + _agrupar_milhares(str(abs(r)))


def decimal(v: float, casas: int = 2) -> str:
    """1234.5 vira `1.234,50`."""
    texto = f"{abs(v):.{casas}f}"
    parte_inteira, _, frac = texto.partition(".")
    sinal = "-" if v < 0 and float(texto) != 0 else ""
    corpo = _agrupar_milhares(parte_inteira) + ("," + frac if frac else "")
    return sinal + corpo


def percentual(v: float, casas: int = 1) -> str:
    """Fração 0,116 vira `11,6\\%`; o `%` já sai escapado para LaTeX em `latex_seguro`."""
    return decimal(100 * v, casas) + "%"


def pontos_percentuais(v: float, casas: int = 1) -> str:
    """Diferença entre percentuais, em pontos: `+1,2 p.p.` (sinal explícito)."""
    texto = decimal(v, casas)
    return ("+" if v > 0 and not texto.startswith("-") else "") + texto + " p.p."


def leitura_h2_comparaveis(linhas: Iterator[dict]) -> str:
    """Descreve o suporte e os contrastes estimáveis da análise de sensibilidade."""
    estimadas = []
    sem_estimativa = []
    for linha in linhas:
        if linha["tipo"] != "contraste" or linha["placebo"]:
            continue
        faixa = linha["categoria"].rsplit("_", 1)[1]
        if linha["estimavel"]:
            efeito, inf, sup = (
                decimal(100 * linha[c], 3) for c in ("estimativa", "ic_inf", "ic_sup")
            )
            estimadas.append(
                f"No recorte comparável da faixa {faixa}, o contraste foi de {efeito} p.p. "
                f"(IC de 95% de {inf} a {sup})."
            )
        else:
            sem_estimativa.append(faixa)
    frases = []
    if sem_estimativa:
        faixas = ", ".join(sem_estimativa)
        recorte = "na faixa" if len(sem_estimativa) == 1 else "nas faixas"
        frases.append(f"No recorte comparável, a estimação ficou indefinida {recorte} {faixas}.")
    frases.extend(estimadas)
    return " ".join(frases)


def reais_bilhoes(v: float, casas: int = 1) -> str:
    """Reais em unidades viram `R$ 1,2 bi`."""
    return "R$ " + decimal(v / 1e9, casas) + " bi"


def reais_milhoes(v: float, casas: int = 1) -> str:
    return "R$ " + decimal(v / 1e6, casas) + " mi"


def automatico(v: float) -> str:
    """Formato das macros brutas: inteiro se for inteiro, senão três algarismos significativos."""
    if v == round(v):
        return inteiro(v)
    casas = max(2, 2 - math.floor(math.log10(abs(v)))) if v else 2
    return decimal(v, min(casas, 6))


FORMATOS: Mapping[str, Callable[[float], str]] = {
    "auto": automatico,
    "int": inteiro,
    "dec1": lambda v: decimal(v, 1),
    "dec2": lambda v: decimal(v, 2),
    "dec3": lambda v: decimal(v, 3),
    "pct": percentual,
    "pp": pontos_percentuais,
    "rs_bi": reais_bilhoes,
    "rs_mi": reais_milhoes,
}


def latex_seguro(texto: str) -> str:
    """Escapa `%` e `&` dos textos formatados; o menos vira sinal matemático."""
    texto = texto.replace("%", r"\%").replace("&", r"\&")
    return texto.replace("-", "\\textminus{}") if texto.startswith("-") else texto


# --- leitura das tabelas ---------------------------------------------------------------------


def _eh_numero(texto: str) -> bool:
    try:
        float(texto)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class Celula:
    tabela: str
    chaves: tuple[str, ...]
    coluna: str
    valor: float | None


def celulas_da_tabela(caminho: Path) -> Iterator[Celula]:
    with caminho.open(newline="", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        colunas = list(leitor.fieldnames or [])
        linhas = list(leitor)
    if not colunas:
        return

    def numerica(coluna: str) -> bool:
        textos = [linha[coluna] for linha in linhas if linha[coluna] != ""]
        return coluna not in CHAVES_NUMERICAS and bool(textos) and all(map(_eh_numero, textos))

    valores = [c for c in colunas if numerica(c)]
    chaves = [c for c in colunas if c not in valores]
    for linha in linhas:
        k = tuple(linha[c] for c in chaves)
        for c in valores:
            texto = linha[c]
            valor = float(texto) if texto else math.nan
            yield Celula(caminho.stem, k, c, valor if math.isfinite(valor) else None)


@dataclass(frozen=True)
class Destaque:
    """Apelido semântico de uma célula, com o formato em que o texto a mostra."""

    apelido: str
    tabela: str
    chaves: tuple[str, ...]
    coluna: str
    formato: str = "auto"


_P = "PRINCIPAL"
DESTAQUES: tuple[Destaque, ...] = (
    Destaque("empresasRede", "rede_resumo", (_P, "empresas"), "valor", "int"),
    Destaque("pessoasRede", "rede_resumo", (_P, "pessoas"), "valor", "int"),
    Destaque("vinculosRede", "rede_resumo", (_P, "vinculos"), "valor", "int"),
    Destaque("componentesRede", "rede_resumo", (_P, "componentes"), "valor", "int"),
    Destaque(
        "articulacaoRede", "rede_resumo", (_P, "pessoas_ponto_de_articulacao"), "valor", "int"
    ),
    Destaque("fracGigante", "rede_resumo", (_P, "fracao_no_maior_componente"), "valor", "pct"),
    Destaque(
        "fracGiganteSemArt",
        "rede_resumo",
        ("SEM_ARTICULACAO", "fracao_no_maior_componente"),
        "valor",
        "pct",
    ),
    Destaque(
        "fracGiganteSemPJ", "rede_resumo", ("SEM_PJ", "fracao_no_maior_componente"), "valor", "pct"
    ),
    Destaque(
        "fracGiganteSemAdm",
        "rede_resumo",
        ("SEM_ADMINISTRADOR", "fracao_no_maior_componente"),
        "valor",
        "pct",
    ),
    Destaque("munConexaoA", "rede_resumo", (_P, "municipios_com_conexao_a"), "valor", "int"),
    Destaque("munConexaoB", "rede_resumo", (_P, "municipios_com_conexao_b"), "valor", "int"),
    Destaque("munAnalisaveis", "links_pc1", ("municipios_analisaveis", ""), "valor", "int"),
    Destaque("doadoresA", "links_pc1", ("doadores_pf", "A"), "valor", "int"),
    Destaque("doadoresB", "links_pc1", ("doadores_pf", "B"), "valor", "int"),
    Destaque("taxaCruzamentoA", "links_pc1", ("taxa_cruzamento", "A"), "valor", "pct"),
    Destaque("taxaCruzamentoB", "links_pc1", ("taxa_cruzamento", "B"), "valor", "pct"),
    Destaque("empresasConectadasA", "links_pc1", ("empresas_conectadas", "A"), "valor", "int"),
    Destaque("empresasConectadasB", "links_pc1", ("empresas_conectadas", "B"), "valor", "int"),
    Destaque("munAmbos", "links_pc1", ("municipios_com_conexao", "AMBOS"), "valor", "int"),
    Destaque(
        "paresDeltaZeroA", "rede_distancias", (_P, "A", "0"), "pares_empresa_municipio", "int"
    ),
    Destaque("paresDeltaUmA", "rede_distancias", (_P, "A", "1"), "pares_empresa_municipio", "int"),
    Destaque(
        "paresDeltaDoisA", "rede_distancias", (_P, "A", "2"), "pares_empresa_municipio", "int"
    ),
    Destaque(
        "paresDeltaZeroB", "rede_distancias", (_P, "B", "0"), "pares_empresa_municipio", "int"
    ),
    Destaque("paresDeltaUmB", "rede_distancias", (_P, "B", "1"), "pares_empresa_municipio", "int"),
    Destaque(
        "paresDeltaDoisB", "rede_distancias", (_P, "B", "2"), "pares_empresa_municipio", "int"
    ),
    Destaque(
        "fracVinculosPerdidos",
        "reconstrucao",
        ("fracao_vinculos_setembro_ausentes_na_reconstrucao",),
        "valor",
        "pct",
    ),
    Destaque(
        "fracVinculosExtras",
        "reconstrucao",
        ("fracao_vinculos_reconstruidos_ausentes_em_setembro",),
        "valor",
        "pct",
    ),
    Destaque(
        "fracVinculosLacuna",
        "reconstrucao",
        ("fracao_vinculos_extras_tambem_no_preenchimento",),
        "valor",
        "pct",
    ),
    Destaque(
        "sobreposicaoDireta", "comparabilidade_h2", ("0",), "sobreposicao_mercado_porte", "pct"
    ),
    Destaque("permanenciaComLigacao", "permanencia_h4", ("50", "true"), "permanencia", "pct"),
    Destaque("permanenciaSemLigacao", "permanencia_h4", ("50", "false"), "permanencia", "pct"),
    Destaque("taxaVinculacao", "validacao_panel", ("", "vinculacao_valor_2025"), "valor", "pct"),
)

_APELIDO = re.compile(r"[A-Za-z]+")
for _d in DESTAQUES:
    assert _APELIDO.fullmatch(_d.apelido), _d.apelido


class Numeros:
    """Dicionário macro -> texto formatado, com "n.d." para o que não existe."""

    def __init__(self, tabelas: Mapping[tuple[str, tuple[str, ...], str], float | None]):
        self._tabelas = dict(tabelas)

    @classmethod
    def ler(cls, diretorio: Path) -> "Numeros":
        """Lê todos os CSV de `diretorio`; diretório ausente equivale a nenhuma tabela."""
        celulas: dict[tuple[str, tuple[str, ...], str], float | None] = {}
        if diretorio.is_dir():
            for caminho in sorted(diretorio.glob("*.csv")):
                for c in celulas_da_tabela(caminho):
                    celulas[(c.tabela, c.chaves, c.coluna)] = c.valor
        return cls(celulas)

    def valor(self, tabela: str, chaves: Sequence[str], coluna: str) -> float | None:
        return self._tabelas.get((tabela, tuple(chaves), coluna))

    def linhas(self, tabela: str) -> list[tuple[str, ...]]:
        """Chaves de linha da tabela, sem repetição, na ordem em que foram lidas."""
        return list(dict.fromkeys(k for (t, k, _), _v in self._tabelas.items() if t == tabela))

    def formatado(
        self, tabela: str, chaves: Sequence[str], coluna: str, formato: str = "auto"
    ) -> str:
        v = self.valor(tabela, chaves, coluna)
        return ND if v is None else FORMATOS[formato](v)

    def destaque(self, apelido: str) -> str:
        for d in DESTAQUES:
            if d.apelido == apelido:
                return self.formatado(d.tabela, d.chaves, d.coluna, d.formato)
        raise KeyError(apelido)

    def macros(self) -> dict[str, str]:
        """Todas as macros: brutas (por célula) e apelidos. Valor já formatado, não escapado."""
        saida = {
            nome_macro(t, k, c): (ND if v is None else automatico(v))
            for (t, k, c), v in self._tabelas.items()
        }
        for d in DESTAQUES:
            saida[d.apelido] = self.destaque(d.apelido)
        return saida

    def __getitem__(self, apelido: str) -> str:
        return self.destaque(apelido)


def escrever_macros(numeros: Numeros) -> str:
    """Conteúdo de `numeros.tex`: um `\\newcommand` por macro, em ordem estável."""
    linhas = ["% Gerado por redes.numeros a partir de results/tables; não editar à mão."]
    for nome, texto in sorted(numeros.macros().items()):
        corpo = ND if texto == ND else latex_seguro(texto)
        linhas.append(f"\\newcommand{{\\{nome}}}{{{corpo}}}")
    return "\n".join(linhas) + "\n"
