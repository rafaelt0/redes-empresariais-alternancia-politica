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


def leitura(pasta: Path) -> list[str]:
    frases = []
    gigante = _linha(pasta, "sensibilidade_gigante", coorte="H3_ambos")
    if (peso := gigante.get("fracao_peso_gigante")) is not None:
        frases.append(
            f"O gigante concentra {decimal(100 * peso, 1)}% do peso municipal de AMBOS na banda "
            "de H3; a comparação não representa muitas redes independentes."
        )
    elif (valor := gigante.get("fracao_empenho_gigante")) is not None:
        frases.append(
            f"O gigante concentra {decimal(100 * valor, 2)}% do empenho prévio de AMBOS na banda "
            "de H3; a comparação não representa muitas redes independentes."
        )
    h4 = _linha(pasta, "sensibilidade_gigante", coorte="H4_exclusivas_50")
    if (peso := h4.get("fracao_peso_gigante")) is not None:
        frases.append(
            f"Em H4 (50%), {decimal(100 * peso, 1)}% do peso das redes de ligação exclusiva "
            "na janela de cinco p.p. pertence ao gigante."
        )
    sem_gigante = _linha(
        pasta,
        "sensibilidade_sem_gigante",
        hipotese="H3",
        categoria="ambos_menos_demais",
        resultado="variacao_total",
    )
    if sem_gigante and not sem_gigante.get("estimavel"):
        sem_gigante_h4 = _linha(
            pasta, "sensibilidade_sem_gigante", hipotese="H4", categoria="ligada_ao_vencedor_50"
        )
        nomes = "H3 e H4 (50%)" if sem_gigante_h4 and not sem_gigante_h4.get("estimavel") else "H3"
        frases.append(f"Sem o gigante, os contrastes de {nomes} ficam sem suporte.")
    setembro = _linha(
        pasta, "sensibilidade_apenas_setembro", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if setembro and not setembro.get("estimavel"):
        frases.append("Só com setembro, H2 em δ = 1 fica sem suporte para o contraste.")
    variacao = _linha(
        pasta, "sensibilidade_placebo", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if variacao.get("estimavel"):
        est, inf, sup = (decimal(100 * variacao[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"Em H2 (δ = 1), a variação pós menos pré dá {est} p.p. "
            f"(IC [{inf}; {sup}]); são janelas distintas, sem interpretação causal automática."
        )
    auto = _linha(
        pasta, "sensibilidade_sem_autofinanciamento", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if auto.get("estimavel"):
        est, inf, sup = (decimal(100 * auto[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(f"Sem autofinanciamento, H2 (δ = 1) dá {est} p.p. (IC [{inf}; {sup}]).")
    pre = _linha(
        pasta, "sensibilidade_pre_periodos", tipo="contraste", categoria="vencedor_faixa_1"
    )
    if pre.get("estimavel"):
        est, inf, sup = (decimal(100 * pre[c], 2) for c in ("estimativa", "ic_inf", "ic_sup"))
        frases.append(
            f"O placebo de variação pré-eleitoral de H2 (δ = 1) é {est} p.p. "
            f"(IC [{inf}; {sup}]); não comprova continuidade."
        )
    escopo = _linha(pasta, "sensibilidade_escopo_tcesp", periodo="2025", recorte="amostra")
    if (fracao := escopo.get("fracao_excluido")) is not None:
        frases.append(
            f"Pessoal ou credores públicos somam {decimal(100 * fracao, 1)}% do empenho de 2025 "
            "com CNPJ válido na amostra."
        )
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
    return frases
