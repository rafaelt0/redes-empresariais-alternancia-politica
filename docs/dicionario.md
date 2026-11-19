# Dicionário de dados

Gerado por `make dicionario` a partir de `src/redes/schemas.py`; não edite à mão.
`tests/test_schemas.py` falha quando este arquivo e o módulo divergem.

Todas as tabelas ficam em `$REDES_DATA_DIR` (padrão `data/`), fora do git.

## Convenções

- empresa: `cnpj_basico`, texto de 8 dígitos;
- pessoa física: pseudônimo de 16 caracteres hexadecimais (`redes.pseudonimo`), o mesmo para
  sócios, doadores e candidatos;
- município: `cod_municipio_tse`, texto de 5 dígitos; a tabela `municipios` traduz o
  identificador do TCESP na ingestão, e daí em diante só o código do TSE circula.

Tipos enumerados aceitam só os valores listados entre chaves.

## `socios.parquet`

Quadro de sócios e administradores da fotografia da Receita de 2024-09; as empresas sem sócio nela recebem os de 2024-10 que entraram antes da extração de 2024-09.

Gravada por `ingest-rfb`; lida por `links`, `network`. Chave primária: `cnpj_basico`, `id_socio`, `cod_qualificacao`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `id_socio` | String | não | Pseudônimo da pessoa física ou estrangeira; CNPJ básico do sócio pessoa jurídica |
| `tipo_socio` | Enum{PF, PJ, ESTRANGEIRO} | não | PF, PJ ou ESTRANGEIRO |
| `vinculo` | Enum{SOCIO, ADMINISTRADOR_NAO_SOCIO} | não | SOCIO ou ADMINISTRADOR_NAO_SOCIO, derivado da qualificação |
| `cod_qualificacao` | String | não | Código de qualificação do sócio na Receita |
| `data_entrada` | Date | sim | Data de entrada na sociedade |
| `origem` | Enum{2024-09, 2024-10} | não | Pasta da Receita de onde veio o vínculo: 2024-09 ou, no preenchimento, 2024-10 |

Checagens na gravação:

- `cnpj_basico` tem 8 dígitos
- `id_socio` é CNPJ básico para PJ e pseudônimo para os demais
- `data_entrada` até a extração (2024-09-14)
- vínculo de 2024-10 tem `data_entrada` antes de 2024-09-14

## `empresas.parquet`

Cadastro das empresas da fotografia 2024-09; sem razão social, que no MEI contém nome e CPF.

Gravada por `ingest-rfb`; lida por nenhuma etapa. Chave primária: `cnpj_basico`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `cod_natureza_juridica` | String | não | Código da natureza jurídica |
| `porte` | String | sim | Código de porte da Receita |
| `capital_social` | Float64 | sim | Capital social declarado, em reais |

Checagens na gravação:

- `cnpj_basico` tem 8 dígitos

## `candidatos.parquet`

Candidatos a prefeito em SP: eleições ordinárias de 2020 e 2024 e suplementares entre elas.

Gravada por `ingest-tse`; lida por `elections`. Chave primária: `ano`, `sq_candidato`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `ano` | Int16 | não | Ano da eleição |
| `data_eleicao` | Date | não | Data do primeiro turno |
| `tipo_eleicao` | Enum{ORDINARIA, SUPLEMENTAR} | não | ORDINARIA ou SUPLEMENTAR |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `sq_candidato` | String | não | Sequencial do candidato no TSE |
| `id_pessoa` | String | não | Pseudônimo do candidato; liga o prefeito eleito em 2020 ao candidato de 2024 |
| `sigla_partido` | String | não | Partido do candidato; antes de 2024, a sigla sucessora quando o partido se fundiu, foi incorporado ou mudou de nome até 2024 |
| `sq_coligacao` | String | sim | Sequencial da coligação ou federação |
| `partidos_coligacao` | List(String) | não | Siglas dos partidos da coligação, incluindo o do candidato |
| `situacao_candidatura` | String | não | Situação da candidatura no TSE |
| `eleito` | Boolean | sim | Eleito no pleito (primeiro ou segundo turno) |

