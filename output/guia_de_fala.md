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
| 1 | Redes empresariais e persistência econômica sob alternância política | Voz 1 | 10 s | 0:10 |
| 2 | De onde vem o poder político? | Voz 1 | 25 s | 0:35 |
| 3 | Muda o governo. Mudam as redes fornecedoras? | Voz 1 | 30 s | 1:05 |
| 4 | Ligação direta e distância ao vencedor | Voz 1 | 65 s | 2:10 |
| 5 | O efeito da derrota perto do empate | Voz 2 | 130 s | 4:20 |
| 6 | Como montamos a rede e o que ela mostra | Voz 3 | 85 s | 5:45 |
| 7 | Quem doou ao incumbente perde espaço (H1)? | Voz 3 | 45 s | 6:30 |
| 8 | A distância ao vencedor muda a fatia em 2025? | Voz 4 | 75 s | 7:45 |
| 9 | O que os dados permitem concluir | Voz 4 | 55 s | 8:40 |

## Voz 1 · Economia política e hipóteses

### 1. Redes empresariais e persistência econômica sob alternância política (10 s)

**Na fala**

Estudamos as eleições municipais paulistas de 2024 e os empenhos de 2025 para saber se a troca de governo muda quais redes empresariais recebem recursos.

### 2. De onde vem o poder político? (25 s)

**Na fala**

Para Acemoglu, Johnson e Robinson, grupos disputam as regras da economia. O poder formal vem das instituições políticas; o poder de fato, dos recursos que permitem aos grupos se organizar e influenciar decisões. As regras que resultam dessa disputa distribuem recursos e podem reforçar a influência de quem já se beneficia delas.

**Se perguntarem**

- No esquema completo, o poder político também influencia as instituições políticas do período seguinte.

### 3. Muda o governo. Mudam as redes fornecedoras? (30 s)

**Na fala**

A eleição troca quem decide na prefeitura, mas não desfaz os vínculos entre empresas. Uma rede pode estar ligada aos dois grupos. Se uma fornecedora ligada ao derrotado perde espaço, ganhos de outras empresas da mesma rede podem compensar essa perda. Mapeamos essas conexões com doações de campanha nas eleições municipais de 2024 e vínculos societários e olhamos os empenhos de 2025.

**Se perguntarem**

- Empenhos são compromissos de despesa, não pagamentos. Os vínculos observados não medem diretamente poder de fato nem demonstram favorecimento.

### 4. Ligação direta e distância ao vencedor (65 s)

**Na fala**

No diagrama, definimos A e B no primeiro turno de 2024 em municípios sem segundo turno e com prefeito anterior definido. A é o grupo incumbente, por ordem de prioridade: o próprio prefeito concorrendo à reeleição, ou o candidato do seu partido, ou de coligação com esse partido; sem candidato ou com ruptura, o município sai da amostra. B é o adversário mais votado entre os demais. As setas tracejadas são doações: Ana liga X a A e Daniel liga Z a B — essas são as sementes. As linhas contínuas são vínculos societários: Bruno liga X a Y e Carla liga Y a Z. Em H1, testamos se X perde espaço quando A perde ante firmas sem caminho a A ou B. Em H2, exploramos diferenças por distância de B: Z a zero passos, Y a um e X a dois.

**Se perguntarem**

- O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo suplementares). O prefeito concorrendo por outro partido continua no ramo do prefeito. Municípios sem adversário também são excluídos.
- A hierarquia da apresentação foi definida após a análise. O relatório e as tabelas preservam os testes originais.

## Voz 2 · Desenho empírico e fontes

### 5. O efeito da derrota perto do empate (130 s)

**Na fala**

