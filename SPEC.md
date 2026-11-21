# Spec: Redes empresariais e persistência econômica sob alternância política

Implementação reprodutível do projeto de pesquisa de mesmo título (EAE1429 — Redes Econômicas e Sociais, FEA-USP, 2º semestre de 2026). O projeto (`docs/projeto.pdf`) define a pergunta, as hipóteses e o desenho original. Esta especificação descreve a operação vigente, com as diferenças de medida e de estimando registradas em `docs/decisoes.md`. As ampliações operacionais não devem ser atribuídas retroativamente ao projeto original.

## Objetivo

Um repositório público em que um único comando baixa as bases públicas, constrói a rede societária anterior à eleição de 6 de outubro de 2024, estima H1 a H4 e regenera três artefatos:

1. relatório de até cinco páginas, no estilo de escrita do projeto;
2. deck de cerca de 10 minutos, em `.pptx` e `.pdf` idênticos;
3. guia de fala por slide (pontos a cobrir e divisão sugerida entre quatro pessoas, sem texto para leitura).

Usuários: o grupo (quatro autores), o professor e a turma. Critério da disciplina: relevância, uso correto dos conceitos de rede, profundidade da análise, clareza.

Os resultados são reportados como saírem, inclusive nulos ou inconclusivos, com as leituras previstas na seção 7 do projeto.

## Definições operacionais

As definições abaixo descrevem a implementação vigente. Ampliações e diferenças frente ao
projeto original estão explicitadas em [docs/decisoes.md](docs/decisoes.md), em especial
administradores como sementes, preenchimento por outubro e contrastes entre coortes.

| Conceito | Definição operacional |
|---|---|
| Empresa | CNPJ básico (8 primeiros dígitos). Matriz e filiais são uma empresa. |
| Pessoa | Sócio ou administrador PF: par (nome normalizado, 6 dígitos centrais do CPF), pseudonimizado. Sócio PJ: CNPJ básico; estrangeiro: chave pseudonimizada por nome. |
| Vizinhança | Duas empresas compartilham ao menos um sócio ou administrador na fotografia de 2024-09, complementada somente para empresas ausentes por vínculos de 2024-10 com entrada até 13/09/2024. O erro de sobrevivência desses vínculos após a eleição exige continuidade no corte. |
| Conexão direta com k | Algum sócio ou administrador PF da empresa doou ao candidato do grupo k até 5/10/2024. Administradores ampliam a definição societária literal; a variante sem administradores retira essas sementes e seus canais. |
| δ_ik | Menor número de vizinhanças entre a empresa i e uma empresa diretamente conectada a k; 0 na conexão direta, ∞ sem caminho. Calculada por busca em largura no grafo bipartido pessoa–empresa (distância bipartida ÷ 2). |
| Faixas de distância | 0, 1, 2, 3 ou mais, ∞. |
| Rede societária R | Componente conexo da relação de vizinhança. Serve para agregar, não é agente. |
| Grupo incumbente | Protocolo da seção 6 do projeto: o prefeito, se concorre; senão o candidato do partido do prefeito; senão o da coligação que inclui esse partido. Rupturas e casos sem candidato identificável são excluídos e listados. |
| M_m | Diferença de votos válidos, em pontos percentuais, entre o candidato do grupo incumbente e o adversário mais votado, no primeiro turno. |
| T_m | 1 se M_m < 0 (incumbente perde), 0 caso contrário. |
| Fornecedor anterior | Empresa com empenho líquido positivo no município entre jan/2021 e set/2024. |
| Mercado | Elemento de despesa do TCESP. |
| Resultado | Valor empenhado líquido de anulações em 2025, por CNPJ básico, município e elemento de despesa. |
| Empenho novo | Empenho de 2025 vinculado a licitação ou ajuste posterior à posse (1/1/2025); a taxa de vinculação é reportada. |
| Principais redes | Redes com empenho em ao menos três dos quatro anos de 2021 a 2024, ordenadas por valor até somarem 50% do empenhado no município (25% e 75% como sensibilidade). |

