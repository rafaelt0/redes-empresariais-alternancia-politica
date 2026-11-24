# Guia de fala

**Fala prevista de 8:40**, em 4 blocos iguais de 2:10. Reserve 1:20 para trocas de apresentador e variações de ritmo, dentro do limite de 10:00. Os tempos acumulados servem de referência no ensaio.

## Divisão entre participantes

| Participante | Bloco | Slides | Tempo de fala |
|---|---|---|---|
| Voz 1 | Economia política e hipóteses | 1–4 | 2:10 |
| Voz 2 | Desenho empírico e fontes | 5 | 2:10 |
| Voz 3 | Estrutura da rede e ligação direta (H1) | 6–7 | 2:10 |
| Voz 4 | Distância (H2) e conclusão | 8–9 | 2:10 |

## Cronograma por slide

| Slide | Tema | Voz | Tempo | Até |
|---|---|---|---|---|
| 1 | Redes empresariais, eleições e empenhos municipais | Voz 1 | 10 s | 0:10 |
| 2 | De onde vem o poder político? | Voz 1 | 25 s | 0:35 |
| 3 | A troca de governo muda a fatia das fornecedoras? | Voz 1 | 30 s | 1:05 |
| 4 | Ligação direta e distância ao vencedor | Voz 1 | 65 s | 2:10 |
| 5 | O efeito da derrota perto do empate | Voz 2 | 130 s | 4:20 |
| 6 | Uma rede societária para todos os municípios | Voz 3 | 85 s | 5:45 |
| 7 | As fornecedoras ligadas a A perdem fatia (H1)? | Voz 3 | 45 s | 6:30 |
| 8 | Fatia em 2025 por distância a A e B | Voz 4 | 75 s | 7:45 |
| 9 | O que os dados permitem concluir | Voz 4 | 55 s | 8:40 |

## Voz 1 · Economia política e hipóteses

### 1. Redes empresariais, eleições e empenhos municipais (10 s)

**Na fala**

Estudamos se a derrota do grupo incumbente em eleições apertadas em 2024 mudou a fatia dos empenhos de fornecedoras municipais em 2025.

### 2. De onde vem o poder político? (25 s)

**Na fala**

Para Acemoglu, Johnson e Robinson, grupos disputam as regras da economia. O poder formal vem das instituições políticas; o poder de fato, dos recursos que permitem aos grupos se organizar e influenciar decisões. As regras que resultam dessa disputa distribuem recursos e podem reforçar a influência de quem já se beneficia delas.

**Se perguntarem**

- No esquema completo, o poder político também influencia as instituições políticas do período seguinte.

### 3. A troca de governo muda a fatia das fornecedoras? (30 s)

**Na fala**

Quando o grupo incumbente perde por pouco, muda a fatia dos empenhos das fornecedoras que já vendiam para a prefeitura? Primeiro olhamos as ligações diretas com o incumbente. Depois exploramos a distância a cada candidatura na rede. Usamos os vínculos observados antes do voto e os empenhos do primeiro ano após a eleição.

**Se perguntarem**

- Empenhos registram compromissos de despesa. As doações e os vínculos societários são medidas de conexão observada. A teoria motiva a hipótese de influência.
- O relatório explora se, dentro de uma rede, ganhos de umas empresas compensam perdas de outras (H3). As estimativas deixam essa hipótese em aberto.

### 4. Ligação direta e distância ao vencedor (65 s)

**Na fala**

No diagrama, definimos A e B no primeiro turno de 2024 em municípios sem segundo turno e com prefeito anterior definido. A é o grupo incumbente, por ordem de prioridade: o próprio prefeito concorrendo à reeleição, ou o candidato do seu partido, ou de coligação com esse partido; sem candidato ou com ruptura, o município sai da amostra. B é o adversário mais votado entre os demais. As setas tracejadas são doações: Ana liga X a A e Daniel liga Z a B — essas são as sementes. As linhas contínuas são vínculos societários: Bruno liga X a Y e Carla liga Y a Z. Em H1, testamos se X perde espaço quando A perde ante firmas sem caminho a A ou B. Em H2, a previsão é que uma vantagem para as ligadas ao vencedor diminua com a distância. Medimos a distância até A e até B separadamente. Veja Y: está a um passo de ambos e entra nas duas coortes.

