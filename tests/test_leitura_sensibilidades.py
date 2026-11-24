import polars as pl

from redes.leitura_sensibilidades import leitura, limite_h2


def test_sem_dados_nao_afirma_robustez(tmp_path):
    assert not any(leitura(tmp_path).values())
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


def test_nd_nao_e_evidencia_de_efeito_zero(tmp_path):
    pl.DataFrame(
        {"tipo": ["contraste"], "categoria": ["vencedor_faixa_1"], "estimavel": [False]}
    ).write_csv(tmp_path / "sensibilidade_apenas_setembro.csv")
    verificacoes = leitura(tmp_path)
    assert "sem suporte" in " ".join(verificacoes["sensibilidade H2"])
    assert all("zero" not in frase for frases in verificacoes.values() for frase in frases)


def test_escopo_discute_apenas_os_contrastes_de_h1_e_h2(tmp_path):
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
    texto = " ".join(leitura(tmp_path)["gerais"])
    assert "o IC de H1 continua a incluir zero" in texto
    assert "o contraste a um passo de H2 mantém o IC nominal negativo" in texto
    assert "H3" not in texto
    tabela.with_columns(pl.lit(False).alias("estimavel")).write_csv(arquivo)
    assert not leitura(tmp_path)["gerais"]