## Etapas do pipeline

Cada etapa lê apenas as saídas das anteriores e grava Parquet em `data/`. Os identificadores das etapas são estáveis e são usados no Makefile, nos testes e nas tarefas.

| Etapa | Responsabilidade | Depende de | Saída principal |
|---|---|---|---|
| `fetch` | Baixar todos os arquivos brutos, com URL e SHA-256 registrados em `data/manifest.json`; opcional, pois cada `ingest-*` baixa só o que lê | — | `data/raw/` |
| `ingest-rfb` | Sócios e empresas da fotografia 2024-09; pseudonimização | — (baixa o que lê) | `socios.parquet`, `empresas.parquet` |
| `ingest-tse` | Candidatos de 2020 e 2024, votação de 2024, coligações, receitas de campanha de SP | — (baixa o que lê) | `candidatos.parquet`, `votos.parquet`, `doacoes.parquet` |
| `ingest-tcesp` | Empenhos de 2021 a 2025 (emissão, reforço, anulação) e licitações/ajustes | — (baixa o que lê) | `empenhos.parquet`, `licitacoes.parquet` |
| `elections` | Grupo incumbente, M_m, T_m, exclusões listadas | ingest-tse | `eleicoes.parquet`, `exclusoes.csv` |
| `links` | Cruzamento sócio–doador por nome e 6 dígitos; conexões diretas | ingest-rfb, ingest-tse, elections | `conexoes_diretas.parquet` |
| `network` | Grafo bipartido, componentes, δ_ik por município e grupo (só para empresas com empenho no município), descritivas de rede | ingest-rfb, ingest-tcesp, links | `rede.parquet`, `distancias.parquet` |
| `panel` | Painéis empresa–município–elemento e rede–município; participações; R1, R2, R3; principais redes | ingest-tcesp, elections, network | `painel_firma.parquet`, `painel_rede.parquet` |
| `estimate` | RDD para H1 a H4, diagnósticos, placebos, robustez | panel | `results/tables/`, `results/figures/` |
| `report` | Relatório em PDF | estimate | `output/relatorio.pdf` |
| `deck` | Deck `.pptx`, `.pdf` e guia de fala | estimate | `output/deck.pptx`, `output/deck.pdf`, `output/guia_de_fala.md` |

Ordem: `ingest-*` (paralelas) → `elections` → `links` → `network` → `panel` → `estimate` → `report`, `deck`.

## Estimação

Especificação (5) do projeto, por resultado e categoria de conexão, com `rdrobust`:

- regressão linear local, núcleo triangular, banda de Calonico, Cattaneo e Titiunik (2014), intervalos com correção de viés;
- cada município com o mesmo peso total; erros agrupados por município, com agrupamento por rede como comparação;
- reportar sempre: estimativa com b, b/2 e 2b; municípios de cada lado do corte e em cada categoria; teste de densidade (`rddensity`); placebo com empenhos de 2021 a 2024 como resultado; efeito mínimo detectável.

| Hipótese | Unidade | Resultado | Comparação |
|---|---|---|---|
| H1 | empresa–município–elemento, fornecedores anteriores | participação no empenhado de 2025, dentro do elemento de despesa | salto eleitoral das diretamente ligadas a A menos o das sem caminho a A nem B |
| H2 | empresa–município–elemento, fornecedores anteriores | idem | meia diferença dos saltos eleitorais em coortes de distância fixa a B e A. Resume heterogeneidade entre coortes; não identifica efeito de reduzir distância. Suporte comum de município–elemento–porte como sensibilidade. |
| H3 | rede–município | os três termos da equação (4) e o total, divididos pelo gasto anual médio pré-eleição | redes ligadas aos dois grupos contra as demais; quatro resultados com mesma amostra, banda e pesos; incerteza das diferenças por reamostragem de municípios |
| H4 | rede–município, principais redes | manutenção da posição no ranking de 2025, incluindo entrantes | meia diferença dos saltos nas redes de ligação exclusiva B e A. Médias com/sem ligação ao vencedor na janela de cinco p.p. são descritivas em grupos distintos. |

