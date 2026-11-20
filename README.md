# Desafio 01 — Instrução de Pedidos de Diárias (SEMA-MT)

Sistema de apoio à instrução de pedidos de diárias da Coordenadoria de Diárias e Passagens (SEMA-MT), construído com **Agno 3.2.1** e **Streamlit**, aplicando integralmente os conceitos das Aulas 01 a 07 à Instrução Normativa SEMA nº 07/2026 (hipotética).

---

## 1. Estrutura do Projeto

```text
FicDevIAAgentesDesafio1/
├── .env.example               # Modelo de variáveis de ambiente
├── .gitignore                 # Ignora .env, .venv/, __pycache__/, *.db, tmp/
├── requirements.txt           # Dependências do projeto (inclui sqlalchemy[asyncio])
├── LEIA-ME.md                 # Instruções de execução e decisões técnicas
├── desenho.md                 # Etapa 1: fluxo, PEAS, confiabilidade, custo e autonomia
├── relatorio.md               # Etapa 6: medições, falhas e conferência humana
├── dados/                     # Base hipotética da SEMA-MT (7 arquivos)
├── src/                       # Núcleo da aplicação e do agente
│   ├── __init__.py
│   ├── modelos.py             # Contratos Pydantic (Verificacao, Instrucao, ResultadoInstrucao)
│   ├── ferramentas.py         # Etapa 2: 4 funções Python puras + teste sem agente/chave
│   ├── barreiras.py           # Etapa 3: guardrail PII (padrão BR) + barreira determinística
│   ├── agente.py              # Etapa 3: Agent Agno e fronteira instruir_pedido()
│   └── memoria.py             # Etapas 4/5: inspeção SQLite, eliminação LGPD e conferências
├── app/                       # Interface de usuário
│   └── app_diarias.py         # Etapa 5: formulário Streamlit de conferência humana e LGPD
├── scripts/                   # Geração de dados, gabarito, medições e diagnóstico
│   ├── gerar_dados.py         # Gerador do acervo hipotético e scripts/gabarito.json
│   ├── gabarito.json          # Gabarito normativo (uso exclusivo dos scripts de medição)
│   ├── experimento_memoria.py # Etapa 4: 3 configs de memória + teste de eliminação LGPD
│   ├── avaliacao.py           # Etapa 6: comparação parallel_tool_calls + 3 rodadas
│   └── falhas.py              # Etapa 6: provocação dos 4 modos de falha
└── resultados/                # Saídas e evidências gravadas das etapas
```

- [desenho.md](desenho.md) — Etapa 1: fluxo manual vs agente, quadro PEAS verificável, confiabilidade composta ($p^n$), estimativa de custo para 400 pedidos/mês e quadrante de autonomia.
- [src/ferramentas.py](src/ferramentas.py) — Etapa 2: 4 funções Python puras (`consultar_servidor`, `consultar_historico_diarias`, `calcular_diarias`, `consultar_saldo_diarias`) com minimização de PII, aritmética em código e teste isolado sem chave.
- [src/modelos.py](src/modelos.py) — Contrato Pydantic (`Verificacao`, `Instrucao`) e envelope de execução (`ResultadoInstrucao`).
- [src/barreiras.py](src/barreiras.py) — Filtro `PIIDetectionGuardrail` para CPF e conta/agência brasileiros + barreira determinística em código (`validar_execucao`) que bloqueia argumentos/valores não ancorados no pedido/complementação ou nas ferramentas.
- [src/agente.py](src/agente.py) — Configuração do `Agent` no Agno e fronteira `instruir_pedido()` / `executar_eliminacao_no_banco()`.
- [src/memoria.py](src/memoria.py) — Inspeção SQLite tabela por tabela, rotina de eliminação verificável (LGPD) e registro de conferências humanas em JSONL.
- [scripts/gerar_dados.py](scripts/gerar_dados.py) — Gerador do acervo hipotético em `dados/` e de [scripts/gabarito.json](scripts/gabarito.json).
- [scripts/experimento_memoria.py](scripts/experimento_memoria.py) — Etapa 4: medição de 3 configurações de memória nas 2 complementações e teste de eliminação de Beatriz (`206689`) e Carla (`207418`).
- [app/app_diarias.py](app/app_diarias.py) — Etapa 5: aplicação Streamlit em padrão de formulário com progresso `st.status`, minuta editável, registro de divergências, complementação na mesma sessão e aba LGPD.
- [scripts/avaliacao.py](scripts/avaliacao.py) — Etapa 6: comparação `parallel_tool_calls=False` vs `True` e 3 rodadas completas (42 instruções) contra [scripts/gabarito.json](scripts/gabarito.json).
- [scripts/falhas.py](scripts/falhas.py) — Etapa 6: provocação honesta dos 4 modos de falha.
- [relatorio.md](relatorio.md) — Consolidação dos números medidos, confronto com a Etapa 1, modos de falha e decisão sobre conferência humana.
- [resultados/](resultados/) — Evidências e saídas gravadas de todas as etapas.

