# Guia de fala

**Fala prevista de 9:00**, em 4 blocos iguais de 2:15. Reserve 1:00 para trocas de apresentador e variações de ritmo, dentro do limite de 10:00. Os tempos acumulados servem de referência no ensaio.

## Divisão entre participantes

| Participante | Bloco | Slides | Tempo de fala |
|---|---|---|---|
| [Voz 1 · Andrei](guia_voz_1.md) | Economia política e pergunta de pesquisa | 1–3 | 2:15 |
| [Voz 2 · Felipe](guia_voz_2.md) | Hipóteses e desenho empírico | 4–5 | 2:15 |
| [Voz 3 · João Pedro](guia_voz_3.md) | Estrutura da rede e ligação direta (H1) | 6–7 | 2:15 |
| [Voz 4 · Rafael](guia_voz_4.md) | Distância (H2) e conclusão | 8–9 | 2:15 |

## Cronograma por slide

| Slide | Tema | Voz | Tempo | Até |
|---|---|---|---|---|
| 1 | Redes empresariais, eleições e empenhos municipais | Voz 1 | 15 s | 0:15 |
| 2 | De onde vem o poder político? | Voz 1 | 55 s | 1:10 |
| 3 | A troca de governo muda a fatia das fornecedoras? | Voz 1 | 65 s | 2:15 |
| 4 | Ligação direta e distância ao vencedor | Voz 2 | 60 s | 3:15 |
| 5 | O efeito da derrota perto do empate | Voz 2 | 75 s | 4:30 |
| 6 | Uma rede societária para todos os municípios | Voz 3 | 65 s | 5:35 |
| 7 | As fornecedoras ligadas a A perdem fatia (H1)? | Voz 3 | 70 s | 6:45 |
| 8 | Fatia em 2025 por distância a A e B | Voz 4 | 85 s | 8:10 |
| 9 | O que os dados permitem concluir | Voz 4 | 50 s | 9:00 |

## Voz 1 · Andrei

### 1. Redes empresariais, eleições e empenhos municipais (15 s)

**Na fala**

Vamos apresentar nosso estudo sobre redes empresariais, eleições municipais de 2024 em São Paulo e empenhos de 2025, cobrindo teoria, método, rede e resultados.

### 2. De onde vem o poder político? (55 s)

**Na fala**

Para Acemoglu, Johnson e Robinson (2005) e Acemoglu e Robinson (2008), grupos com interesses distintos disputam as regras econômicas. O poder formal, ou de jure, vem das instituições políticas, como o mandato de quem assume a prefeitura. O poder de fato vem dos recursos econômicos que permitem organizar e influenciar decisões.

O diagrama resume por que esse poder pode persistir: quem detém poder político hoje influencia as regras econômicas, que moldam a distribuição de recursos, e quem acumula recursos hoje pode ampliar sua influência amanhã.

**Se perguntarem**

- No esquema completo de Acemoglu e Robinson (2008), o poder político também molda as instituições políticas futuras; em equilíbrio, elites capturam ou mantêm instituições favoráveis.
- Na literatura empírica no Brasil, Boas et al. (2014) encontram ganhos em contratos federais para doadoras do PT, enquanto Duarte (2025) obtém estimativas imprecisas para doadoras diretas em municípios; Guerra et al. (2025) analisam empresas após o fim das doações empresariais, e Balán et al. (2026) examinam laços familiares como poder corporativo.
- Sobre redes e burocracia: Jackson e Wolinsky (1996) formalizam a formação estratégica de redes e efeitos indiretos; Akhtari et al. (2022) mostram que a troca de governo gera rotatividade burocrática capaz de afetar contratos públicos.

### 3. A troca de governo muda a fatia das fornecedoras? (65 s)

**Na fala**

Aplicamos essa lógica às eleições para prefeito de 2024 em São Paulo. Primeiro (H1), perguntamos se a derrota apertada do grupo incumbente — que chamaremos de A — reduz a fatia de mercado de suas fornecedoras diretas. Segundo (H2), investigamos se essa vantagem prevista varia conforme a distância societária até A e até o principal adversário, B.

