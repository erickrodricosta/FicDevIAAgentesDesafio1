# Medição contra o Gabarito (Etapa 6)

## Comparação de Chamadas Paralelas (14 casos)
| Configuração | Acertos | Recusas barreira | Chamadas | Entrada | Saída | Mediana US$ | Máx US$ | Razão Máx/Med | Tempo | Total US$ |
| :--- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: |
| `parallel_tool_calls=False` | 13/14 | 0 | 64 | 225317 | 10133 | 0.00433 | 0.00499 | 1.15× | 128.2 s | 0.05722 |
| `parallel_tool_calls=True` | 13/14 | 0 | 64 | 225681 | 10323 | 0.00435 | 0.00511 | 1.18× | 123.0 s | 0.05752 |

## Três Rodadas Completas (`parallel_tool_calls=False`, `tool_call_limit=8`)
| Rodada | Acertos | Recusas | Chamadas | Entrada | Saída | Mediana US$ | Máx US$ | Tempo | Total US$ |
| :--- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rodada_1 | 13/14 | 0 | 64 | 224994 | 10029 | 0.00432 | 0.00504 | 116.8 s | 0.05704 |
| rodada_2 | 13/14 | 0 | 64 | 224751 | 10009 | 0.00432 | 0.00490 | 119.9 s | 0.05696 |
| rodada_3 | 13/14 | 0 | 64 | 225126 | 10143 | 0.00434 | 0.00500 | 118.2 s | 0.05720 |

- **Acerto acumulado nas 3 rodadas:** 39/42
- **Mediana geral:** US$ 0.00433 | **Cauda (máx):** US$ 0.00504 | **Razão:** 1.16×
- **Projeção 400 pedidos/mês (mediana):** US$ 1.73/mês | **(cauda):** US$ 2.02/mês
- **Casos de 5 passos (confronto Etapa 1):** 1ª chamada média = 3275.9 tokens | entrada média = 17677.3 tokens | saída média = 757.7 tokens | custo médio = US$ 0.00445