**Se perguntarem**

- O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo suplementares). O prefeito concorrendo por outro partido continua no ramo do prefeito. Municípios sem adversário também são excluídos.
- A hierarquia da apresentação foi definida após a análise. O relatório e as tabelas preservam os testes originais.

## Voz 2 · Desenho empírico e fontes

### 5. O efeito da derrota perto do empate (130 s)

**Na fala**

Subtraímos a porcentagem de votos de B da de A. À esquerda do empate, A perde e B assume. À direita, A vence. Comparamos municípios dos dois lados, perto de zero. Para cada grupo de empresas, ajustamos uma reta de cada lado e medimos o salto na fatia dos empenhos de 2025. O salto estima o efeito local da derrota se os resultados potenciais variarem continuamente ao redor do empate. Para H2, definimos os grupos pela distância às candidaturas usando os vínculos e as doações anteriores à eleição. Também aplicamos a comparação a dados anteriores à eleição como teste placebo. A Receita Federal fornece o quadro societário. Cada aresta liga uma empresa a um sócio ou administrador, que pode ser pessoa física ou jurídica. Usamos os votos do TSE para calcular a margem eleitoral e cruzamos o cadastro com as doações individuais, incluindo recursos próprios dos candidatos, para identificar as empresas-semente. Por fim, cruzamos os CNPJs com os empenhos do Tribunal de Contas. Os empenhos anteriores à eleição identificam quem já fornecia. Em 2025, se X teve R$ 10 empenhados em material de consumo e o total dessa categoria foi R$ 100, a fatia de X foi de 10%. O total inclui fornecedoras que entraram depois da eleição.

**Se perguntarem**

- A especificação é Y = α + βT + γM + θ(T × M) + u. β é o salto no empate e T indica derrota de A.
- A é o prefeito candidato ou, na ausência dele, representante de seu partido ou coligação. Excluímos a capital, os municípios com segundo turno e aqueles sem A identificável ou sem adversário. O suporte na banda varia por coorte.
- Usamos núcleo triangular, banda escolhida pelo erro quadrático médio estimado e correção de viés. Os contrastes reamostram municípios de cada lado em conjunto, com bandas fixas.
- O teste de densidade da margem deu p = 0,993. Também verificamos placebos e sensibilidade à metade e ao dobro da banda.
- Fornecedora anterior tem saldo líquido positivo na janela pré-eleitoral. O desfecho de H1 e H2 inclui os saldos positivos das entrantes no denominador.

## Voz 3 · Estrutura da rede e ligação direta (H1)

### 6. Uma rede societária para todos os municípios (85 s)

**Na fala**

A Receita Federal registra os vínculos entre empresas no país inteiro. Por isso podemos usar a mesma rede em todas as cidades. No exemplo, Z fornece para duas prefeituras. A é o candidato do grupo incumbente de cada cidade. Na primeira, uma sócia de X doou a A. Começamos em X e contamos dois passos até Z, passando por Y. Na segunda, um sócio de Y doou a A. Começamos em Y e contamos um passo até Z. Chamamos a empresa de onde partimos de semente.

**Se perguntarem**

- A Receita Federal liga 14.069.286 empresas a 16.547.513 vértices de sócios/administradores PF/PJ em 24.689.604 vínculos. O TSE registra as doações às candidaturas. Os empenhos do TCESP identificam as fornecedoras e mostram sua fatia em 2025.
- A rede é fragmentada. Quase toda empresa tem um ou dois vínculos (grau médio de 1,75 para empresas e 1,49 para sócios) e quase metade não tem vizinha. Entre 8.003.121 grupos separados, um único componente gigante reúne 14,6% das empresas. Sem os sócios ou administradores que funcionam como ponte, o maior grupo cai para 2,1%.
- Nos 506 municípios analisáveis, encontramos sementes de A em 376 e de B em 356.
- O complemento de 12/10/2024 só usa vínculos iniciados até 13/09/2024 em empresas do cadastro de setembro sem quadro válido naquela fotografia. Vínculos encerrados até outubro podem faltar.
- Ligamos a empresas 41,0% dos doadores de A e 43,4% dos de B.
- A assortatividade é a correlação de Pearson entre os graus da empresa e do sócio ou administrador em cada aresta. A densidade divide o número de arestas pelo produto das duas contagens de vértices.
- Na versão sem pontos de articulação, o universo de empresas é mantido e os caminhos societários mudam.