Subtraímos a porcentagem de votos de B da de A. À esquerda do empate, A perde e B assume. À direita, A vence. Comparamos municípios dos dois lados, perto de zero. Para cada grupo de empresas, ajustamos uma reta de cada lado e medimos o salto na fatia dos empenhos de 2025. O salto estima o efeito local da derrota se os resultados potenciais variarem continuamente ao redor do empate. Para H2, definimos os grupos pela distância às candidaturas usando os vínculos e as doações anteriores à eleição. Também aplicamos a comparação a dados anteriores à eleição como teste placebo. A Receita Federal fornece o quadro societário. Cada aresta liga uma empresa a um sócio ou administrador, que pode ser pessoa física ou jurídica. Usamos os votos do TSE para calcular a margem eleitoral e cruzamos o cadastro com as doações individuais, incluindo recursos próprios dos candidatos, para identificar as empresas-semente. Por fim, cruzamos os CNPJs com os empenhos do Tribunal de Contas. Os empenhos anteriores à eleição identificam quem já fornecia e os de 2025 mostram a fatia de cada grupo.

**Se perguntarem**

- A especificação é Y = α + βT + γM + θ(T × M) + u. β é o salto no empate e T indica derrota de A.
- A é o prefeito candidato ou, na ausência dele, representante de seu partido ou coligação. Excluímos a capital, os municípios com segundo turno e aqueles sem A identificável ou sem adversário. O suporte na banda varia por coorte.
- Usamos núcleo triangular, banda escolhida pelo erro quadrático médio estimado e correção de viés. Os contrastes reamostram municípios de cada lado em conjunto, com bandas fixas.
- O teste de densidade da margem deu p = 0,993. Também verificamos placebos e sensibilidade à metade e ao dobro da banda.
- Fornecedora anterior tem saldo líquido positivo na janela pré-eleitoral. O desfecho de H1 e H2 inclui os saldos positivos das entrantes no denominador.

## Voz 3 · Estrutura da rede e ligação direta (H1)

### 6. Como montamos a rede e o que ela mostra (85 s)

**Na fala**

Montamos a rede em três passos. Primeiro, a Receita Federal liga 14.069.286 empresas a 16.547.513 vértices de sócios/administradores PF/PJ em 24.689.604 vínculos. Segundo, as doações de pessoas físicas do TSE marcam as empresas-semente, aquelas com sócio ou administrador que doou para A ou B. Terceiro, os empenhos do TCESP mostram quem já fornecia antes da eleição e qual fatia recebeu em 2025. Por dentro, a rede é muito fragmentada: quase toda empresa tem só um ou dois vínculos (grau médio de 1,75 para empresas e 1,49 para sócios) e quase metade não divide sócio com nenhuma outra. Mesmo assim, entre 8.003.121 grupos separados, um único componente gigante reúne 14,6% das empresas. Ele depende de poucas pessoas que funcionam como ponte: retirando esses pontos de articulação, como o Bruno no diagrama, o maior grupo cai para 2,1%. Nos 506 municípios analisáveis, encontramos sementes de A em 376 e de B em 356.

**Se perguntarem**

- O complemento de 12/10/2024 só usa vínculos iniciados até 13/09/2024 em empresas do cadastro de setembro sem quadro válido naquela fotografia. Vínculos encerrados até outubro podem faltar.
- Ligamos a empresas 41,0% dos doadores de A e 43,4% dos de B.
- A assortatividade é a correlação de Pearson entre os graus da empresa e do sócio ou administrador em cada aresta. A densidade divide o número de arestas pelo produto das duas contagens de vértices.
- Na versão sem pontos de articulação, o universo de empresas é mantido e os caminhos societários mudam.

### 7. Quem doou ao incumbente perde espaço (H1)? (45 s)

**Na fala**

Agora vamos ao teste principal, H1. Perguntamos se empresas ligadas diretamente ao incumbente A perdem fatia dos empenhos de 2025 quando A perde perto do empate, comparadas a firmas sem ligação a A ou B. O contraste mede o salto das ligadas a A menos o salto das firmas sem ligação. No gráfico, tanto as ligadas a A quanto o contraste principal cruzam zero com folga. A estimativa do contraste é de -1,7 p.p., com IC de 95% de -16,2 a 12,8 p.p. — vai de queda forte a ganho forte, então não há evidência de perda quando A sai do cargo.