Como o STF proibiu doações empresariais na ADI 4650, construímos os vínculos antes do voto cruzando doações de sócios ou administradores pessoas físicas com o quadro societário das empresas.

Depois da eleição, medimos em 2025 a fatia de cada fornecedora anterior no saldo líquido dos empenhos do respectivo elemento de despesa no TCESP, com novas fornecedoras no denominador.

**Se perguntarem**

- A ADI 4650 (2015) proibiu doações de pessoas jurídicas; no TSE, usamos doações de pessoas físicas (inclusive autofinanciamento dos candidatos) e ligamos ao QSA da Receita Federal.
- Doações e vínculos societários medem conexão observada antes do pleito, e não influência política direta; a teoria motiva a hipótese.
- Nos dados do TCESP (excluída a capital), pessoal ou credores públicos somam 50,7% do valor com CNPJ válido na amostra de 2025, órgãos fora das prefeituras respondem por 13,9% do saldo líquido de 2025 e 3,7% do valor está ligado a ajustes; sem pessoal/credor público, as estimativas seguem próximas (H1 -1,3 p.p. e H2 a 1 passo -4,16 p.p.).
- Testes adicionais de compensação dentro da rede e permanência no topo (H3 e H4) foram preservados apenas nas tabelas em results/tables/, fora do relatório e da apresentação.

## Voz 2 · Felipe

### 4. Ligação direta e distância ao vencedor (60 s)

**Na fala**

Definimos A e B em cada município de primeiro turno no interior paulista, sem a capital e sem ruptura — casos com mais de um candidato no ramo do prefeito. A é o candidato do grupo incumbente: primeiro o próprio prefeito, depois alguém do partido ou da coligação. B é o adversário mais votado entre os demais.

No diagrama, doações de sócios tornam X semente de A e Z semente de B. Na H1, comparamos X a firmas sem caminho a A nem a B quando A perde por pouco. Na H2, examinamos se a vantagem ao vencedor cai com a distância societária; Y, por exemplo, está a um passo de cada candidatura.

**Se perguntarem**

- De 645 municípios paulistas (644 fora a capital), excluímos 17 com 2º turno, 39 sem eleito único anterior, além de rupturas (>1 candidato no ramo) e cidades sem A ou B identificáveis, restando 506 municípios analisáveis; a validade externa restringe-se a cidades menores decididas em 1º turno.
- O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo suplementares); se concorre por outro partido, segue no ramo do prefeito. Nos degraus 2 e 3 (partido ou coligação), trocas partidárias entre 2020 e 2024 podem gerar ruído.
- A hierarquia entre hipóteses na apresentação foi definida após a análise; H3 e H4 permanecem preservadas apenas nas tabelas em results/tables/, fora do relatório.

### 5. O efeito da derrota perto do empate (75 s)

**Na fala**

Usamos uma regressão descontínua na margem de votos M: percentual de A menos percentual de B. À esquerda do zero, A perde e T vale um; à direita, A vence e T vale zero.

A unidade é empresa, município e elemento de despesa, com peso igual por município por coorte. Se X recebeu dez reais de cem naquele elemento, sua fatia Y é de dez por cento, com entrantes no total.

Ajustamos retas locais dentro da banda b: alfa é a fatia prevista na vitória, beta é o salto na derrota e gama e teta dão as inclinações, com erro u. Sob continuidade perto do corte, beta estima o efeito causal local. Checamos placebos pré-eleitorais e o teste de densidade da margem, sem evidência de manipulação.

**Se perguntarem**

- Na equação, T = 1 se M < 0 e T = 0 se M ≥ 0; usamos núcleo triangular, banda ótima pelo EQM e correção robusta de viés (CCT), com bandas de 13,1 a 28,8 p.p. em H1 e H2 e checagens em b/2 e 2b.
- Cada município tem peso unitário por coorte (1/n_m para cada observação no município m), evitando que cidades maiores dominem a média.
- Em primeiras diferenças (Y_2025 − Y_pré) na coorte direta a A, o erro-padrão cai 27% (5,51 para 4,01 p.p.), mantendo estimativa nula (-2,57 p.p.).
- O teste de densidade de Cattaneo, Jansson e Ma (2020) deu p = 0,993; contrastes entre coortes usam reamostragem municipal em bloco (999 réplicas) com bandas fixas.
- Fornecedora anterior é quem teve saldo líquido positivo na janela pré-eleitoral (2021–set/2024); o denominador de 2025 inclui todas as empresas com saldo positivo no elemento, inclusive entrantes.

