# Auditorias e análises de sensibilidade

As reestimações usam a mesma regressão descontínua, o mesmo ajuste de Holm por
especificação e as mesmas regras de suporte das tabelas principais. As bandas
são selecionadas novamente a partir do painel de cada variante. As tabelas
trazem a estimativa, o intervalo de 95%, o placebo, a banda e o suporte que
pode ser publicado. As contagens de municípios da esquerda e da direita
correspondem, respectivamente, a derrotas e vitórias do incumbente.

| Análise | O que muda | CSV |
|---|---|---|
| Apenas setembro | Restringe os vínculos societários a `origem = 2024-09`, incluindo a parte da pasta de setembro extraída em agosto. Remove os vínculos supridos pela extração de outubro e recalcula componentes e distâncias. Preserva as linhas, os valores e os pesos originais do painel de fornecedores de H1 e H2. Fornecedores sem quadro societário seguem como redes unitárias. | [Estimativas](../results/tables/sensibilidade_apenas_setembro.csv) · [Origem](../results/tables/sensibilidade_origem.csv) |
| Sem o maior componente | Retira do painel de H3 e H4 as observações rede–município que pertencem ao maior componente nacional por número de empresas. Os denominadores municipais e a classificação das redes principais são os do painel original. | [Estimativas](../results/tables/sensibilidade_sem_gigante.csv) · [Concentração](../results/tables/sensibilidade_gigante.csv) |
| Sem pontos de articulação, com sementes fixas | Exclui do grafo as pessoas cuja remoção fragmenta componentes. Mantém todas as conexões diretas da especificação principal como sementes, inclusive as de empresas que se tornam redes unitárias. Recalcula os caminhos, os componentes e a composição das demais coortes. | [Estimativas](../results/tables/sensibilidade_sem_articulacao_sementes_fixas.csv) |
| Sem pessoal ou credor público | Exclui eventos de empenho da natureza de despesa 3.1, de pessoal e encargos, ou com credor classificado como público. Recalcula o valor líquido, os fornecedores anteriores, os denominadores e a classificação das redes principais. | [Estimativas](../results/tables/sensibilidade_sem_pessoal_ou_credor_publico.csv) · [Escopo](../results/tables/sensibilidade_escopo_tcesp.csv) |
| Sem autofinanciamento | Exclui receitas do TSE classificadas como `RECURSOS_PROPRIOS`, preserva as doações elegíveis de pessoas físicas da categoria `PESSOA_FISICA` e recalcula as sementes e as distâncias. Os componentes societários são os mesmos da rede principal. | [Estimativas](../results/tables/sensibilidade_sem_autofinanciamento.csv) |

A tabela de origem usa a janela de cinco pontos percentuais de cada lado do
corte. Cada fornecedor conta uma vez por município e é classificado pela origem
do quadro de sócios. Seu empenho prévio soma os elementos em que era fornecedor
anterior. As coortes de conexão direta são específicas a A e B.

A tabela de concentração usa a banda de estimação da coorte `AMBOS` para as
coortes de H3. Em H4 usa a janela de cinco pontos percentuais e identifica as
redes principais e o subconjunto com ligação exclusiva a A ou B em cada limiar.
A fração do empenho usa o valor líquido pré-eleitoral do componente dividido pelo
valor da respectiva coorte. A fração do peso divide o peso unitário de cada
município pelas redes que ele tem na coorte e calcula a parcela que cabe ao maior
componente, antes de aplicar o núcleo da regressão. A coluna
`municipios_sem_gigante` conta os municípios que conservam ao menos uma rede
da coorte após a exclusão do maior componente.

No TCESP, `credor_publico` é uma classificação aproximada pelo nome
normalizado do credor nos arquivos intermediários da ingestão. A expressão
regular procura termos que indicam entes públicos, como prefeitura, câmara
municipal, INSS, autarquia e consórcio público. Há possibilidade de erro de
classificação nos dois sentidos. A estimação começa no universo de eventos
para credores classificados como pessoa jurídica com CNPJ válido pelo pipeline.
Os eventos de pessoas físicas, sem CNPJ ou com CNPJ inválido têm contagens e
valores próprios na [validação da ingestão](../results/tables/validacao_tcesp.csv).
A auditoria combina emissão, reforço e anulação com seus sinais originais.
A união entre pessoal e credor público desconta a interseção uma vez. Os
percentuais usam como denominador o empenho líquido na janela e amostra de
cada linha.

A estimação requer pelo menos dez municípios com peso de núcleo positivo de
cada lado. Cada linha em branco por falta de suporte ou falha de estimação
traz seu motivo em `motivo`. As tabelas aplicam supressão a contagens positivas
menores que cinco e aos campos que permitiriam recuperá-las por subtração.
Na tabela de concentração, a parcela monetária pode ser publicada mesmo quando
a parcela do peso é suprimida. O valor em reais de cada grupo da coorte fica
fora da tabela, e a parcela monetária independe das contagens do grupo.

## Reprodução

Execute a partir da raiz, após a etapa de estimação, usando os Parquets que
geraram os resultados principais. A pasta de dados precisa conter os painéis,
o cadastro de sócios, as conexões diretas, a rede, as distâncias, as eleições,
as doações, os empenhos e as licitações. Os cinco Parquets intermediários do
TCESP precisam conter `credor_publico`.

```sh
POLARS_MAX_THREADS=2 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  uv run --frozen python -m redes.sensibilidades \
  --dados data --cache data/sensibilidades --parciais-tcesp data/tcesp
```

Use `--tabelas` para apontar a pasta de tabelas públicas que contém
`h1.csv`, `h2.csv`, `h3.csv` e `densidade.csv`. O padrão é
`results/tables`. A opção `--caso` executa uma variante. A opção `--etapa`
permite preparar os painéis, repetir as estimações a partir dos painéis já
gravados ou gerar só os diagnósticos da fotografia e do maior componente.
Os Parquets de trabalho ficam na pasta local informada em `--cache`.
