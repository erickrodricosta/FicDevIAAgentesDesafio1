# Etapa 1 — Desenho do Processo e Quadro PEAS

**Desafio 01:** Instrução de Pedidos de Diárias — Coordenadoria de Diárias e Passagens (SEMA-MT)  
**Norma de referência:** Instrução Normativa SEMA nº 07/2026 (hipotética) — `dados/normas.md`  
**Volume mensal adotado:** **400 pedidos/mês** (~18,2 pedidos/dia útil em 22 dias úteis; proporção estimada de diligências/complementações de ~16,7%, baseada em 2 de 12 pedidos no acervo)

---

## 1. Processo Atual (Execução Manual pelo Servidor)

Hoje, cada pedido de diária protocolado é instruído manualmente por um servidor da Coordenadoria antes de seguir ao ordenador de despesa:

1. **Recebimento e leitura do pedido:** o servidor abre o formulário protocolado (`numero`, `data_pedido`, `matricula`, `nome`, `destino_municipio`, `destino_uf`, `data_partida`, `data_retorno`, `transporte`, `justificativa`).
2. **Conferência de completude e cadastro funcional:** verifica se todos os campos obrigatórios (como `data_retorno`) estão preenchidos e consulta `servidores.csv` pela matrícula para confirmar se o nome coincide e obter cargo, `grupo_diaria`, unidade de lotação e município sede. Se faltar dado ou houver divergência cadastral (Art. 9º), devolve o pedido em diligência sem análise de mérito.
3. **Consulta ao histórico de diárias e prestações de contas:** consulta `historico_diarias.csv`, verifica se há prestação de contas pendente e conta manualmente 5 dias úteis após o retorno da viagem anterior até a data da análise para apurar se há prestação vencida (Art. 7º). Soma também as diárias já concedidas no mês civil da partida (Art. 6º).
4. **Análise de antecedência e urgência:** calcula a diferença em dias corridos entre `data_pedido` e `data_partida` e verifica se atende ao mínimo de 10 dias corridos (Art. 5º). Se inferior, lê a justificativa para verificar se descreve situação emergencial imprevisível (Art. 5º, § 1º), exigindo autorização expressa e escrita do Secretário Adjunto (Art. 5º, § 2º).
5. **Cálculo de quantidade e valor:** conta os pernoites e aplica a regra de 1 diária por pernoite + 0,5 no dia do retorno, ou 0,5 sem pernoite (Art. 4º). Cruza o grupo do servidor (`A`, `B` ou `C`) com a classe do destino (`interior_mt`, `outra_uf`, `distrito_federal`) na tabela do Anexo I (`tabela_diarias.json`) e multiplica pela quantidade de diárias.
6. **Conferência de limite mensal e saldo orçamentário:** soma as diárias do pedido às já concedidas no mês para conferir o teto de 10 diárias/mês (Art. 6º) e consulta o saldo de `unidades.json` para a unidade de lotação do servidor (Art. 8º).
7. **Redação da instrução e minuta de despacho:** consolida as verificações, define a recomendação (`apto_para_autorizacao`, `nao_recomendado` ou `diligencia`), redige a minuta de despacho e encaminha ao ordenador de despesa para decidir (Art. 10).
8. **Tratamento de retorno de diligência:** quando o solicitante envia uma complementação semanas ou horas depois, o servidor precisa localizar o pedido original e reconstituir todo o caso manualmente do zero.

---

## 2. Processo Proposto (Execução com o Agente Agno + Barreiras + Conferência)

Com o sistema construído neste desafio, o fluxo passa a operar em etapas controladas por código:

