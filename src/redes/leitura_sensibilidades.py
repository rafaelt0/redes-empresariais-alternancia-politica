"""Leitura compartilhada das verificações adicionais, sempre a partir dos CSVs."""

from pathlib import Path

import polars as pl

from redes.numeros import decimal


def _linha(pasta: Path, nome: str, **filtros: object) -> dict:
    arquivo = pasta / f"{nome}.csv"
    if not arquivo.is_file():
        return {}
    tabela = pl.read_csv(arquivo)
    for coluna, valor in filtros.items():
        tabela = tabela.filter(pl.col(coluna) == valor)
    return tabela.row(0, named=True) if tabela.height else {}


def piso_gigante_h2(pasta: Path) -> float | None:
    arquivo = pasta / "concentracao_gigante_h2.csv"
    if not arquivo.is_file():
        return None
    coortes = pl.read_csv(arquivo).filter((pl.col("faixa") == "3+") & (pl.col("janela") == "h"))
    pisos = coortes["piso_fracao_observacoes"]
    return pisos.min() if coortes.height == 4 and not pisos.null_count() else None


def limite_h2(pasta: Path) -> str:
    piso = piso_gigante_h2(pasta)
    if piso is None:
        return ""
    return (
        f"Como ao menos {decimal(100 * piso, 0)}% das observações de H2 na faixa 3+ pertencem "
        "ao gigante, tanto nas bandas principais como nas comparáveis, a generalização a outros "
        "componentes é limitada. O IC é condicional à inferência municipal, que trata os "
        "municípios como independentes."
    )


def leitura(pasta: Path) -> dict[str, list[str]]:
    verificacoes = {}

    frases = []
    variacao = _linha(
        pasta, "sensibilidade_placebo", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if variacao.get("estimavel"):
        est, inf, sup = (decimal(100 * variacao[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"Em H2 (δ = 1), usar a mudança de participação do pré para o pós-eleitoral dá "
            f"um contraste de {est} p.p. "
            f"(IC de 95% de {inf} a {sup} p.p.)."
        )
    auto = _linha(
        pasta, "sensibilidade_sem_autofinanciamento", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if auto.get("estimavel"):
        est, inf, sup = (decimal(100 * auto[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"Ao excluir o autofinanciamento, o contraste a um passo é de {est} p.p. "
            f"(IC de 95% de {inf} a {sup} p.p.)."
        )
    if all(
        linha.get("estimavel") and linha["ic_inf"] <= 0 <= linha["ic_sup"]
        for linha in (variacao, auto)
    ):
        frases.append("Os intervalos das duas especificações incluem zero.")
    setembro = _linha(
        pasta, "sensibilidade_apenas_setembro", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if setembro and not setembro.get("estimavel"):
        frases.append("Com apenas o cadastro de setembro, H2 a um passo fica sem suporte.")
    verificacoes["sensibilidade H2"] = frases

    frases = []
    pre = _linha(
        pasta, "sensibilidade_pre_periodos", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if pre.get("estimavel"):
        est, inf, sup = (decimal(100 * pre[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"O placebo de variação pré-eleitoral de H2 (δ = 1) é {est} p.p. "
            f"(IC de 95% de {inf} a {sup} p.p.)."
        )
    verificacoes["placebo H2"] = frases

    frases = []
    escopo = _linha(pasta, "sensibilidade_escopo_tcesp", periodo="2025", recorte="amostra")
    if (fracao := escopo.get("fracao_excluido")) is not None:
        frases.append(
            f"Pessoal ou credores públicos somam {decimal(100 * fracao, 1)}% do empenho de 2025 "
            "com CNPJ válido na amostra."
        )
    efeitos_escopo = []
    for hipotese, categoria in (
        ("H1", "conectada_menos_sem_conexao"),
        ("H2", "vencedor_faixa_1"),
    ):
        recorte = _linha(
            pasta,
            "sensibilidade_sem_pessoal_ou_credor_publico",
            tipo="contraste",
            hipotese=hipotese,
            categoria=categoria,
            resultado="participacao_2025",
        )
        inferior, superior = recorte.get("ic_inf"), recorte.get("ic_sup")
        if not recorte.get("estimavel") or inferior is None or superior is None:
            continue
        if hipotese == "H1" and inferior <= 0 <= superior:
            efeitos_escopo.append("o IC de H1 continua a incluir zero")
        if hipotese == "H2" and superior < 0:
            efeitos_escopo.append("o contraste a um passo de H2 mantém o IC nominal negativo")
    if efeitos_escopo:
        efeitos = " e ".join(efeitos_escopo)
        frases.append(f"Ao excluir empenhos de pessoal e de credores públicos, {efeitos}.")
    media = _linha(pasta, "descritivas_estimacao", categoria="faixa_a_0")
    if (valor := media.get("media_participacao_2025")) is not None:
        h1 = _linha(
            pasta, "resumo_estimacao", tipo="contraste", categoria="conectada_menos_sem_conexao"
        )
        escala = (
            f" O EMD de H1 é {decimal(h1['emd'] / valor, 1)} vezes essa média."
            if valor > 0 and h1.get("emd") is not None
            else ""
        )
        frases.append(
            f"Na coorte direta a A, a média pós ponderada é {decimal(100 * valor, 2)}% do "
            f"elemento (DP {decimal(100 * media['dp_participacao_2025'], 2)} p.p.).{escala}"
        )
    zeros = _linha(
        pasta,
        "mercados_sem_empenho",
        hipotese="H1",
        categoria="conectada_incumbente",
        lado="direita",
    )
    if zeros.get("sem_empenho") is not None and zeros.get("fracao") is not None:
        frases.append(
            f"No painel completo, {decimal(zeros['sem_empenho'], 0)} observações diretas a A "
            f"nas vitórias ({decimal(100 * zeros['fracao'], 1)}%) têm mercado zerado em 2025."
        )
    verificacoes["gerais"] = frases
    return verificacoes
