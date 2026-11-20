# Guia de fala

Deck de 12 slides, cerca de 10 minutos. Os tempos são sugestões; os pontos são o que precisa ser dito, não um texto para ler.

| Slide | Tema | Pessoa | Tempo |
|---|---|---|---|
| 1 | Redes empresariais e persistência econômica sob alternância política | Felipe | 40 s |
| 2 | O que sobrevive quando o governo muda | Felipe | 40 s |
| 3 | Dados e construção da rede | Andrei | 50 s |
| 4 | A rede é fragmentada, mas tem um núcleo | Andrei | 55 s |
| 5 | Eleições apertadas como choque | Andrei | 55 s |
| 6 | H1 — conexão direta ao incumbente | Rafael | 50 s |
| 7 | H2 — contrastes entre coortes de distância | Rafael | 55 s |
| 8 | H3 — de onde vem a variação da rede | Rafael | 60 s |
| 9 | H4 — permanência das principais redes | João Pedro | 45 s |
| 10 | Robustez: a rede alternativa muda a conclusão? | João Pedro | 50 s |
| 11 | O que os resultados permitem dizer | Felipe | 55 s |
| 12 | Limites e o que ficou de fora | Felipe | 45 s |

## 1. Redes empresariais e persistência econômica sob alternância política — Felipe (40 s)

- Abrir com a pergunta do projeto, não com a literatura.
- Dizer em uma frase o que o grupo encontrou ou não encontrou.
- Apresentar a divisão: desenho, resultados, robustez.

## 2. O que sobrevive quando o governo muda — Felipe (40 s)

- Contraste entre rotatividade de CNPJ e continuidade de sócios.
- Antecipar a conclusão central já aqui, sem esperar o final.
- Deixar claro o que o desenho identifica (vitória eleitoral) e o que é hipótese.

## 3. Dados e construção da rede — Andrei (50 s)

- Explicar a unidade empresa e a distância com o exemplo de três empresas da Figura 1.
- Dizer por que a fotografia é de setembro e não a atual.
- Para empresas sem sócios em setembro, usamos a extração de 12/10/2024, após a eleição, com entrada até 13/09/2024. Vínculos encerrados antes da extração podem ficar de fora.

## 4. A rede é fragmentada, mas tem um núcleo — Andrei (55 s)

- Mostrar que a rede nacional não é um bloco único.
- Explicar o que muda ao remover pontos de articulação.
- Ligar a decisão de PC2 à robustez.

## 5. Eleições apertadas como choque — Andrei (55 s)

- Explicar a hipótese de continuidade no corte sem entrar na fórmula.
- Frisar que a estimativa de RDD é local (disputas apertadas) e que o teste de densidade não sugere manipulação.
- Mencionar poder limitado e EMD antes dos resultados.

## 6. H1 — conexão direta ao incumbente — Rafael (50 s)

- Ler a estimativa em p.p. e o intervalo, não a tabela inteira.
- Interpretar o placebo: se o pré-período também salta, o desenho tem problema.
- Comparar o efeito com o EMD: intervalo largo é imprecisão, não zero preciso.

## 7. H2 — contrastes entre coortes de distância — Rafael (55 s)

- Comparar os efeitos eleitorais nas coortes definidas pela distância.
- Ler δ = 1 junto ao placebo, ao suporte pequeno e à sensibilidade de banda; não interpretar composição como gradiente causal da distância.
- No recorte comparável, a estimação ficou indefinida nas faixas 0, 1, 2. No recorte comparável da faixa 3+, o contraste foi de 0,055 p.p. (IC de 95% de 0,001 a 0,109).
- Distinguir imprecisão das coortes próximas do IC estreito do contraste médio em δ = 3+, sem limitar efeitos individuais.

## 8. H3 — de onde vem a variação da rede — Rafael (60 s)

- Explicar R1, R2 e R3 com um exemplo de rede.
- Mostrar que os termos somam o total, não são hipóteses separadas.
- Apontar que os intervalos não confirmam compensação interna e notar o placebo pré-eleitoral de H3.

## 9. H4 — permanência das principais redes — João Pedro (45 s)

- Explicar o que é uma rede principal e por que o limiar muda a amostra.
- Mostrar os p-valores ajustados (Holm), não os brutos.
- Lembrar que H4 é secundária e tem EMD muito alto no limiar de 50%.

## 10. Robustez: a rede alternativa muda a conclusão? — João Pedro (50 s)

- Não ler a tabela: apontar que H1 e H2 (δ = 0) seguem cruzando zero em todas as variantes.
- Explicar por que aparecem n.d.: remover pontos de articulação ou administradores fragmenta componentes e derruba o suporte municipal.
- Comparar H3 total sem sócios PJ com o intervalo da versão principal; a mudança do grafo também reclassifica as coortes.

## 11. O que os resultados permitem dizer — Felipe (55 s)

- Amarrar os achados das quatro hipóteses com magnitudes e precisão.
- Distinguir resultado impreciso (H1, H2 δ=0, H3, H4) de efeito pequeno (δ=3+).
- Relacionar à literatura (Boas et al., Baltrunaite): doações individuais pós-ADI 4650 em um ciclo municipal não reproduzem ganhos claros.

## 12. Limites e o que ficou de fora — Felipe (45 s)

- Fechar com o que o grupo faria diferente com mais ciclos eleitorais.
- Deixar claro o que é limitação de medida, de validade local e de poder.
- Convidar à pergunta sobre o mecanismo.

## Divisão

- Felipe: 180 s
- Andrei: 160 s
- Rafael: 165 s
- João Pedro: 95 s