---

## 2. Como Executar

### 2.1 Pré-requisitos e Instalação
Requer **Python 3.10+** (validado em Python 3.13.14 no `.venv`).  
> **Nota importante:** o pacote `sqlalchemy[asyncio]` é obrigatório para incluir o `greenlet`, exigido pelo `SqliteDb` do Agno.

```powershell
# Criar e ativar ambiente virtual (caso ainda não exista)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalar dependências
pip install -r requirements.txt
```

### 2.2 Configuração de Variáveis de Ambiente
Copie [.env.example](.env.example) para `.env` na raiz do repositório e preencha sua chave da OpenAI (o `.env` está no `.gitignore` e nunca deve ser versionado):

```env
OPENAI_API_KEY=sk-sua-chave-aqui
OPENAI_MODEL=gpt-5.6-luna
AGNO_TELEMETRY=false
```

### 2.3 Execução Passo a Passo

```powershell
# (Opcional) Regenerar o acervo hipotético e o scripts/gabarito.json
.\.venv\Scripts\python.exe scripts/gerar_dados.py

# Etapa 2: Testar as 4 ferramentas isoladamente (sem agente e sem chave)
.\.venv\Scripts\python.exe src/ferramentas.py

# Etapa 4: Medir as 3 configurações de memória e testar eliminação LGPD
.\.venv\Scripts\python.exe scripts/experimento_memoria.py

# Etapa 6a: Comparar chamadas paralelas e executar 3 rodadas contra scripts/gabarito.json
.\.venv\Scripts\python.exe scripts/avaliacao.py

# Etapa 6b: Provocar e diagnosticar os 4 modos de falha
.\.venv\Scripts\python.exe scripts/falhas.py

# Etapa 5: Subir o formulário de conferência humana no navegador
.\.venv\Scripts\streamlit.exe run app/app_diarias.py
```

---

## 3. Decisões Técnicas e Respostas às Perguntas do Desafio

### 1. Que configuração de chamadas paralelas, teto de chamadas e memória você escolheu, e com base em que número?
- **Chamadas paralelas (`parallel_tool_calls=False`):** escolhida sobre `True`. Na comparação dos 14 casos ([resultados/medicao_paralelas.json](resultados/medicao_paralelas.json)), ambas obtiveram **13/14 acertos** e **64 chamadas**, porém `False` consumiu ligeiramente menos tokens (**225.317** vs 225.681 entrada; **10.133** vs 10.323 saída), apresentou menor razão cauda/mediana (**1,15×** vs **1,18×**) e garante na própria API da OpenAI que etapas dependentes (`consultar_servidor` → `calcular_diarias` → `consultar_saldo_diarias`) jamais executem em paralelo com parâmetros supostos.
- **Teto de chamadas (`tool_call_limit=8`):** dimensionado acima dos **4 usos nominais** de ferramentas em pedidos regulares (5 chamadas ao modelo no total) para absorver eventual reconsulta em complementação sem permitir laços caros em caso de hesitação.
- **Memória (`SqliteDb` + `add_history_to_context=True` + `num_history_runs=6`, sem `update_memory_on_run`):** na medição das 2 complementações ([resultados/medicao_memoria.md](resultados/medicao_memoria.md)), **sem memória** obteve **0/2 acertos** (o modelo inventou matrícula e datas e foi bloqueado pela barreira). O **histórico da sessão** alcançou **2/2 acertos** custando **US\$ 0,00672–0,00687** por ciclo de 2 turnos — contra **US\$ 0,00734–0,00869** quando acrescido de `update_memory_on_run=True`, além de evitar gravar fatos livres na tabela `agno_memories`.

