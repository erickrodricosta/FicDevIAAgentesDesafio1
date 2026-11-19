"""Medição completa do agente contra gabarito.json (Etapa 6).

Executa:
1. Chamada de aquecimento descartada (Aula 02, Seção 2.2) antes de cronometrar.
2. Comparação de `parallel_tool_calls=False` vs `parallel_tool_calls=True` nos 14 casos
   (12 pedidos + 2 complementações).
3. Três rodadas independentes completas (42 instruções) com a configuração escolhida,
   calculando acertos, passos, tokens da 1ª chamada e incremento por passo, mediana,
   cauda (máximo), razão máx/mediana e projeção para 400 pedidos/mês.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from src.agente import MODELO_PADRAO, criar_agente, instruir_pedido
from src.ferramentas import PASTA_BASE, PASTA_RESULTADOS, carregar_complementacoes, carregar_pedidos
from src.modelos import ResultadoInstrucao

PASTA_BANCOS_EVAL = PASTA_BASE / "tmp" / "eval"


def _limpar_banco(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    for sufixo in ("", "-wal", "-shm"):
        p = Path(str(caminho) + sufixo)
        if p.exists():
            p.unlink()


def _aquecer_conexao() -> None:
    """Chamada de aquecimento descartada da medição de latência (Aula 02, Seção 2.2)."""
    ag = Agent(
        model=OpenAIChat(id=MODELO_PADRAO, reasoning_effort="none"),
        markdown=False,
        telemetry=False,
    )
    ag.run("ok")


def avaliar_contra_gabarito(
    resultado: ResultadoInstrucao,
    esperado: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Compara Instrucao aprovada pela barreira contra o item correspondente de gabarito.json."""
    divergencias: list[str] = []
    if resultado.erro_api:
        divergencias.append(f"erro_api: {resultado.erro_detalhe_interno}")
        return False, divergencias
    if not resultado.aprovado_barreira or resultado.instrucao is None:
        divergencias.append(f"recusado_barreira: {resultado.motivos_recusa_barreira}")
        return False, divergencias

    inst = resultado.instrucao
    if inst.recomendacao != esperado["recomendacao"]:
        divergencias.append(
            f"recomendacao: esperado={esperado['recomendacao']}, obtido={inst.recomendacao}"
        )

    qtd_esp = esperado["quantidade_diarias"]
    if qtd_esp is None:
        if inst.quantidade_diarias is not None:
            divergencias.append(
                f"quantidade_diarias: esperado=None, obtido={inst.quantidade_diarias}"
            )
    elif inst.quantidade_diarias is None or abs(float(inst.quantidade_diarias) - float(qtd_esp)) > 0.01:
        divergencias.append(
            f"quantidade_diarias: esperado={qtd_esp}, obtido={inst.quantidade_diarias}"
        )

    val_esp = esperado["valor_total"]
    if val_esp is None:
        if inst.valor_total is not None:
            divergencias.append(f"valor_total: esperado=None, obtido={inst.valor_total}")
    elif inst.valor_total is None or abs(float(inst.valor_total) - float(val_esp)) > 0.01:
        divergencias.append(f"valor_total: esperado={val_esp}, obtido={inst.valor_total}")

    if inst.exige_autorizacao_superior != bool(esperado["exige_autorizacao_superior"]):
        divergencias.append(
            f"exige_autorizacao_superior: esperado={esperado['exige_autorizacao_superior']}, obtido={inst.exige_autorizacao_superior}"
        )

    nao_atendidos_obtidos = sorted(
        v.criterio for v in inst.verificacoes if v.situacao == "nao_atende"
    )
    nao_atendidos_esp = sorted(esperado["criterios_nao_atendidos"])
    if nao_atendidos_obtidos != nao_atendidos_esp:
        divergencias.append(
            f"criterios_nao_atendidos: esperado={nao_atendidos_esp}, obtido={nao_atendidos_obtidos}"
        )

    return (len(divergencias) == 0), divergencias