## Voz 3 · João Pedro

### 6. Uma rede societária para todos os municípios (65 s)

**Na fala**

Cruzamos três bases: o cadastro nacional da Receita Federal, as doações ao TSE até 5 de outubro de 2024 e os empenhos do TCESP no interior paulista.

No centro, mostramos como as distâncias são municipais: se uma sócia de X doou a A na cidade 1, Z fica a dois passos; se um sócio de Y doou a A na cidade 2, Z fica a um passo.

A rede é muito esparsa e fragmentada, mas o maior componente conecta 14,6% das empresas — percentual que cai para 2,1% sem sócios-ponte. Por fim, nem todos os 376 municípios com semente de A fornecem ao próprio município; só os com fornecedoras anteriores entram na estimação.

**Se perguntarem**

- A Receita Federal liga 14.069.286 empresas a 16.547.513 vértices de sócios/administradores PF/PJ em 24.689.604 vínculos e 8.003.121 componentes (grau médio 1,75 para empresas e 1,49 para sócios; densidade bipartida de 0,106 por milhão; assortatividade r = 0,0003).
- Dos 376 municípios com semente de A (356 para B), chegamos a 272 pares empresa–município fornecedores ligados diretamente a A, dos quais 56 municípios (25 derrotas e 31 vitórias) entram na banda principal de H1.
- Na ambiguidade de nomes da RFB, há 26 pseudônimos PF em 501+ empresas (máximo de 2.847 firmas); retirar pontes de articulação (2,1%) ou administradores (10,6%) testa essa sensibilidade.
- No painel, 129.975 fornecedoras anteriores sem QSA (45,5% do valor pré-eleitoral) permanecem no grupo "Sem ligação".
- Ligamos a empresas 41,0% dos doadores de A e 43,4% dos de B; no autofinanciamento, 290 candidatos A (287 B) conectam 388 firmas A (486 B) só por recursos próprios.
- A recomposição de outubro supre 19,4% dos vínculos (2.756.163 empresas) porque Socios0.zip da pasta de setembro veio da extração de 10/08/2024.

### 7. As fornecedoras ligadas a A perdem fatia (H1)? (70 s)

**Na fala**

Na H1, comparamos o salto na fatia de 2025 das fornecedoras ligadas diretamente a A com o salto das empresas sem caminho a A nem a B, cada grupo em sua banda.

A estimativa do contraste foi de -1,7 pontos percentuais, com intervalo de 95% de -16,2 a 12,8 pontos percentuais. O intervalo admite perdas e ganhos relevantes de participação. O efeito mínimo detectável é de 20,7 p.p., que equivale a 11,7 vezes a fatia média (1,77%) das fornecedoras ligadas a A na banda. Na banda, a coorte ligada diretamente a A tem 25 municípios com A derrotado e 31 com A vitorioso, o que limita a precisão do contraste.

**Se perguntarem**

- Ligadas a A: -1,6 p.p. (IC de 95% de -12,4 a 9,2 p.p., EP robusto CCT de 5,51 p.p.); Sem ligação: 0,1 p.p. (IC de 95% de -0,1 a 0,4 p.p.). O contraste tem EP de 7,39 p.p. por reamostragem municipal (999 réplicas) — cerca de 34% mais largo que o de Ligadas a A por combinar incerteza amostral entre coortes com suporte assimétrico (25/31 municípios).
- Os dois placebos de H1 incluem zero: nível pré-eleitoral de +2,0 p.p. (p = 0,82) e tendência pré-eleitoral (2023–24 vs. 2021–22) de -2,85 p.p. (p = 0,56).
- Sensibilidades de H1: meia banda +2,9 p.p., dobro da banda -0,7 p.p., sem autofinanciamento -1,2 p.p., apenas setembro -1,8 p.p., sem pontes -1,5 p.p. e sem pessoal/credor público -1,3 p.p.
- H3 e H4 ficaram fora da apresentação principal e do relatório, preservadas apenas em results/tables/: na H3, a coorte AMBOS concentra 99,98% do empenho no gigante; na H4 a 50%, o EMD é 277,1 p.p. numa escala de 0 a 100% e 100%/100% do peso/empenho nas bandas está no gigante.