Checagens na gravação:

- `cod_municipio_tse` tem 5 dígitos
- `id_pessoa` é pseudônimo hexadecimal de 16 caracteres

## `votos.parquet`

Votos nominais para prefeito por candidato e município, somados sobre as zonas.

Gravada por `ingest-tse`; lida por `elections`. Chave primária: `ano`, `turno`, `cod_municipio_tse`, `sq_candidato`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `ano` | Int16 | não | Ano da eleição |
| `turno` | Int8 | não | 1 ou 2 |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `sq_candidato` | String | não | Sequencial do candidato no TSE |
| `votos` | Int64 | não | Votos nominais válidos |

Checagens na gravação:

- `cod_municipio_tse` tem 5 dígitos
- `turno` é 1 ou 2
- `votos` não negativo

## `doacoes.parquet`

Receitas de campanha dos candidatos a prefeito de SP em 2024.

Gravada por `ingest-tse`; lida por `links`. Chave primária: `ano`, `sq_candidato`, `id_receita`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `ano` | Int16 | não | Ano da eleição |
| `sq_candidato` | String | não | Candidato que recebeu |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `id_receita` | String | não | Identificador da receita no TSE |
| `id_doador` | String | sim | Pseudônimo do doador PF; CNPJ básico do doador PJ; nulo nos demais |
| `tipo_doador` | Enum{PF, PJ, OUTRO} | não | PF (doador com CPF), PJ (partido, campanha ou plataforma, com CNPJ) ou OUTRO |
| `origem` | Enum{PESSOA_FISICA, RECURSOS_PROPRIOS, REPASSE, OUTRA} | não | PESSOA_FISICA (inclui internet e financiamento coletivo), RECURSOS_PROPRIOS, REPASSE (de partido ou de outro candidato) ou OUTRA |
| `data_receita` | Date | não | Data da receita, não da declaração (seção 5) |
| `valor` | Float64 | não | Valor em reais |

Checagens na gravação:

- `id_doador` preenchido para PF
- `valor` positivo

## `pseudonimos_ambiguos.parquet`

Pseudônimos de doadores e candidatos do TSE que correspondem a mais de um CPF completo.

Gravada por `ingest-tse`; lida por nenhuma etapa. Chave primária: `id_pessoa`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `id_pessoa` | String | não | Pseudônimo (nome normalizado e seis dígitos centrais) |
| `n_cpfs` | Int64 | não | Número de CPFs completos distintos com esse pseudônimo |

Checagens na gravação:

- `id_pessoa` é pseudônimo hexadecimal de 16 caracteres

## `empenhos.parquet`

Eventos de empenho dos municípios paulistas, credores pessoa jurídica.

Gravada por `ingest-tcesp`; lida por `network`, `panel`. Chave primária: `id_evento`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `id_evento` | String | não | Identificador único do evento |
| `id_empenho` | String | não | Empenho ao qual o evento pertence |
| `evento` | Enum{EMISSAO, REFORCO, ANULACAO} | não | EMISSAO, REFORCO ou ANULACAO |
| `data` | Date | não | Data do evento |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `elemento_despesa` | String | não | Elemento de despesa, 2 dígitos (5º e 6º da natureza): o mercado, na especificação |
| `natureza_despesa` | String | sim | Natureza da despesa até o subelemento, 8 dígitos, como no TCESP; nula na amostra |
| `tipo_orgao` | Enum{PREFEITURA, CAMARA, PREVIDENCIA, AUTARQUIA_OU_OUTRA} | sim | Órgão que empenhou, pelo nome: prefeitura, câmara, previdência própria ou outro |
| `valor` | Float64 | não | Valor com sinal: positivo em emissão e reforço, negativo em anulação |
| `id_ajuste` | String | sim | Licitação ou ajuste vinculado, quando houver |