def executar_bateria_14_casos(
    nome_execucao: str,
    *,
    parallel_tool_calls: bool,
    pedidos: list[dict[str, Any]],
    complementacoes_por_num: dict[str, dict[str, Any]],
    gabarito: dict[str, Any],
) -> dict[str, Any]:
    """Executa os 12 pedidos e as 2 complementações sem intervenção manual."""
    db_file = PASTA_BANCOS_EVAL / f"{nome_execucao}.db"
    _limpar_banco(db_file)

    agente = criar_agente(
        db_file=db_file,
        parallel_tool_calls=parallel_tool_calls,
        tool_call_limit=8,
        add_history_to_context=True,
        num_history_runs=6,
        update_memory_on_run=False,
        usar_guardrail_pii=True,
        debug_mode=False,
    )

    registros: list[dict[str, Any]] = []

    # 1) Os 12 pedidos
    for ped in pedidos:
        num = ped["numero"]
        res = instruir_pedido(
            agente,
            ped,
            session_id=num,
            user_id=str(ped["matricula"]),
        )
        acertou, diffs = avaliar_contra_gabarito(res, gabarito["pedidos"][num])
        registros.append(
            {
                "id_caso": num,
                "tipo": "pedido",
                "caso_descricao": gabarito["pedidos"][num]["caso"],
                "acertou": acertou,
                "divergencias": diffs,
                "status_execucao": res.status_execucao,
                "aprovado_barreira": res.aprovado_barreira,
                "recomendacao": res.instrucao.recomendacao if res.instrucao else None,
                "quantidade_diarias": res.instrucao.quantidade_diarias if res.instrucao else None,
                "valor_total": res.instrucao.valor_total if res.instrucao else None,
                "chamadas_modelo": res.chamadas_modelo,
                "ferramentas_chamadas": [f.nome for f in res.ferramentas],
                "tokens_entrada_por_chamada": res.tokens_entrada_por_chamada,
                "tokens_entrada": res.tokens_entrada,
                "tokens_saida": res.tokens_saida,
                "custo_usd": res.custo_usd,
                "tempo_s": res.tempo_segundos,
            }
        )

    # 2) As 2 complementações na mesma sessão dos respectivos pedidos
    pedidos_por_num = {p["numero"]: p for p in pedidos}
    for num, comp in complementacoes_por_num.items():
        ped = pedidos_por_num[num]
        msg_comp = (
            f"Complementação do pedido {num} (enviada em {comp['data']}):\n"
            f"{comp['texto']}\n"
            "Reavalie o pedido completo considerando os dados originais e esta complementação."
        )
        res = instruir_pedido(
            agente,
            ped,
            complementacoes=[comp["texto"]],
            session_id=num,
            user_id=str(ped["matricula"]),
            mensagem_override=msg_comp,
        )
        acertou, diffs = avaliar_contra_gabarito(res, gabarito["complementacoes"][num])
        registros.append(
            {
                "id_caso": f"{num} (comp)",
                "tipo": "complementacao",
                "caso_descricao": gabarito["complementacoes"][num]["caso"],
                "acertou": acertou,
                "divergencias": diffs,
                "status_execucao": res.status_execucao,
                "aprovado_barreira": res.aprovado_barreira,
                "recomendacao": res.instrucao.recomendacao if res.instrucao else None,
                "quantidade_diarias": res.instrucao.quantidade_diarias if res.instrucao else None,
                "valor_total": res.instrucao.valor_total if res.instrucao else None,
                "chamadas_modelo": res.chamadas_modelo,
                "ferramentas_chamadas": [f.nome for f in res.ferramentas],
                "tokens_entrada_por_chamada": res.tokens_entrada_por_chamada,
                "tokens_entrada": res.tokens_entrada,
                "tokens_saida": res.tokens_saida,
                "custo_usd": res.custo_usd,
                "tempo_s": res.tempo_segundos,
            }
        )

    custos = [r["custo_usd"] for r in registros]
    tempos = [r["tempo_s"] for r in registros]
    passos = [r["chamadas_modelo"] for r in registros]
    mediana_custo = statistics.median(custos) if custos else 0.0
    max_custo = max(custos) if custos else 0.0
    min_custo = min(custos) if custos else 0.0

    # Tokens da 1ª chamada e incremento médio por passo em execuções com 5 chamadas
    primeiras_chamadas = [
        r["tokens_entrada_por_chamada"][0]
        for r in registros
        if r["tokens_entrada_por_chamada"]
    ]
    incrementos_passo: list[float] = []
    for r in registros:
        seq = r["tokens_entrada_por_chamada"]
        if len(seq) >= 2:
            for a, b in zip(seq, seq[1:]):
                incrementos_passo.append(float(b - a))

    return {
        "nome_execucao": nome_execucao,
        "parallel_tool_calls": parallel_tool_calls,
        "total_casos": len(registros),
        "acertos": sum(1 for r in registros if r["acertou"]),
        "recusas_barreira": sum(1 for r in registros if r["status_execucao"] == "BARREIRA_RECUSOU"),
        "erros_api": sum(1 for r in registros if r["status_execucao"] == "ERROR"),
        "chamadas_totais": sum(passos),
        "passos_mediana": statistics.median(passos),
        "passos_max": max(passos),
        "tokens_entrada_total": sum(r["tokens_entrada"] for r in registros),
        "tokens_saida_total": sum(r["tokens_saida"] for r in registros),
        "tokens_1a_chamada_medio": round(statistics.mean(primeiras_chamadas), 1) if primeiras_chamadas else 0.0,
        "incremento_medio_por_passo": round(statistics.mean(incrementos_passo), 1) if incrementos_passo else 0.0,
        "custo_total_usd": round(sum(custos), 6),
        "custo_min_usd": round(min_custo, 6),
        "custo_mediana_usd": round(mediana_custo, 6),
        "custo_max_usd": round(max_custo, 6),
        "razao_max_sobre_mediana": round(max_custo / mediana_custo, 2) if mediana_custo > 0 else 0.0,
        "tempo_total_s": round(sum(tempos), 2),
        "registros": registros,
    }


