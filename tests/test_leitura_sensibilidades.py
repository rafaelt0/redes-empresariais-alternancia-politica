import polars as pl

from redes.leitura_sensibilidades import leitura


def test_sem_dados_nao_afirma_robustez(tmp_path):
    assert leitura(tmp_path) == []


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
