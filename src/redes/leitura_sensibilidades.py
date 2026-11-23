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
        f"Em H2, ao menos {decimal(100 * piso, 0)}% das observações 3+ nas bandas "
        "principais e comparáveis pertencem ao gigante. O IC é condicional à inferência "
        "municipal, que trata os municípios como independentes. A concentração limita a "
        "generalização para outros componentes."
    )


def leitura(pasta: Path) -> dict[str, list[str]]:
    verificacoes = {}
    frases = []
    gigante = _linha(pasta, "sensibilidade_gigante", coorte="H3_ambos")
    if (peso := gigante.get("fracao_peso_gigante")) is not None:
        frases.append(
            f"O gigante concentra {decimal(100 * peso, 1)}% do peso municipal de AMBOS na banda "
            "de H3. A comparação depende desse componente."
        )
    elif (valor := gigante.get("fracao_empenho_gigante")) is not None:
        frases.append(
            f"O gigante concentra {decimal(100 * valor, 2)}% do empenho prévio de AMBOS na banda "
            "de H3. A comparação depende desse componente."
        )
    sem_gigante = _linha(
        pasta,
        "sensibilidade_sem_gigante",
        hipotese="H3",
        categoria="ambos_menos_demais",
        resultado="variacao_total",
    )
    if sem_gigante and not sem_gigante.get("estimavel"):
        frases.append("Em H3, retirar o gigante deixa municípios insuficientes para o contraste.")
    verificacoes["H3"] = frases

    frases = []
    h4 = _linha(pasta, "sensibilidade_gigante", coorte="H4_exclusivas_50")
    if (peso := h4.get("fracao_peso_gigante")) is not None:
        frases.append(
            f"Em H4 (50%), {decimal(100 * peso, 1)}% do peso das redes de ligação exclusiva "
            "na janela de cinco p.p. pertence ao gigante."
        )
    h4_a = _linha(pasta, "sensibilidade_gigante", coorte="H4_rdd_A_50")
    h4_b = _linha(pasta, "sensibilidade_gigante", coorte="H4_rdd_B_50")
    if h4_a.get("fracao_peso_gigante") == h4_b.get("fracao_peso_gigante") == 1:
        frases.append(
            "Em H4 (50%), o gigante também ocupa integralmente as duas coortes nas bandas do RD."
        )
    sem_gigante_h4 = _linha(
        pasta, "sensibilidade_sem_gigante", hipotese="H4", categoria="ligada_ao_vencedor_50"
    )
    if sem_gigante_h4 and not sem_gigante_h4.get("estimavel"):
        frases.append("Em H4 (50%), retirar o gigante deixa o contraste sem suporte.")
    verificacoes["H4"] = frases

    frases = []
    variacao = _linha(
        pasta, "sensibilidade_placebo", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if variacao.get("estimavel"):
        est, inf, sup = (decimal(100 * variacao[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"Em H2 (δ = 1), o RD da diferença de participação pós menos pré é {est} p.p. "
            f"(IC de 95% de {inf} a {sup} p.p.)."
        )
    auto = _linha(
        pasta, "sensibilidade_sem_autofinanciamento", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if auto.get("estimavel"):
        est, inf, sup = (decimal(100 * auto[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"Sem autofinanciamento, H2 (δ = 1) dá {est} p.p. (IC de 95% de {inf} a {sup} p.p.)."
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
        frases.append("Só com setembro, H2 em δ = 1 fica sem suporte para o contraste.")
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
    recortes = [
        _linha(
            pasta,
            "sensibilidade_sem_pessoal_ou_credor_publico",
            tipo="contraste",
            hipotese=h,
            categoria=c,
            resultado=r,
        )
        for h, c, r in (
            ("H1", "conectada_menos_sem_conexao", "participacao_2025"),
            ("H2", "vencedor_faixa_1", "participacao_2025"),
            ("H3", "ambos_menos_demais", "variacao_total"),
        )
    ]
    if all(
        r.get("estimavel") and r.get("ic_inf") is not None and r.get("ic_sup") is not None
        for r in recortes
    ):
        h1, h2, h3 = recortes
        if h1["ic_inf"] <= 0 <= h1["ic_sup"] and h3["ic_inf"] <= 0 <= h3["ic_sup"]:
            frases.append("Sem esses empenhos, H1 e H3 total mantêm ICs cruzando zero.")
        if h2["ic_sup"] < 0:
            frases.append("H2 a um passo permanece negativa com IC nominal fora de zero.")
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
