"""Datas de corte, limiares e caminhos do pipeline.

Toda constante de data ou limiar do desenho vive aqui; as etapas importam daqui.
"""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DATA_ELEICAO = date(2024, 10, 6)
# Seção 5 do projeto: doações entram pela data da receita, com corte no dia anterior à eleição.
DATA_LIMITE_DOACAO = date(2024, 10, 5)

# Seção 5: seleção pré-eleitoral usa empenhos de jan/2021 a set/2024.
INICIO_PRE_ELEICAO = date(2021, 1, 1)
FIM_PRE_ELEICAO = date(2024, 9, 30)
ANOS_PRE_ELEICAO = (2021, 2022, 2023, 2024)
# Seção 6: os resultados de H3 são divididos pelo gasto anual médio pré-eleição. A janela tem 45
# meses; a média anual é o total da janela dividido pela duração dela em anos (3,75).
MESES_PRE_ELEICAO = (
    (FIM_PRE_ELEICAO.year - INICIO_PRE_ELEICAO.year) * 12
    + FIM_PRE_ELEICAO.month
    - INICIO_PRE_ELEICAO.month
    + 1
)
ANOS_NA_JANELA_PRE = MESES_PRE_ELEICAO / 12

DATA_POSSE = date(2025, 1, 1)
ANO_RESULTADO = 2025
ANOS_EMPENHO = (2021, 2022, 2023, 2024, 2025)

ANO_ELEICAO = 2024
ANO_ELEICAO_ANTERIOR = 2020
UF = "SP"

FOTOGRAFIA_RFB = "2024-09"
DATA_EXTRACAO_RFB = date(2024, 9, 14)

# δ é calculada até 3 vizinhanças; além disso só importa se há caminho (faixa 3+) ou não (∞).
LIMITE_DISTANCIA = 3

LIMIAR_PRINCIPAIS_REDES = 0.50
LIMIARES_PRINCIPAIS_REDES = (0.25, 0.50, 0.75)
MINIMO_ANOS_PRINCIPAIS_REDES = 3

SUPRESSAO_MINIMA = 5

# Estimação (seção 6). Abaixo de 10 municípios de um lado dentro da banda, o próprio rdrobust
# avisa que o erro-padrão agrupado não é confiável; a estimativa sai como não estimável.
MINIMO_MUNICIPIOS_POR_LADO = 10
# Mesmo piso de suporte para o diagnóstico de agrupamento por rede.
MINIMO_REDES_POR_LADO = 10
JANELA_DESCRITIVA_H4 = 5.0
REPETICOES_BOOTSTRAP = 999
SEMENTE_BOOTSTRAP = 20241006
# Efeito mínimo detectável: poder de 80% num teste bilateral a 5%.
PODER_EMD = 0.80
NIVEL_EMD = 0.05

RAIZ = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Caminhos:
    dados: Path
    resultados: Path
    saida: Path
    chave: Path

    @property
    def brutos(self) -> Path:
        return self.dados / "raw"

    def exigir_resultados(
        self, tabelas: tuple[str, ...], figuras: tuple[str, ...], formato: str
    ) -> None:
        arquivos = [
            *(self.resultados / "tables" / f"{t}.csv" for t in tabelas),
            *(self.resultados / "figures" / f"{f}.{formato}" for f in figuras),
        ]
        faltam = [str(a) for a in arquivos if not a.is_file() or not a.stat().st_size]
        if faltam:
            raise FileNotFoundError("rode make estimate; faltam resultados: " + ", ".join(faltam))

    @classmethod
    def do_ambiente(cls) -> "Caminhos":
        """Lê `REDES_DATA_DIR`, `REDES_RESULTS_DIR`, `REDES_OUTPUT_DIR` e `REDES_CHAVE`.

        Resultados e saída são separáveis para que `make sample` não sobrescreva os versionados.
        """

        def caminho(variavel: str, padrao: Path) -> Path:
            valor = os.environ.get(variavel)
            return Path(valor).resolve() if valor else padrao

        return cls(
            dados=caminho("REDES_DATA_DIR", RAIZ / "data"),
            resultados=caminho("REDES_RESULTS_DIR", RAIZ / "results"),
            saida=caminho("REDES_OUTPUT_DIR", RAIZ / "output"),
            chave=caminho("REDES_CHAVE", RAIZ / ".chave_pseudonimo"),
        )
