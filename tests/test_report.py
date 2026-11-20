import polars as pl

from redes.report import (
    leitura_resultados,
    leitura_robustez,
    numeros_tex,
    sintese_principal,
    tabela_categorias,
    tabela_estimativas,
)


def test_h3_discute_placebo_de_nivel_mesmo_sem_rejeicao():
    resumo = pl.DataFrame(
        {
            "hipotese": ["H3"],
            "categoria": ["ambos_menos_demais"],
            "tipo": ["contraste"],
            "resultado": ["variacao_total"],
            "estimativa": [-0.04],
            "ic_inf": [-0.10],
            "ic_sup": [0.02],
            "placebo_estimativa": [-0.11],
            "placebo_p_valor": [0.13],
        }
    )
    texto = leitura_resultados(resumo)
    assert "placebo de nível de H3 é -11,0 p.p. de participação" in texto
    assert "no mesmo sentido do contraste pós" in texto
    assert "não a variação normalizada do pós" in texto


def test_relatorio_le_o_resumo_real_e_distingue_o_intervalo_do_contraste():
    resumo = pl.DataFrame(
        {
            "hipotese": ["H1", "H1"],
            "categoria": ["conectada_menos_sem_conexao", "conectada_incumbente"],
            "tipo": ["contraste", "categoria"],
            "resultado": ["participacao_2025", "participacao_2025"],
            "estimativa": [-0.1234, -0.8912],
            "ic_inf": [-0.5, -1.0],
            "ic_sup": [0.25, -0.4],
            "municipios_tratados": [22, 18],
            "municipios_controle": [28, 20],
        }
    )
    quadro = tabela_estimativas(resumo)
    assert "-0,1234" in quadro
    assert "-0,8912" not in quadro
    assert "reamostragem" in quadro
    categorias = tabela_categorias(resumo)
    assert "-0,8912" in categorias
    assert "18 & 20" in categorias
    assert "IC robusto" in categorias


def test_relatorio_mostra_o_suporte_e_o_contraste_do_recorte_comparavel(tmp_path):
    pl.DataFrame(
        {
            "tipo": ["contraste", "contraste"],
            "placebo": [False, False],
            "categoria": ["vencedor_faixa_1", "vencedor_faixa_3+"],
            "estimavel": [False, True],
            "estimativa": [None, 0.0023],
            "ic_inf": [None, 0.001],
            "ic_sup": [None, 0.0041],
        }
    ).write_csv(tmp_path / "h2_comparaveis.csv")
    texto = numeros_tex(tmp_path)
    assert "indefinida na faixa 1" in texto
    assert r"faixa 3+, o contraste foi de 0,230 p.p. (IC de 95\% de 0,100 a 0,410)" in texto


def test_relatorio_sintese_e_leitura_usam_formato_ptbr_e_emd():
    resumo = pl.DataFrame(
        {
            "hipotese": ["H1", "H2", "H2", "H3"],
            "categoria": [
                "conectada_menos_sem_conexao",
                "vencedor_faixa_0",
                "vencedor_faixa_3+",
                "ambos_menos_demais",
            ],
            "tipo": ["contraste"] * 4,
            "resultado": [
                "participacao_2025",
                "participacao_2025",
                "participacao_2025",
                "variacao_total",
            ],
            "estimativa": [-0.011, -0.016, 0.001, -0.039],
            "ic_inf": [-0.114, -0.062, -0.002, -0.090],
            "ic_sup": [0.093, 0.029, 0.004, 0.011],
            "emd": [0.148, 0.065, 0.004, 0.072],
            "densidade_p_valor": [0.993] * 4,
            "placebo_p_valor": [0.936, 0.240, 0.465, 0.060],
        }
    )
    sintese = sintese_principal(resumo)
    assert "EMD de 14,8 p.p." in sintese
    leitura = leitura_resultados(resumo)
    assert "$p = 0{,}993$" in leitura
    assert r"-3,9\% do gasto prévio; EMD 7,2\%" in leitura
    assert "magnitudes pequenas (0,1 p.p.; EMD de 0,4 p.p.)" in leitura


def test_leitura_robustez_destaca_estabilidade_e_suporte_nd():
    robustez = pl.DataFrame(
        {
            "hipotese": ["H1", "H3"],
            "categoria": ["conectada_menos_sem_conexao", "ambos_menos_demais"],
            "tipo": ["contraste", "contraste"],
            "resultado": ["participacao_2025", "variacao_total"],
            "estimativa_principal": [-0.011, -0.039],
            "ic_inf_principal": [-0.114, -0.090],
            "ic_sup_principal": [0.093, 0.011],
            "estimativa_sem_articulacao": [-0.017, None],
            "ic_inf_sem_articulacao": [-0.135, None],
            "ic_sup_sem_articulacao": [0.101, None],
            "estimativa_sem_pj": [-0.011, -0.073],
            "ic_inf_sem_pj": [-0.114, -0.110],
            "ic_sup_sem_pj": [0.093, -0.036],
            "estimativa_sem_administrador": [-0.008, None],
            "ic_inf_sem_administrador": [-0.110, None],
            "ic_sup_sem_administrador": [0.094, None],
        }
    )
    texto = leitura_robustez(robustez)
    assert "permanecem indistinguíveis de zero" in texto
    assert r"H3 total (-7,3\%)" in texto
    assert "suporte municipal abaixo de dez municípios" in texto