1. **Entrada e filtragem de dados pessoais (PII):** o pedido protocolado entra pelo formulário Streamlit (ou lote de avaliação) e passa pelo `PIIDetectionGuardrail` configurado para o padrão brasileiro (CPF por máscara válida, conta e agência bancária), mascarando dados sensíveis antes de chegarem ao modelo ou ao banco SQLite do agente, sem mascarar matrícula, datas nem número do pedido.
2. **Consulta cadastral (`consultar_servidor`):** o agente consulta o cadastro pela matrícula informada. A ferramenta devolve apenas os campos necessários à instrução (nome, cargo, grupo, unidade e sede), omitindo CPF e e-mail (princípio da minimização).
3. **Decisão preliminar de diligência (Art. 9º):** se a matrícula não existir, o nome cadastrado divergir do pedido ou faltar `data_retorno`, o agente interrompe as contas e emite `Instrucao` com `recomendacao="diligencia"`, `quantidade_diarias=None` e `valor_total=None`.
4. **Consulta ao histórico (`consultar_historico_diarias`):** estando o cadastro íntegro e os dados completos, a ferramenta apura em código se há prestação de contas vencida (5 dias úteis após retorno vs data da análise) e soma as diárias do mês da partida.
5. **Cálculo normativo em código (`calcular_diarias`):** utilizando `grupo` obtido no passo 2 e `diarias_ja_concedidas_mes` obtidas no passo 4, a ferramenta calcula em código a antecedência em dias corridos, a quantidade de diárias, o valor unitário, o valor total e a soma mensal contra o limite de 10,0 diárias.
6. **Conferência orçamentária (`consultar_saldo_diarias`):** utilizando a sigla da unidade obtida no passo 2 e o `valor_total` obtido no passo 5, a ferramenta compara o pedido com o saldo da unidade.
7. **Emissão estruturada (`output_schema=Instrucao`):** o agente devolve o objeto Pydantic validado com as 6 verificações, alertas (incluindo tentativas de instrução embutida na justificativa e dados mascarados), pendências, recomendação e minuta de despacho.
8. **Barreira de código e verificação de status:** antes de qualquer exibição ao servidor, a aplicação confere `resposta.status != RunStatus.error` e executa a barreira de verificação em Python: garante que todas as matrículas e datas usadas nas ferramentas constam do pedido ou da complementação, que a cadeia de parâmetros/valores coincide com os retornos das ferramentas e que nenhuma instrução com dado inventado chegue ao conferente. Em caso de falha ou recusa, exibe mensagem padrão devolvendo à análise manual.
9. **Conferência humana no formulário e retorno de diligência:** o servidor analisa as verificações, edita a minuta de despacho em campo editável, registra sua decisão (e justificativa se divergir do agente) e encaminha ao ordenador de despesa (Art. 10). Se o pedido estava em diligência, a complementação é enviada na mesma sessão (`session_id = numero_pedido`), recuperando o pedido original pela memória SQLite (`add_history_to_context=True`). O titular pode ainda acionar a eliminação verificável dos dados no banco de trabalho do agente.

---

## 3. Quadro PEAS do Agente (Aula 01)

Classificação conceitual: agente **baseado em objetivos e utilidade restrita à norma**, operando em ambiente **parcialmente observável** (o agente não enxerga diretamente o código das bases; percebe via texto e retornos das ferramentas), **determinístico nas ferramentas e probabilístico no programa do modelo**, **sequencial** (estados de diálogo na diligência) e **discreto**.

| Elemento | Definição no Desafio 01 |
| :--- | :--- |
| **P — Performance (Medida de desempenho)** | **Verificável contra `scripts/gabarito.json` nos 14 casos (12 pedidos + 2 complementações):**<br>1. Taxa de acerto integral (`recomendacao`, `quantidade_diarias`, `valor_total` com tolerância R\$ 0,01, `exige_autorizacao_superior` e conjunto exato de `criterios_nao_atendidos`).<br>2. **0%** de instruções entregues ao conferente com matrícula ou data inventada (barreira em código).<br>3. **0%** de vazamento de CPF/conta bancária (`DIA-2026-0104`) ao modelo ou ao banco SQLite.<br>4. Resistência à injeção de instrução na justificativa (`DIA-2026-0107`) com geração de alerta ao conferente.<br>5. **0** registros remanescentes no banco SQLite após execução da rotina de eliminação (LGPD).<br>6. Custo por pedido e latência dentro do orçamento operacional projetado. |
| **E — Environment (Ambiente)** | Acervo da SEMA-MT (`dados/servidores.csv`, `historico_diarias.csv`, `tabela_diarias.json`, `unidades.json`, `normas.md`), fluxo de `pedidos.json` e `complementacoes.json`, banco SQLite de sessões/memórias do agente, aplicação Streamlit, servidor conferente e ordenador de despesa. |
| **A — Actuators (Atuadores)** | Chamadas às 4 ferramentas Python (`consultar_servidor`, `consultar_historico_diarias`, `calcular_diarias`, `consultar_saldo_diarias`), gravação de estado de sessão no `SqliteDb`, emissão do contrato `Instrucao` e atualização da interface Streamlit (o agente **nunca** defere nem indefere — Art. 10). |
| **S — Sensors (Sensores)** | Texto e campos do pedido protocolado (já filtrados pelo `PIIDetectionGuardrail`), mensagens de complementação na mesma sessão, strings estruturadas devolvidas pelas 4 ferramentas e histórico da sessão recuperado do SQLite. |

---

## 4. Contagem de Passos e Confiabilidade Composta ($p^n$)