**Se perguntarem**

- Na banda principal de H1, a estimativa das ligadas a A é -1,6 p.p. (IC de 95% de -12,4 a 9,2 p.p.) e a das sem ligação é 0,1 p.p. (IC de 95% de -0,1 a 0,4 p.p.).
- Meia banda: 2,9 p.p.; dobro da banda: -0,7 p.p.; placebo pré-eleitoral: 2,0 p.p. (p = 0,82); EMD: 20,7 p.p.
- H4 (permanência no topo) ficou fora da apresentação principal por falta de uma comparação informativa. No limiar de 50%, o efeito mínimo detectável é 277,1 p.p. numa escala de 0 a 100%. O relatório preserva o teste.

## Voz 4 · Distância (H2) e conclusão

### 8. A distância ao vencedor muda a fatia em 2025? (75 s)

**Na fala**

Em H2, perguntamos se estar mais perto do vencedor ajuda em 2025. Quando A perde, B assume. Para cada distância — direta, 1, 2 ou 3+ passos — medimos a vantagem média de estar ligado ao vencedor B sobre o derrotado A, fazendo salto de B menos salto de A dividido por dois. Um valor acima de zero indicaria vantagem do vencedor. No gráfico, três das quatro faixas cruzam zero; só 1 passo se afasta, com -4,06 p.p. (IC de 95% de -7,16 a -0,97 p.p.), já no sinal oposto a um ganho do vencedor. Além disso, os contrastes por faixa não testam se o efeito diminui com a distância. Para checar se isso é efeito da eleição, montamos um teste placebo com as mesmas firmas, coortes, margem e bandas de 2024, trocando o desfecho pela mudança de fatia antes do voto — de jan/2021–dez/2022 para jan/2023–set/2024. Na coorte B a 1 passo, o salto já dá -7,68 p.p. (IC nominal de -13,50 a -1,86 p.p.). A diferença anterior à eleição enfraquece a leitura causal de 2025.

**Se perguntarem**

- Ler o contraste como vantagem da ligação ao vencedor exige coortes comparáveis e simetria entre os efeitos de ganhar e perder essa ligação. A mesma firma pode entrar nas duas coortes, e um passo societário não mede necessariamente proximidade política.
- A um passo, o salto de B em 2025 foi -8,07 p.p. (p de Holm = 0,077). O IC do contraste é nominal. A correção de Holm se aplica ao salto de B na família de testes secundários.
- O placebo da coorte B mede a mudança de participação de 2021–2022 para 2023–setembro de 2024. Ele é distinto do placebo de nível pré do contraste.

### 9. O que os dados permitem concluir (55 s)

**Na fala**

Para concluir, voltamos às duas hipóteses apresentadas. Em H1, o intervalo de confiança cruza zero com folga, então não há evidência de que empresas ligadas diretamente ao incumbente percam espaço quando ele sai do cargo. Em H2, três das quatro distâncias cruzam zero, e o único destaque em 2025 — a 1 passo — já tem sinal oposto a uma vantagem do vencedor e aparece antes do voto no teste placebo (Na coorte B a 1 passo, o salto já dá -7,68 p.p. (IC nominal de -13,50 a -1,86 p.p.). A diferença anterior à eleição enfraquece a leitura causal de 2025.). Em síntese, os dados de 2024 e 2025 deixam em aberto a perda para ligados ao incumbente e não provam efeito causal nem favorecimento.

**Se perguntarem**

- A três passos ou mais, o contraste é 0,06 p.p. (IC de 95% de -0,29 a 0,41 p.p.).
- Ao menos 99% das observações nas bandas dessa faixa pertencem ao componente gigante. A mesma rede pode gerar dependência entre municípios.
- No recorte comparável, a estimação ficou indefinida nas faixas 0, 1, 2. No recorte comparável da faixa 3+, o contraste foi de 0,055 p.p. (IC de 95% de 0,001 a 0,109).