Checagens na gravação:

- `cnpj_basico` tem 8 dígitos
- `cod_municipio_tse` tem 5 dígitos
- sinal de `valor` segue o evento
- `data` entre 2021-01-01 e 2025-12-31

## `licitacoes.parquet`

Licitações e ajustes do TCESP, usados para marcar empenhos de 2025 como novos.

Gravada por `ingest-tcesp`; lida por `panel`. Chave primária: `id_ajuste`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `id_ajuste` | String | não | Identificador da licitação ou ajuste |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `cnpj_basico` | String | sim | Contratado, quando informado |
| `tipo` | String | não | Licitação, contrato, aditivo etc., como no TCESP |
| `data` | Date | não | Data da licitação ou da assinatura do ajuste |
| `valor` | Float64 | sim | Valor em reais |

Checagens na gravação:

- `cod_municipio_tse` tem 5 dígitos

## `municipios.parquet`

Correspondência entre o código do TSE e o identificador do TCESP; sem a capital.

Gravada por `ingest-tcesp`; lida por nenhuma etapa. Chave primária: `cod_municipio_tse`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `id_municipio_tcesp` | String | não | Identificador do município no TCESP |
| `cod_ibge` | String | sim | Código IBGE (7 dígitos) |
| `nome` | String | não | Nome do município |

Checagens na gravação:

- `cod_municipio_tse` tem 5 dígitos
- `id_municipio_tcesp` único

## `eleicoes.parquet`

Municípios na amostra principal: grupo incumbente, margem M_m e tratamento T_m.

Gravada por `elections`; lida por `links`, `panel`, `estimate`. Chave primária: `cod_municipio_tse`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `ramo` | Enum{PREFEITO, PARTIDO, COLIGACAO} | não | Ramo do protocolo da seção 6: PREFEITO, PARTIDO ou COLIGACAO |
| `sq_candidato_a` | String | não | Candidato do grupo incumbente (A) |
| `sq_candidato_b` | String | não | Adversário mais votado (B) |
| `votos_validos` | Int64 | não | Votos válidos no primeiro turno |
| `margem` | Float64 | não | M_m: votos de A menos votos de B, em pontos percentuais |
| `tratamento` | Int8 | não | T_m: 1 se A perde (M_m < 0) |

Checagens na gravação:

- `tratamento` = 1 exatamente quando `margem` < 0

## `exclusoes.csv`

Municípios fora da amostra principal e o motivo.

Gravada por `elections`; lida por nenhuma etapa. Chave primária: `cod_municipio_tse`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `motivo` | Enum{SEGUNDO_TURNO, RUPTURA, SEM_CANDIDATO, SEM_ADVERSARIO, PREFEITO_INDEFINIDO} | não | Primeiro motivo de exclusão que se aplica |
| `detalhe` | String | sim | Explicação do caso |

## `conexoes_diretas.parquet`

Empresas com sócio PF que doou ao candidato do grupo até a véspera da eleição.

Gravada por `links`; lida por `network`. Chave primária: `cod_municipio_tse`, `grupo`, `cnpj_basico`, `id_pessoa`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `grupo` | Enum{A, B} | não | A (incumbente) ou B (adversário) |
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `id_pessoa` | String | não | Sócio doador; permite refazer as robustezas |
| `vinculo` | Enum{SOCIO, ADMINISTRADOR_NAO_SOCIO} | não | SOCIO se a pessoa tem ao menos uma qualificação de sócio na empresa; ADMINISTRADOR_NAO_SOCIO se só administra (a variante SEM_ADMINISTRADOR descarta) |
| `valor_doado` | Float64 | não | Soma das doações do sócio ao candidato do grupo |

Checagens na gravação:

- `id_pessoa` é pseudônimo hexadecimal de 16 caracteres
- `cnpj_basico` tem 8 dígitos