Considerando **cada chamada ao modelo de linguagem como 1 passo** (Aula 01, Seção 6):

- **Caso completo em modo sequencial (`parallel_tool_calls=False`):**
  - Passo 1: modelo decide chamar `consultar_servidor(matricula)`
  - Passo 2: modelo decide chamar `consultar_historico_diarias(matricula, mes_partida)`
  - Passo 3: modelo decide chamar `calcular_diarias(...)`
  - Passo 4: modelo decide chamar `consultar_saldo_diarias(unidade, valor)`
  - Passo 5: modelo consolida todos os retornos e produz a saída estruturada `Instrucao`
  - **Total nominal para pedido completo: $n = 5$ passos.**
- **Caso de diligência precoce (`DIA-2026-0111` ou `DIA-2026-0112`):**
  - Passo 1: modelo decide chamar `consultar_servidor(matricula)`
  - Passo 2: modelo constata divergência cadastral ou ausência de `data_retorno` e emite `Instrucao` com `recomendacao="diligencia"`
  - **Total nominal na diligência: $n = 2$ passos.**
- **Teto de segurança configurado (`tool_call_limit=8`):** admite até 8 chamadas de ferramentas (em casos de erro de preenchimento ou reconsulta controlada) antes de interromper.

Aplicando a **Regra $p^n$ (Aula 01, Seção 6)** para confiabilidade por passo $p = 95\%$ e $p = 99\%$:

| Passos ($n$) | Cenário correspondente no fluxo | $p = 95\%$ por passo ($0{,}95^n$) | $p = 99\%$ por passo ($0{,}99^n$) |
| :---: | :--- | :---: | :---: |
| **1** | Chamada única sem ferramentas | 95,0% | 99,0% |
| **2** | Diligência com parada imediata após cadastro | 90,3% | 98,0% |
| **3** | Fluxo parcial intermediário | 85,7% | 97,0% |
| **4** | Fluxo com 3 ferramentas + resposta final | 81,5% | 96,1% |
| **5** | **Pedido completo sequencial (4 ferramentas + `Instrucao`)** | **77,4%** | **95,1%** |
| **8** | Teto máximo de chamadas (`tool_call_limit=8`) | 66,3% | 92,3% |

**Leitura arquitetural:** com $n = 5$ passos e $p = 95\%$, quase 1 em cada 4 instruções falharia em alguma etapa se não houvesse contenção. Como a aritmética normativa foi retirada do modelo e movida para o código Python (Etapa 2) e o retorno é travado por `output_schema` + barreira de verificação em código (Etapa 3), eleva-se a confiabilidade efetiva por passo em direção a $99\%$+ e garante-se que falhas residuais sejam interceptadas antes de chegarem ao conferente.

---

## 5. Estimativa de Custo por Passos e Volume Mensal Adotado

### 5.1 Preço de referência (`gpt-5.6-luna`, Aulas 06 e 07)
- **Entrada:** US\$ 0,20 por 1 milhão de tokens (`US$ 0,0000002 / token`)
- **Saída:** US\$ 1,20 por 1 milhão de tokens (`US$ 0,0000012 / token`)

### 5.2 Estimativa de tokens e custo para 5 passos (pedido completo sequencial)
Conforme referência da página 5 do desafio, a **1ª chamada** reúne instrução de sistema, esquemas das 4 ferramentas, esquema Pydantic `Instrucao` e pedido protocolado, consumindo aproximadamente **$E_1 = 2.060$ tokens de entrada**. Cada passo seguinte acrescenta entre **90 e 150 tokens** (média $\Delta = 120$ tokens/passo entre o pedido da ferramenta e seu retorno), reenviando todo o histórico acumulado a cada ida ao modelo:

| Passo | Entrada estimada (média $\Delta=120$) | Faixa ($\Delta \in [90, 150]$) | Saída estimada |
| :---: | :---: | :---: | :---: |
| 1 | 2.060 | 2.060 | ~35 (1ª `tool_call`) |
| 2 | 2.180 | 2.150 – 2.210 | ~35 (2ª `tool_call`) |
| 3 | 2.300 | 2.240 – 2.360 | ~35 (3ª `tool_call`) |
| 4 | 2.420 | 2.330 – 2.510 | ~35 (4ª `tool_call`) |
| 5 | 2.540 | 2.420 – 2.660 | ~470 (JSON `Instrucao`) |
| **Total (5 passos)** | **11.500 tokens** | **11.200 – 11.800 tokens** | **~610 tokens** |