H1 a H3 são principais. H4 e as demais comparações recebem correção para múltiplas hipóteses (Holm).

Categorias e contrastes usam pontos corrigidos pelo viés. Categorias usam IC robusto CCT;
contrastes usam IC normal com EP de reamostragem municipal conjunta, estratificada por lado,
recalculando o ajuste de viés com bandas fixas. A aproximação não trata a dependência entre
municípios ligados à mesma rede. O diagnóstico pré-eleitoral adicional compara 2021–2022 com
2023–setembro de 2024, sem mudar coortes, pesos ou bandas do pós. Ver [nota de inferência](docs/inferencia.md).

Robustez da rede, reestimando H1 a H3: sem pessoas cuja retirada divide componentes (pontos de articulação), sem sócios pessoas jurídicas, sem administradores não sócios. Descritivas obrigatórias: distribuição do tamanho dos componentes e das distâncias, e erro de reconstrução (fotografia 2024-09 contra a mais recente filtrada pela data de entrada).

## Stack

- Python 3.12, ambiente gerido por `uv` com `uv.lock` versionado.
- DuckDB e Polars para ingestão e painéis (leitura em fluxo dos zips, sem extrair para disco).
- `python-igraph` para componentes, pontos de articulação e busca em largura.
- `rdrobust` e `rddensity` para estimação; `matplotlib` para figuras.
- Relatório em LaTeX (`latexmk`), com a mesma aparência do projeto; números entram por macros geradas pelo pipeline.
- Deck com `python-pptx`; PDF por conversão do `.pptx` com LibreOffice em modo headless.
- `pytest` e `ruff`.

Dependências de sistema, documentadas no README: `uv`, GNU make no Linux/macOS
(opcional com o executor Python), uma distribuição TeX completa com `latexmk`, pdfLaTeX, BibTeX e `abntex2cite`, LibreOffice.
No macOS, MacTeX/TeX Live completo (BasicTeX não basta); no Windows, TeX Live ou
MiKTeX com Perl. Locais conhecidos e overrides `REDES_SOFFICE`/`REDES_LATEXMK`
são documentados na seção Reprodução do README, junto com NTFS para a chave HMAC
e ext4 para os dados no WSL.

## Comandos

```
make setup        # uv sync --frozen
make all          # pipeline inteiro, do download aos artefatos
make <etapa>      # uma etapa e o que ela exige (ex.: make network)
make test         # uv run pytest
make lint         # uv run ruff check . && uv run ruff format --check .
make sample       # pipeline inteiro sobre a amostra sintética de tests/fixtures
make clean-raw    # apaga data/raw após a ingestão
```

No Windows nativo, substitua `make <alvo>` por
`uv run --frozen python -m redes.tarefas <alvo>`; para preparar o ambiente,
`uv sync --frozen` ou o alvo `setup`. Todos os alvos acima e os auxiliares
`dicionario`, `sensibilidades` e `entrega-revisada` são preservados. As dependências
vêm de `ETAPA`; o executor reexecuta os pré-requisitos em cada chamada, enquanto
make usa marcadores incrementais. Não é necessário instalar make ou bash no Windows.

A opção `sample --sem-publicacao` (ou `REDES_SEM_PUBLICACAO=1 make sample` no POSIX)
roda até `estimate` sem TeX/LibreOffice. Essa execução reduzida é explícita e não
satisfaz os critérios de publicação. A CI usa apenas dados sintéticos nos três
sistemas, omitindo publicação explicitamente quando as ferramentas estão ausentes.

`REDES_DATA_DIR` aponta o diretório de dados (padrão `./data`), para permitir disco externo.

## Estrutura