### 7. As fornecedoras ligadas a A perdem fatia (H1)? (45 s)

**Na fala**

Agora vamos ao teste principal, H1. Perguntamos se empresas ligadas diretamente ao incumbente A perdem fatia dos empenhos de 2025 quando A perde perto do empate, comparadas a firmas sem ligação a A ou B. O contraste mede o salto das ligadas a A menos o salto das firmas sem ligação. Estimamos cada salto em sua própria banda de margem eleitoral. A estimativa do contraste é de -1,7 p.p., com IC de 95% de -16,2 a 12,8 p.p.. O intervalo admite perdas e ganhos relevantes de participação.

**Se perguntarem**

- A estimativa das ligadas a A é -1,6 p.p. (IC de 95% de -12,4 a 9,2 p.p.) e a das sem ligação é 0,1 p.p. (IC de 95% de -0,1 a 0,4 p.p.).
- Meia banda: 2,9 p.p.; dobro da banda: -0,7 p.p.; placebo pré-eleitoral: 2,0 p.p. (p = 0,82); EMD: 20,7 p.p.
- H4 (permanência no topo) ficou fora da apresentação principal por falta de uma comparação informativa. No limiar de 50%, o efeito mínimo detectável é 277,1 p.p. numa escala de 0 a 100%. O relatório preserva o teste.

## Voz 4 · Distância (H2) e conclusão

### 8. Fatia em 2025 por distância a A e B (75 s)

**Na fala**

Em H2, as coortes ficam fixas pela distância a A e a B antes do voto. Para cada distância, subtraímos o salto de A do de B e dividimos por dois. Em 2025, o contraste entre as duas coortes a um passo foi de -4,06 p.p. (IC de 95% de -7,16 a -0,97 p.p.). Testar se o efeito diminui exige comparar as faixas entre si. Para investigar se já havia diferenças antes da eleição, repetimos a análise usando a mudança da fatia entre 2021–2022 e 2023 até setembro de 2024. À direita estão os dois saltos da coorte B. O salto em B foi de -7,68 p.p. antes do voto e de -8,07 p.p. em 2025. O salto antes do voto enfraquece a leitura causal para B.

**Se perguntarem**

- Ler o contraste como vantagem da ligação ao vencedor exige coortes comparáveis e simetria entre os efeitos de ganhar e perder essa ligação. A mesma firma pode entrar nas duas coortes, e um passo societário não mede necessariamente proximidade política.
- O placebo para B a um passo tem IC de 95% de -13,50 a -1,86 p.p. (nominal). Em 2025, o salto de B tem p de Holm = 0,077 na família secundária.
- O contraste entre A e B a um passo, no placebo de mudança pré-eleitoral, foi de -2,75 p.p. (IC de 95% de -7,38 a 1,87 p.p., nominal).

### 9. O que os dados permitem concluir (55 s)

**Na fala**

Em H1, a estimativa é imprecisa: o intervalo admite perdas e ganhos de fatia para as empresas diretamente ligadas a A. Em H2, o primeiro número é a diferença entre as duas coortes a um passo em 2025, dividida por dois. O segundo é o salto da coorte B no placebo pré-eleitoral. O salto antes do voto enfraquece a leitura causal para B. A hipótese de que o efeito diminui com a distância segue em aberto.

**Se perguntarem**

- A três passos ou mais, o contraste é 0,06 p.p. (IC de 95% de -0,29 a 0,41 p.p.).
- Ao menos 99% das observações nas bandas dessa faixa pertencem ao componente gigante. A mesma rede pode gerar dependência entre municípios.
- No recorte comparável, a estimação ficou indefinida nas faixas 0, 1, 2. No recorte comparável da faixa 3+, o contraste foi de 0,055 p.p. (IC de 95% de 0,001 a 0,109).
