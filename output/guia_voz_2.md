# Voz 2 · Felipe

**Hipóteses e desenho empírico · 2:15**

## Slide 4 · Ligação direta e distância ao vencedor (0:00–1:00)

**Na fala**

Definimos A e B em cada município de primeiro turno no interior paulista, sem a capital e sem ruptura — casos com mais de um candidato no ramo do prefeito. A é o candidato do grupo incumbente: primeiro o próprio prefeito, depois alguém do partido ou da coligação. B é o adversário mais votado entre os demais.

No diagrama, doações de sócios tornam X semente de A e Z semente de B. Na H1, comparamos X a firmas sem caminho a A nem a B quando A perde por pouco. Na H2, examinamos se a vantagem ao vencedor cai com a distância societária; Y, por exemplo, está a um passo de cada candidatura.

**Se perguntarem**

- De 645 municípios paulistas (644 fora a capital), excluímos 17 com 2º turno, 39 sem eleito único anterior, além de rupturas (>1 candidato no ramo) e cidades sem A ou B identificáveis, restando 506 municípios analisáveis; a validade externa restringe-se a cidades menores decididas em 1º turno.
- O prefeito anterior é o eleito na última eleição antes de 06/10/2024 (incluindo suplementares); se concorre por outro partido, segue no ramo do prefeito. Nos degraus 2 e 3 (partido ou coligação), trocas partidárias entre 2020 e 2024 podem gerar ruído.
- A hierarquia entre hipóteses na apresentação foi definida após a análise; H3 e H4 permanecem preservadas apenas nas tabelas em results/tables/, fora do relatório.

## Slide 5 · O efeito da derrota perto do empate (1:00–2:15)

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