```
src/redes/
  config.py        datas de corte, URLs, caminhos
  fetch.py         download com manifesto e checksum
  ingest/          rfb.py, tse.py, tcesp.py
  elections.py     grupo incumbente, margem, tratamento
  links.py         cruzamento sócio–doador
  network.py       grafo, componentes, distâncias
  panel.py         participações, R1–R3, principais redes
  estimate/        rdd.py, h1_h2.py, h3.py, h4.py, robustness.py
  figures.py       figuras do relatório e do deck
  report.py        macros e tabelas LaTeX
  deck.py          geração do .pptx e do guia de fala
  cli.py           python -m redes <etapa>
tests/             testes por etapa e fixtures sintéticas
report/            relatorio.tex, referencias.bib
docs/              projeto.pdf, decisões, dicionário de dados
results/           tabelas e figuras agregadas (versionadas)
output/            relatório, deck, guia (versionados)
data/              bruto e intermediário (fora do git)
tasks/             plan.md, todo.md
Makefile, pyproject.toml, uv.lock, SPEC.md, README.md
```

## Estilo de código

```python
def distancia_ate_conectadas(grafo: ig.Graph, origens: list[int], limite: int = 3) -> dict[int, int]:
    """Menor número de vizinhanças de cada empresa até o conjunto `origens`.

    O grafo é bipartido (pessoa–empresa); um passo entre empresas são dois passos no grafo.
    Empresas além de `limite` ficam fora do dicionário e são tratadas como distância 3+ ou ∞.
    """
    ...
```

- Nomes de domínio em português, como no projeto (`empenho`, `socio`, `rede`); verbos e termos técnicos de biblioteca em inglês quando forem o nome usual.
- Funções puras sobre tabelas; leitura e escrita só nas bordas de cada etapa.
- Constantes de data e limiares apenas em `config.py`.
- Comentários explicam decisões do desenho, com referência à seção do projeto.

## Testes

- `pytest`, um arquivo por etapa em `tests/`.
- Fixtures sintéticas pequenas, sem dado pessoal real, que reproduzem o exemplo da Figura 1 do projeto (X, Y, Z; Ana, Bruno, Carla, Daniel): δ_XA = 0, δ_YA = 1, δ_ZA = 2, δ_XB = 2, δ_YB = 1, δ_ZB = 0.
- Casos obrigatórios: empenho líquido de anulação; protocolo do grupo incumbente nos três ramos e na exclusão; homônimos com dígitos de CPF diferentes não se ligam; os três termos de (4) somam a variação total; seleção das principais redes nos limiares de 25%, 50% e 75%; recuperação de um salto conhecido em dados simulados de RDD.
- `make sample` roda o pipeline inteiro sobre as fixtures e serve de teste de integração.
- Validações sobre dados reais ficam como asserções nas etapas (contagens, chaves únicas, datas dentro das janelas) e seus resultados vão para `results/tables/validacao.csv`.

## Limites

Sempre:
- fixar toda seleção antes de 6/10/2024, como no projeto;
- pseudonimizar CPFs e nomes na ingestão (HMAC com chave local não versionada);
- versionar apenas resultados agregados; células com menos de 5 unidades são suprimidas em tabelas e figuras;
- registrar URL, data de acesso e SHA-256 de cada arquivo bruto;
- rodar `make test` e `make lint` antes de cada commit.

Perguntar antes:
- qualquer desvio do desenho ou das hipóteses do projeto;
- tornar o repositório público ou alterar sua visibilidade;
- adicionar dependência de sistema;
- apagar dados já baixados.

Nunca:
- versionar dados brutos, CPFs, nomes de sócios ou doadores;
- reconstruir a rede de 2024 pela fotografia atual como substituto da de 2024-09;
- incluir a capital, outros ciclos eleitorais ou dados de 2026;
- divulgar redes ou pessoas identificáveis;
- ajustar especificação, banda ou amostra depois de ver o resultado sem registrar a mudança em `docs/decisoes.md`.

## Critérios de sucesso

1. Em um clone limpo com as dependências de publicação instaladas, `make setup && make all`
   (Linux/macOS), ou `uv sync --frozen` seguido de
   `uv run --frozen python -m redes.tarefas all` (Windows nativo), termina sem erro e gera `output/relatorio.pdf`, `output/deck.pptx`, `output/deck.pdf` e `output/guia_de_fala.md`.
