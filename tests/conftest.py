from pathlib import Path

import polars as pl
import pytest

from redes import amostra
from redes.config import Caminhos


@pytest.fixture(scope="session")
def tabelas_amostra() -> dict[str, pl.DataFrame]:
    return amostra.gerar()


@pytest.fixture
def caminhos_amostra(tmp_path: Path) -> Caminhos:
    """Amostra gravada num diretório temporário, como `make sample` faz em data/amostra."""
    caminhos = Caminhos(
        dados=tmp_path / "dados",
        resultados=tmp_path / "results",
        saida=tmp_path / "output",
        chave=tmp_path / "chave",
    )
    amostra.gravar_amostra(caminhos.dados)
    return caminhos