### 2. Como o sistema impede que uma instrução fundamentada em dado inventado chegue ao conferente?
Por meio de **duas camadas em código Python fora do prompt**:
1. **Contas determinísticas nas ferramentas ([src/ferramentas.py](src/ferramentas.py)):** antecedência, prazos de prestação de contas, quantidade de diárias, valores do Anexo I, acumulado mensal e comparação de saldo são calculados integralmente em código.
2. **Barreira de validação pós-execução ([src/barreiras.py](src/barreiras.py), `validar_execucao`):** antes de exibir qualquer resultado, confere em código todas as chamadas em `resposta.tools` e o objeto `Instrucao` contra o pedido/complementação:
   - toda matrícula consultada e toda data passada a `calcular_diarias` precisa constar literalmente do pedido ou das complementações recebidas (se `data_retorno` estiver ausente sem complementação, qualquer cálculo é bloqueado);
   - `grupo`, `unidade` e `valor` devem coincidir com o retorno das ferramentas anteriores e o nome cadastrado da matrícula final deve coincidir com o nome do pedido;
   - `quantidade_diarias` e `valor_total` da `Instrucao` devem estar ancorados (tolerância R\$ 0,01) nos valores retornados por `calcular_diarias` (e serem `None` na diligência);
   - qualquer recusa da barreira ou erro da API (`RunStatus.error`) oculta integralmente o conteúdo recusado e exibe apenas a mensagem padrão encaminhando o processo para análise manual. Esse bloqueio foi comprovado na prática na Config 1 sem memória (2/2 bloqueios ao modelo inventar matrícula/datas) e no teste determinístico da Falha 4.

### 3. Que dados do servidor o agente guarda, por quanto tempo, e como o titular os elimina?
- **O que é guardado e onde:** usando `SqliteDb` com `add_history_to_context=True` e `update_memory_on_run=False`, o banco de trabalho do agente armazena em `agno_sessions` e `agno_runs` o `session_id` (número do pedido), o `user_id` (matrícula informada no pedido), as mensagens do pedido/complementação (já **filtradas pelo `PIIDetectionGuardrail`** — com **0 ocorrências** de CPF, conta ou agência bancária no banco), as chamadas/retornos das ferramentas (sem CPF nem e-mail por minimização) e a `Instrucao` gerada.
- **Prazo de retenção (política de governança):** por se tratar apenas de **cópia operacional de trabalho** para instrução e eventual complementação de diligência, adota-se retenção máxima de **30 dias após o encerramento/arquivamento do pedido** (com expurgo automático programado), distinguindo-a dos autos oficiais de concessão de diárias, que permanecem no sistema de despesa pública conforme normas de transparência e prestação de contas.
- **Como o titular elimina ([src/memoria.py](src/memoria.py)):** a rotina de eliminação (acessível também pela aba *Eliminação de Dados (LGPD)* do formulário) executa três etapas em sequência: (1) exclui sessões e execuções vinculadas ao `user_id` do titular; (2) lista e exclui eventuais memórias via `delete_user_memories`; e (3) **varre todas as tabelas do SQLite buscando a matrícula e o nome do titular** para capturar sessões gravadas sob `user_id` divergente por erro de digitação (como comprovado no `DIA-2026-0112`, gravado sob `user_id="207481"`), confirmando **0 registros remanescentes** em todas as tabelas.

### 4. Qual o ponto de conferência humana no fluxo e por que ele é obrigatório nesse ponto?
- O ponto obrigatório fica **imediatamente após a aprovação pela barreira em código e antes da decisão do ordenador de despesa** (Art. 10 da IN SEMA nº 07/2026), implementado na aba *Instrução e Conferência* de [app/app_diarias.py](app/app_diarias.py).
- **Por quê:** conforme o posicionamento na grade de autonomia (detecção tardia em auditoria + despesa pública) e os dados medidos (**39/42** pela divergência taxonômica no `DIA-2026-0112`, necessidade de validar autorização expressa e escrita do Secretário Adjunto no `DIA-2026-0106`, e alertas de injeção no `DIA-2026-0107`), o agente prepara a instrução e a minuta editável, enquanto o servidor confere, edita se necessário e registra sua decisão (com justificativa obrigatória em caso de divergência) antes da assinatura pelo ordenador.