2. `make sample` termina em menos de dois minutos e `make test` passa; no Windows,
   valem os alvos `sample` e `test` do executor Python, com TeX/LibreOffice para a amostra completa.
3. Todo número do relatório e do deck vem de arquivo em `results/`; nenhum é digitado à mão.
4. O relatório tem no máximo cinco páginas e reporta, para H1 a H4: estimativa, intervalo robusto, banda, número de municípios de cada lado, b/2 e 2b, teste de densidade e placebo.
5. As descritivas de rede (componentes, distâncias, erro de reconstrução) e as três reestimações de robustez estão em `results/`.
6. `exclusoes.csv` lista os municípios excluídos e o motivo.
7. `git grep` não encontra CPF, e nenhuma tabela versionada tem célula com menos de 5 unidades.
8. `deck.pdf` é a conversão de `deck.pptx`, com o mesmo número de slides.

## Fatos já verificados (11/11/2026)

- Receita, fotografia 2024-09: pasta oficial em `arquivos.receitafederal.gov.br`, extração em 14/09/2024, última entrada de sócio em 13/09/2024; `Socios0` a `Socios9` somam cerca de 600 MB. Falta registrar a página oficial que aponta para o compartilhamento.
- TSE, `cdn.tse.jus.br/estatistica/sead/odsele/`: votação por município e zona 2024 (48 MB), prestação de contas de candidatos 2024 (1,25 GB), candidatos 2020 e 2024, coligações 2024.
- TCESP: `despesas-2021.zip` a `despesas-2025.zip`, de 1,7 a 2,1 GB cada; licitações e ajustes de 2018 a 2025.
- Máquina de desenvolvimento: 7 GB de RAM.

## Fatos verificados na ingestão (12/11/2026)

- Receita: o `Socios0.zip` da pasta 2024-09 é da extração de 10/08/2024 (arquivo `D40810`); os outros 21 zips são de 14/09/2024. Cerca de 995 mil empresas ficam com o quadro de sócios de agosto. A etapa aceita só essa exceção registrada.
- Receita: 19,9 milhões de vínculos (PF 19,4 milhões; PJ 463 mil; estrangeiro 10,6 mil) e 59,6 milhões de empresas. Estrangeiros são identificados só pelo nome. Na fotografia original, 567 aparecem em mais de uma empresa.
- TSE: o CPF do doador vem completo; o do candidato de 2024 vem mascarado e é recuperado para 82% dos casos.
- TCESP: total líquido de 2025 de Bady Bassitt e Adamantina confere ao centavo com a API do portal. Em 2021 e 2022 há gasto com pessoa jurídica sem CNPJ (credor "identificação especial"), 92% dele com pessoal. A vinculação empenho–ajuste de 2025 é de 11,8% dos empenhos e 3,6% do valor.

## Questões em aberto

1. **Componente gigante.** A rede nacional de sócios pode ter um componente que reúne grande parte das empresas, o que esvaziaria H3 e H4, definidas sobre componentes. O projeto prevê reportar a distribuição e reestimar sem pontos de articulação. A decisão sobre o que fazer se o componente gigante dominar fica para depois das descritivas (ponto de controle após `network`).
2. ~~**CPF do doador.**~~ Resolvida: vem completo (ver fatos verificados na ingestão).
3. **Poder estatístico.** O número de disputas apertadas em São Paulo, sem a capital e sem segundo turno, só é conhecido após `elections`. O projeto já prevê reportar o efeito mínimo detectável.
4. ~~**NUSP de João Pedro Ferreira.**~~ Resolvida em 18/11/2026.

## Decisões tomadas (11/11/2026)

- **Disco.** A máquina de desenvolvimento tem 13 GB livres e os brutos somam cerca de 12 GB. A ingestão é em fluxo, um arquivo por vez, e o bruto pode ser apagado após virar Parquet (`make clean-raw`).
- **Prefeito em exercício.** Usa-se o eleito em 2020, corrigido pelas eleições suplementares do TSE; os demais casos vão para `exclusoes.csv`.
- **Visibilidade.** O repositório é público, com autorização do grupo.