def executar_avaliacao_completa() -> dict[str, Any]:
    pedidos = carregar_pedidos()
    complementacoes_por_num = {c["numero"]: c for c in carregar_complementacoes()}
    gabarito = json.loads((Path(__file__).resolve().parent / "gabarito.json").read_text(encoding="utf-8"))

    _aquecer_conexao()

    # 1) Comparação parallel_tool_calls=False vs True
    comp_false = executar_bateria_14_casos(
        "paralelas_false",
        parallel_tool_calls=False,
        pedidos=pedidos,
        complementacoes_por_num=complementacoes_por_num,
        gabarito=gabarito,
    )
    comp_true = executar_bateria_14_casos(
        "paralelas_true",
        parallel_tool_calls=True,
        pedidos=pedidos,
        complementacoes_por_num=complementacoes_por_num,
        gabarito=gabarito,
    )

    comparacao_paralelas = {
        "escopo": "12 pedidos + 2 complementações (14 casos) em cada configuração",
        "resultados": [comp_false, comp_true],
    }
    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    (PASTA_RESULTADOS / "medicao_paralelas.json").write_text(
        json.dumps(comparacao_paralelas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) Três rodadas completas com a configuração escolhida (parallel_tool_calls=False)
    # Reaproveita comp_false como Rodada 1 ou executa 3 rodadas independentes dedicadas.
    # Executamos 3 rodadas dedicadas (r1, r2, r3) para que todas sejam homogêneas e auditáveis.
    rodadas: list[dict[str, Any]] = []
    for idx in range(1, 4):
        rodadas.append(
            executar_bateria_14_casos(
                f"rodada_{idx}",
                parallel_tool_calls=False,
                pedidos=pedidos,
                complementacoes_por_num=complementacoes_por_num,
                gabarito=gabarito,
            )
        )

    todos_registros = [r for rod in rodadas for r in rod["registros"]]
    todos_custos = [r["custo_usd"] for r in todos_registros]
    custos_5_passos = [r["custo_usd"] for r in todos_registros if r["chamadas_modelo"] == 5]
    primeiras_5p = [
        r["tokens_entrada_por_chamada"][0]
        for r in todos_registros
        if r["chamadas_modelo"] == 5 and r["tokens_entrada_por_chamada"]
    ]
    entradas_5p = [r["tokens_entrada"] for r in todos_registros if r["chamadas_modelo"] == 5]
    saidas_5p = [r["tokens_saida"] for r in todos_registros if r["chamadas_modelo"] == 5]

    mediana_geral = statistics.median(todos_custos)
    max_geral = max(todos_custos)
    razao_cauda = round(max_geral / mediana_geral, 2) if mediana_geral > 0 else 0.0

    resumo_3_rodadas = {
        "configuracao_escolhida": {
            "modelo": MODELO_PADRAO,
            "parallel_tool_calls": False,
            "tool_call_limit": 8,
            "memoria": "SqliteDb + add_history_to_context=True + num_history_runs=6",
        },
        "total_instrucoes": len(todos_registros),
        "total_acertos": sum(1 for r in todos_registros if r["acertou"]),
        "acertos_por_rodada": [f"{rod['acertos']}/{rod['total_casos']}" for rod in rodadas],
        "custo_mediana_geral_usd": round(mediana_geral, 6),
        "custo_max_geral_usd": round(max_geral, 6),
        "razao_cauda_mediana": razao_cauda,
        "projecao_400_pedidos_mediana_usd": round(mediana_geral * 400, 4),
        "projecao_400_pedidos_cauda_usd": round(max_geral * 400, 4),
        "casos_5_passos": {
            "quantidade": len(custos_5_passos),
            "tokens_1a_chamada_medio": round(statistics.mean(primeiras_5p), 1) if primeiras_5p else 0.0,
            "tokens_entrada_medio": round(statistics.mean(entradas_5p), 1) if entradas_5p else 0.0,
            "tokens_saida_medio": round(statistics.mean(saidas_5p), 1) if saidas_5p else 0.0,
            "custo_medio_usd": round(statistics.mean(custos_5_passos), 6) if custos_5_passos else 0.0,
        },
        "rodadas": rodadas,
    }

    (PASTA_RESULTADOS / "medicao_rodadas.json").write_text(
        json.dumps(resumo_3_rodadas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    linhas_md = [
        "# Medição contra o Gabarito (Etapa 6)",
        "",
        "## Comparação de Chamadas Paralelas (14 casos)",
        "| Configuração | Acertos | Recusas barreira | Chamadas | Entrada | Saída | Mediana US$ | Máx US$ | Razão Máx/Med | Tempo | Total US$ |",
        "| :--- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: |",
    ]
    for c in [comp_false, comp_true]:
        linhas_md.append(
            f"| `parallel_tool_calls={c['parallel_tool_calls']}` | {c['acertos']}/{c['total_casos']} | "
            f"{c['recusas_barreira']} | {c['chamadas_totais']} | {c['tokens_entrada_total']} | "
            f"{c['tokens_saida_total']} | {c['custo_mediana_usd']:.5f} | {c['custo_max_usd']:.5f} | "
            f"{c['razao_max_sobre_mediana']:.2f}× | {c['tempo_total_s']:.1f} s | {c['custo_total_usd']:.5f} |"
        )

    linhas_md.extend(
        [
            "",
            "## Três Rodadas Completas (`parallel_tool_calls=False`, `tool_call_limit=8`)",
            "| Rodada | Acertos | Recusas | Chamadas | Entrada | Saída | Mediana US$ | Máx US$ | Tempo | Total US$ |",
            "| :--- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for rod in rodadas:
        linhas_md.append(
            f"| {rod['nome_execucao']} | {rod['acertos']}/{rod['total_casos']} | {rod['recusas_barreira']} | "
            f"{rod['chamadas_totais']} | {rod['tokens_entrada_total']} | {rod['tokens_saida_total']} | "
            f"{rod['custo_mediana_usd']:.5f} | {rod['custo_max_usd']:.5f} | {rod['tempo_total_s']:.1f} s | "
            f"{rod['custo_total_usd']:.5f} |"
        )

    linhas_md.extend(
        [
            "",
            f"- **Acerto acumulado nas 3 rodadas:** {resumo_3_rodadas['total_acertos']}/{resumo_3_rodadas['total_instrucoes']}",
            f"- **Mediana geral:** US$ {resumo_3_rodadas['custo_mediana_geral_usd']:.5f} | **Cauda (máx):** US$ {resumo_3_rodadas['custo_max_geral_usd']:.5f} | **Razão:** {resumo_3_rodadas['razao_cauda_mediana']:.2f}×",
            f"- **Projeção 400 pedidos/mês (mediana):** US$ {resumo_3_rodadas['projecao_400_pedidos_mediana_usd']:.2f}/mês | **(cauda):** US$ {resumo_3_rodadas['projecao_400_pedidos_cauda_usd']:.2f}/mês",
            f"- **Casos de 5 passos (confronto Etapa 1):** 1ª chamada média = {resumo_3_rodadas['casos_5_passos']['tokens_1a_chamada_medio']} tokens | entrada média = {resumo_3_rodadas['casos_5_passos']['tokens_entrada_medio']} tokens | saída média = {resumo_3_rodadas['casos_5_passos']['tokens_saida_medio']} tokens | custo médio = US$ {resumo_3_rodadas['casos_5_passos']['custo_medio_usd']:.5f}",
        ]
    )
    (PASTA_RESULTADOS / "medicao_rodadas.md").write_text("\n".join(linhas_md) + "\n", encoding="utf-8")
    return resumo_3_rodadas


if __name__ == "__main__":
    executar_avaliacao_completa()
    print((PASTA_RESULTADOS / "medicao_rodadas.md").read_text(encoding="utf-8"))
