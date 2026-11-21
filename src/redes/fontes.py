"""Registro dos arquivos brutos: de onde vêm e se o conteúdo publicado pode mudar.

Receita Federal. A página oficial dos dados abertos do CNPJ é `PAGINA_OFICIAL_RFB`
(gov.br/receitafederal, Dados abertos > Cadastros > CNPJ), que redireciona para o conjunto
`PAGINA_DADOS_GOV_RFB` no dados.gov.br. Lá o recurso "Inscrições no CNPJ" aponta para o
compartilhamento `COMPARTILHAMENTO_RFB`, cujas pastas mensais são lidas por WebDAV em
`BASE_RFB`. Cadeia conferida em 11/11/2026 (o recurso só aparece com JavaScript; foi lido da
resposta de `dados.gov.br/api/publico/conjuntos-dados/...`). O dicionário de dados
(`https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf`) responde 403 a clientes que não
se identificam como navegador e por isso não está no registro.

Eleições suplementares. As do ciclo de 2020 (realizadas de 2021 a 2024) estão dentro dos
arquivos de 2020 do TSE, com `NM_TIPO_ELEICAO = "ELEIÇÃO SUPLEMENTAR"`; a lista oficial delas,
com data e município, é `lista_eleicoes_suplementares_2020.zip`. Não há arquivos de candidatos
ou de votação de 2021 nem de 2023. Em 11/11/2026 a lista trazia mais eleições de SP do que os
arquivos de candidatos e de votação de SP; `elections` precisa cruzar as três.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

PAGINA_OFICIAL_RFB = (
    "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/cadastros/cnpj"
)
PAGINA_DADOS_GOV_RFB = (
    "https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj"
)
COMPARTILHAMENTO_RFB = "https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9"
BASE_RFB = "https://arquivos.receitafederal.gov.br/public.php/dav/files/YggdBLfdninEJX9/"
BASE_TSE = "https://cdn.tse.jus.br/estatistica/sead/"
BASE_TCESP = "https://transparencia.tce.sp.gov.br/sites/default/files/conjunto-dados/"
PAGINA_TCESP = "https://transparencia.tce.sp.gov.br/conjunto-de-dados"


@dataclass(frozen=True)
class Arquivo:
    fonte: str
    url: str
    imutavel: bool
    """Imutável: SHA-256 diferente do registrado é erro. Mutável: o órgão republica; é aviso."""

    @property
    def nome(self) -> str:
        return PurePosixPath(self.url).name

    @property
    def chave(self) -> str:
        """Identifica o arquivo no manifesto e na trava, e é o caminho relativo a `dados/raw`."""
        return f"{self.fonte}/{self.nome}"


def _fonte(nome: str, imutavel: bool, base: str, caminhos: list[str]) -> tuple[Arquivo, ...]:
    return tuple(Arquivo(nome, base + c, imutavel) for c in caminhos)


def _rfb(pasta: str, tabelas: list[str]) -> list[str]:
    return [f"{pasta}/{t}" for t in tabelas]


_SOCIOS = [f"Socios{i}.zip" for i in range(10)]
_EMPRESAS = [f"Empresas{i}.zip" for i in range(10)]

_LICITACOES = (
    ["licitacao-2018_0.zip"]
    + [f"licitacao-{a}-{m:02d}_0.zip" for a in range(2019, 2025) for m in range(1, 13)]
    + [f"licitacao-2025-{m:02d}.zip" for m in range(1, 13)]
)
_AJUSTES = [
    "ajustes-2018_0.zip",
    "ajustes-2019_0.zip",
    "ajustes-2020_0.zip",
    "ajustes-2021_1o_Semestre.zip",
    "ajustes-2021-2o-semestre_0.zip",
    "ajustes-2022-1o-semestre_0.zip",
    "ajustes-2022-2o-semestre_0.zip",
    "ajustes-2023-1o-semestre_0.zip",
    "ajustes-2023-2o-semestre.zip",
    "ajustes-2024-1o-semestre.zip",
    "ajustes-2024-2o-semestre_0.zip",
    "ajustes-2025-1o-semestre.zip",
    "ajustes-2025-2o-semestre.zip",
]

# As pastas 2024-09 e 2024-10 foram regravadas em maio de 2025 (Last-Modified), mas são as
# fotografias do desenho e tratamos mudança nelas como erro. A 2024-10 só preenche as empresas
# sem sócio em 2024-09; a 2026-10 é só para o erro de reconstrução (T10).
FONTES: dict[str, tuple[Arquivo, ...]] = {
    arquivos[0].fonte: arquivos
    for arquivos in (
        _fonte(
            "rfb-2024-09",
            True,
            BASE_RFB,
            _rfb("2024-09", [*_SOCIOS, *_EMPRESAS, "Qualificacoes.zip", "Naturezas.zip"]),
        ),
        _fonte("rfb-2024-10", True, BASE_RFB, _rfb("2024-10", _SOCIOS)),
        _fonte("rfb-2026-10", False, BASE_RFB, _rfb("2026-10", _SOCIOS)),
        _fonte(
            "tse-2024",
            False,
            BASE_TSE + "odsele/",
            [
                "consulta_cand/consulta_cand_2024.zip",
                "consulta_coligacao/consulta_coligacao_2024.zip",
                "votacao_candidato_munzona/votacao_candidato_munzona_2024.zip",
                "prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2024.zip",
            ],
        ),
        _fonte(
            "tse-2020",
            False,
            BASE_TSE,
            [
                "odsele/consulta_cand/consulta_cand_2020.zip",
                "odsele/votacao_candidato_munzona/votacao_candidato_munzona_2020.zip",
                "eleicoes/eleicoes2020/listaelesuplem/lista_eleicoes_suplementares_2020.zip",
            ],
        ),
        _fonte(
            "tcesp-despesas",
            False,
            BASE_TCESP,
            [f"despesas-{a}.zip" for a in range(2021, 2026)],
        ),
        _fonte(
            "tcesp-licitacoes",
            False,
            BASE_TCESP + "licitacoes-contratos/",
            [*_LICITACOES, *_AJUSTES, "layout-ajustes-licitacoes.pdf"],
        ),
        _fonte(
            "tse-municipios",
            False,
            BASE_TSE + "odsele/",
            ["municipio_tse_ibge/municipio_tse_ibge.zip"],
        ),
    )
}

ARQUIVOS: dict[str, Arquivo] = {a.chave: a for arquivos in FONTES.values() for a in arquivos}
