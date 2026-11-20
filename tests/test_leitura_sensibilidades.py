import polars as pl

from redes.leitura_sensibilidades import leitura, limite_h2


def test_sem_dados_nao_afirma_robustez(tmp_path):
    assert leitura(tmp_path) == []
    assert limite_h2(tmp_path) == ""


def test_limite_h2_usa_pisos_sem_recuperar_taxas_suprimidas(tmp_path):
    dados = pl.DataFrame(
        {
            "recorte": ["principal", "principal", "comparaveis", "comparaveis"],
            "grupo": ["A", "B", "A", "B"],
            "faixa": ["3+"] * 4,
            "janela": ["h"] * 4,
            "piso_fracao_observacoes": [0.99] * 4,
        }
    )
    dados.write_csv(tmp_path / "concentracao_gigante_h2.csv")
    assert "ao menos 99%" in limite_h2(tmp_path)
    assert "condicional à inferência municipal" in limite_h2(tmp_path)
    dados.with_columns(piso_fracao_observacoes=pl.lit(None, pl.Float64)).write_csv(
        tmp_path / "concentracao_gigante_h2.csv"
    )
    assert limite_h2(tmp_path) == ""


def test_concentracao_e_nd_nao_sao_evidencia_de_efeito_zero(tmp_path):
    pl.DataFrame({"coorte": ["H3_ambos"], "fracao_peso_gigante": [0.93548]}).write_csv(
        tmp_path / "sensibilidade_gigante.csv"
    )
    pl.DataFrame(
        {"tipo": ["contraste"], "categoria": ["vencedor_faixa_1"], "estimavel": [False]}
    ).write_csv(tmp_path / "sensibilidade_apenas_setembro.csv")
    texto = " ".join(leitura(tmp_path))
    assert "93,5% do peso municipal" in texto
    assert "sem suporte" in texto
    assert "zero" not in texto


def test_escopo_discute_contrastes_sem_confundir_com_categoria_h3(tmp_path):
    tabela = pl.DataFrame(
        {
            "hipotese": ["H1", "H2", "H3", "H3"],
            "categoria": [
                "conectada_menos_sem_conexao",
                "vencedor_faixa_1",
                "ambos_menos_demais",
                "ambos",
            ],
            "tipo": ["contraste", "contraste", "contraste", "categoria"],
            "resultado": [
                "participacao_2025",
                "participacao_2025",
                "variacao_total",
                "variacao_total",
            ],
            "estimavel": [True] * 4,
            "ic_inf": [-0.15, -0.05, -0.10, -0.09],
            "ic_sup": [0.13, -0.01, 0.02, -0.01],
        }
    )
    arquivo = tmp_path / "sensibilidade_sem_pessoal_ou_credor_publico.csv"
    tabela.write_csv(arquivo)
    texto = " ".join(leitura(tmp_path))
    assert "H1 e H3 total mantêm ICs cruzando zero" in texto
    assert "H2 a um passo permanece negativa com IC nominal fora de zero" in texto
    tabela.with_columns(pl.lit(False).alias("estimavel")).write_csv(arquivo)
    assert "mantêm ICs cruzando zero" not in " ".join(leitura(tmp_path))