## `rede.parquet`

Rede societária (componente conexo da vizinhança) de cada empresa, por variante.

Gravada por `network`; lida por `panel`. Chave primária: `variante`, `cnpj_basico`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `variante` | Enum{PRINCIPAL, SEM_ARTICULACAO, SEM_PJ, SEM_ADMINISTRADOR} | não | Versão da rede: principal ou uma das robustezas da seção 5 do projeto |
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `id_rede` | Int64 | não | Identificador do componente |
| `empresas_na_rede` | Int64 | não | Número de empresas no componente |

## `distancias.parquet`

δ_ik por município, grupo e variante, para as empresas com empenho no município.

Gravada por `network`; lida por `panel`. Chave primária: `variante`, `cod_municipio_tse`, `grupo`, `cnpj_basico`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `variante` | Enum{PRINCIPAL, SEM_ARTICULACAO, SEM_PJ, SEM_ADMINISTRADOR} | não | Versão da rede: principal ou uma das robustezas da seção 5 do projeto |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `grupo` | Enum{A, B} | não | A ou B |
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `distancia` | Int8 | sim | δ exato até 3; nulo além disso ou sem caminho |
| `faixa` | Enum{0, 1, 2, 3+, inf} | não | 0, 1, 2, 3+ ou inf |

## `painel_firma.parquet`

Painel empresa–município–elemento das fornecedoras anteriores do elemento (H1 e H2).

Gravada por `panel`; lida por `estimate`. Chave primária: `variante`, `cod_municipio_tse`, `elemento_despesa`, `cnpj_basico`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `variante` | Enum{PRINCIPAL, SEM_ARTICULACAO, SEM_PJ, SEM_ADMINISTRADOR} | não | Versão da rede: principal ou uma das robustezas da seção 5 do projeto |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `elemento_despesa` | String | não | Mercado |
| `cnpj_basico` | String | não | CNPJ básico (8 primeiros dígitos) da empresa |
| `id_rede` | Int64 | não | Rede da empresa em `rede`, na variante; a empresa sem sócio na fotografia é uma rede de uma empresa só, com `id_rede` = −(CNPJ básico) − 1 |
| `faixa_a` | Enum{0, 1, 2, 3+, inf} | não | Faixa de δ até o grupo incumbente; inf se a empresa falta em `distancias` |
| `faixa_b` | Enum{0, 1, 2, 3+, inf} | não | Faixa de δ até o grupo adversário; idem |
| `empenhado_pre` | Float64 | não | Empenho líquido (emissão + reforço − anulação) no elemento, jan/2021 a set/2024; positivo, pois a linha é de fornecedora anterior |
| `empenhado_2025` | Float64 | não | Empenho líquido no elemento em 2025; pode ser ≤ 0 |
| `empenhado_novo_2025` | Float64 | não | Parte de `empenhado_2025` em empenhos vinculados a licitação ou ajuste com data a partir da posse (1/1/2025) |
| `participacao_pre` | Float64 | não | `empenhado_pre` ÷ soma dele entre as fornecedoras anteriores do município e elemento |
| `participacao_2025` | Float64 | sim | max(`empenhado_2025`, 0) ÷ empenho líquido positivo de 2025 de todas as empresas do município e elemento, novas inclusive; nula se ninguém recebeu no elemento em 2025 |
| `margem` | Float64 | não | M_m, repetida de `eleicoes` |
| `tratamento` | Int8 | não | T_m, repetido de `eleicoes` |
| `peso` | Float64 | não | 1 ÷ linhas do município na variante: cada município soma 1 (seção 6 do projeto) |

Checagens na gravação:

- `empenhado_pre` positivo
- participações entre 0 e 1

## `painel_rede.parquet`

Painel rede–município das redes com fornecedora anterior no município: termos da equação (4) e principais redes (H3 e H4).

Gravada por `panel`; lida por `estimate`. Chave primária: `variante`, `cod_municipio_tse`, `id_rede`.

