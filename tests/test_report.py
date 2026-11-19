import polars as pl

from redes.report import numeros_tex, tabela_categorias, tabela_estimativas


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