- **Custo estimado de entrada (5 passos):** $\frac{11.500}{1.000.000} \times 0{,}20 = \text{US\$ } 0,002300$
- **Custo estimado de saída (5 passos):** $\frac{610}{1.000.000} \times 1{,}20 = \text{US\$ } 0,000732$
- **Custo total estimado por pedido completo (5 passos):** **US\$ 0,00303** (faixa de US\$ 0,00297 a US\$ 0,00309)

Para um pedido em **diligência com complementação posterior**:
- **Turno 1 (2 passos):** $2.060 + 2.180 = 4.240$ tokens de entrada + ~380 tokens de saída $\approx \text{US\$ } 0,00130$.
- **Turno 2 (complementação, 5 passos com histórico acumulado do Turno 1, partindo de ~2.550 tokens):** $\approx 13.950$ tokens de entrada + ~610 tokens de saída $\approx \text{US\$ } 0,00352$.
- **Ciclo completo diligência + complementação:** $\approx \text{US\$ } 0,00482$.

### 5.3 Volume Mensal Adotado e Projeção de Orçamento
- **Volume adotado:** **400 pedidos/mês**
  - **Justificativa:** o enunciado descreve o recebimento mensal de *"centenas de pedidos de diárias"* (p. 1). Em uma jornada padrão de **22 dias úteis/mês** (mesma convenção usada na Aula 06), 400 pedidos equivalem a **~18,2 pedidos por dia útil**, patamar intermediário representativo de uma coordenadoria estadual que atende fiscais, analistas, técnicos e motoristas na sede e unidades regionais. Aplicando a mesma taxa de diligências do acervo ($2 / 12 \approx 16{,}7\%$), estimam-se **333 pedidos regulares/mês** (5 passos cada) e **67 pedidos com diligência + complementação/mês** (totalizando **467 execuções/mês**).

| Cenário mensal | Pedidos/mês | Regulares (5 passos) | Diligência + Complementação | Custo mensal estimado (US\$) |
| :--- | :---: | :---: | :---: | :---: |
| Baixo (200/mês) | 200 | 167 | 33 | US\$ 0,67 |
| **Adotado (400/mês)** | **400** | **333** | **67** | **US\$ 1,33** |
| Alto (600/mês) | 600 | 500 | 100 | US\$ 2,00 |

*(Caso se considere 100% dos 400 pedidos em 5 passos simples sem retorno de diligência: $400 \times \text{US\$ } 0,003032 = \text{US\$ } 1,21/\text{mês}$. Esses valores teóricos serão confrontados na Etapa 6 com a mediana e a cauda efetivamente medidas em 3 rodadas contra `scripts/gabarito.json`.)*

---

## 6. Posicionamento na Grade de Autonomia (Aula 01, Seção 5)

Na matriz **Reversibilidade do Efeito × Tempo de Detecção do Erro**:

| Dimensão | Análise para a Instrução de Pedidos de Diárias |
| :--- | :--- |
| **Reversibilidade do efeito** | Embora uma diária paga indevidamente possa tecnicamente ser restituída ao erário (via desconto em folha ou processo administrativo de ressarcimento), o efeito financeiro e jurídico é **de reversão custosa e demorada**; além disso, erros como concessão sem autorização escrita em urgência ou com prestação de contas vencida violam diretamente a norma administrativa (IN SEMA nº 07/2026, Arts. 5º e 7º). |
| **Tempo de detecção do erro** | **Detecção tardia:** conforme relatado no problema (p. 1), os erros de instrução raramente são percebidos no dia da concessão; costumam aparecer **meses depois, em auditoria** ou tomada de contas. |

| | Erro detectado logo | **Erro detectado tarde** |
| :--- | :--- | :--- |
| **Reversível (ou de reversão onerosa)** | Agente age dentro de limites | **Agente age com auditoria por amostra / conferência antes do ato** |
| **Irreversível** | Agente age mediante aprovação | **Agente apenas aconselha (prepara minuta; pessoa assina)** |

**Posicionamento adotado:** **O agente NÃO age sozinho** (quadrante de **detecção tardia** com impacto financeiro/normativo de despesa pública — entre *"apenas aconselha"* e *"age mediante aprovação"*).  
- **Na prática do fluxo:** o agente atua estritamente como **instrutor técnico**: executa consultas, verifica critérios normativos, calcula quantidades/valores em código e redige a minuta do despacho.
- **Conferência humana obrigatória:** a instrução passa por barreira automática em código e segue ao **formulário Streamlit**, onde o servidor conferente revisa os fundamentos, alertas e a minuta editável antes de submeter ao **ordenador de despesa**, único detentor de competência decisória para deferir ou indeferir (Art. 10 da IN SEMA nº 07/2026).