## Voz 4 · Rafael

### 8. Fatia em 2025 por distância a A e B (85 s)

**Na fala**

Na H2, olhamos a distância societária a A e a B antes da eleição e calculamos, em cada faixa, o salto de B menos o de A dividido por dois, em que valores positivos indicam vantagem ao vencedor.

A um passo, o contraste em 2025 foi de -4,06 p.p., com intervalo de -7,16 a -0,97 — ou seja, sinal oposto ao previsto, puxado pela queda em B (-8,07 p.p.), enquanto A fica perto de zero (+0,06 p.p.).

Além disso, o recorte comparável por estratos fica sem suporte a um passo, e o diagnóstico pré-eleitoral mostra que B já apresentava salto negativo antes da eleição: -11,00 p.p. em nível e -7,68 p.p. na tendência. Quando fazemos pós menos pré, o contraste passa para +1,25 p.p., com intervalo que inclui zero.

**Se perguntarem**

- Decomposição a 1 passo: B tem -8,07 p.p. (p de Holm = 0,077, média na banda 2,18%) e A tem +0,06 p.p. (p de Holm = 1,000, média 0,28%); os grupos diferem em porte.
- Três diagnósticos de 1 passo: nível pré-eleitoral de -5,05 p.p. no contraste (-11,00 p.p. em B); tendência pré-eleitoral de -2,75 p.p. (-7,68 p.p. em B); e pós − pré de +1,25 p.p. (IC de 95% de -4,08 a 6,58 p.p.).
- Recortes sem estimação válida a 1 passo: apenas setembro, sem pontos de articulação, sem administradores, meia banda.
- Nos estratos (município × elemento × quintil prévio), a sobreposição de mercado e porte é de 6,3% na faixa direta e 15,1% a 1 passo; no recorte comparável a 1 passo restam 6/5 municípios, abaixo do mínimo de 10.
- Na banda principal a 1 passo, o suporte é pequeno (6/7 redes em B; 8/6 em A; p de rede = n.d.), com 66,7% do peso de B e 60,5% do peso de A no componente gigante.

### 9. O que os dados permitem concluir (50 s)

**Na fala**

Para concluir, nenhuma das duas hipóteses se confirma de forma robusta. Em H1, a estimativa de -1,7 p.p. é imprecisa e admite efeitos grandes nos dois sentidos. Em H2 a um passo, o contraste de -4,06 p.p. tem sinal oposto ao esperado, já aparecia antes da eleição e vira +1,25 p.p. na variação pós menos pré.

Três limitações explicam essa cautela: um único ano de empenhos com contratos herdados e folha, cruzamento parcial de doadores e empresas sem QSA, e a concentração no componente gigante somada à troca burocrática. Obrigado.

**Se perguntarem**

- Resumo H2 a 1 passo: -4,06 p.p. em 2025, +1,25 p.p. em pós − pré (IC de 95% de -4,08 a 6,58 p.p.) e -2,75 p.p. na tendência pré-eleitoral (IC de 95% de -7,38 a 1,87 p.p.).
- A 3+ passos no painel principal, o contraste é +0,06 p.p. (IC de 95% de -0,29 a 0,41 p.p.), mas ao menos 99% das observações (99,99% do peso de A e 94,82% do de B) pertencem ao componente gigante.
- Na auditoria do recorte comparável a 3+ passos, o contraste de 0,055 p.p. (IC de 95% de 0,001 a 0,109 p.p.) decorre de sobreposição de 97,4% (Jaccard) entre A e B nos 2.674 estratos (85,0% nas bandas), gerando correlação de 0,971 no bootstrap que reduz o EP de 0,159 para 0,028 p.p.