| Coluna | Tipo | Nula | Descrição |
|---|---|---|---|
| `variante` | Enum{PRINCIPAL, SEM_ARTICULACAO, SEM_PJ, SEM_ADMINISTRADOR} | não | Versão da rede: principal ou uma das robustezas da seção 5 do projeto |
| `cod_municipio_tse` | String | não | Código do município no TSE (5 dígitos) |
| `id_rede` | Int64 | não | Rede da empresa em `rede`, na variante; a empresa sem sócio na fotografia é uma rede de uma empresa só, com `id_rede` = −(CNPJ básico) − 1 |
| `ligacao` | Enum{NENHUM, A, B, AMBOS} | não | Grupos do município conectados diretamente a alguma empresa da rede, forneça ela ao município ou não |
| `termo_r1` | Float64 | não | Σ (empenho de 2025 − média anual pré-eleição) ÷ `gasto_medio_pre`, sobre R1, fornecedoras anteriores conectadas diretamente ao incumbente |
| `termo_r2` | Float64 | não | Σ (empenho de 2025 − média anual pré-eleição) ÷ `gasto_medio_pre`, sobre R2, as demais fornecedoras anteriores |
| `termo_r3` | Float64 | não | Σ (empenho de 2025 − média anual pré-eleição) ÷ `gasto_medio_pre`, sobre R3, empresas da rede sem empenho líquido positivo antes da eleição |
| `variacao_total` | Float64 | não | Soma dos três termos |
| `gasto_medio_pre` | Float64 | não | Empenho líquido do município a todos os credores PJ, jan/2021 a set/2024, ÷ 3.75 anos |
| `anos_com_empenho_pre` | Int8 | não | Anos de 2021 a 2024 (2024 até setembro) com empenho líquido positivo da rede |
| `participacao_pre` | Float64 | não | Empenho líquido da rede ÷ o do município, jan/2021 a set/2024 |
| `principal_25` | Boolean | não | Entre as redes com empenho em ao menos 3 dos 4 anos, em ordem de empenho pré-eleição, está entre as primeiras que alcançam 25% do empenhado no município |
| `principal_50` | Boolean | não | Entre as redes com empenho em ao menos 3 dos 4 anos, em ordem de empenho pré-eleição, está entre as primeiras que alcançam 50% do empenhado no município |
| `principal_75` | Boolean | não | Entre as redes com empenho em ao menos 3 dos 4 anos, em ordem de empenho pré-eleição, está entre as primeiras que alcançam 75% do empenhado no município |
| `mantem_posicao_25` | Boolean | sim | Principal também em 2025: entre as redes com empenho positivo em 2025, em ordem de empenho de 2025, está entre as primeiras que alcançam 25% do empenhado em 2025; nulo se não era principal |
| `mantem_posicao_50` | Boolean | sim | Principal também em 2025: entre as redes com empenho positivo em 2025, em ordem de empenho de 2025, está entre as primeiras que alcançam 50% do empenhado em 2025; nulo se não era principal |
| `mantem_posicao_75` | Boolean | sim | Principal também em 2025: entre as redes com empenho positivo em 2025, em ordem de empenho de 2025, está entre as primeiras que alcançam 75% do empenhado em 2025; nulo se não era principal |
| `margem` | Float64 | não | M_m, repetida de `eleicoes` |
| `tratamento` | Int8 | não | T_m, repetido de `eleicoes` |
| `peso` | Float64 | não | 1 ÷ linhas do município na variante: cada município soma 1 (seção 6 do projeto) |

Checagens na gravação:

- os três termos somam `variacao_total`
- `mantem_posicao_25` nulo exatamente quando a rede não é principal
- `mantem_posicao_50` nulo exatamente quando a rede não é principal
- `mantem_posicao_75` nulo exatamente quando a rede não é principal
- principal em 25% é principal em 50%
- principal em 50% é principal em 75%
