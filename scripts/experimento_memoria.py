"""Experimento de memória, custo por turno e eliminação LGPD (Etapa 4).

Executa os dois casos de diligência + complementação (DIA-2026-0111 e DIA-2026-0112)
em três configurações:
1. Sem memória
2. Histórico da sessão (add_history_to_context=True, num_history_runs=6)
3. Histórico da sessão + memórias do usuário (update_memory_on_run=True)

Ao final, executa e valida a rotina de eliminação para as duas servidoras
(Beatriz Moraes Cunha - 206689 e Carla Regina Souza - 207418), confirmando tabela
por tabela e por nova pergunta ao agente que nenhum dado pessoal restou.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

from src.agente import MODELO_PADRAO, criar_agente, instruir_pedido
from src.ferramentas import PASTA_BASE, PASTA_RESULTADOS, carregar_complementacoes, carregar_pedidos
from src.memoria import eliminar_dados_titular, inspecionar_banco_titular

PASTA_BANCOS_TEMP = PASTA_BASE / "tmp" / "exp_memoria"


def _limpar_banco(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    for sufixo in ("", "-wal", "-shm"):
        p = Path(str(caminho) + sufixo)
        if p.exists():
            p.unlink()


def _conferir_contra_gabarito(numero: str, resultado: Any, gabarito_comp: dict[str, Any]) -> bool:
    if not resultado.aprovado_barreira or resultado.instrucao is None:
        return False
    inst = resultado.instrucao
    esp = gabarito_comp[numero]
    qtd_ok = inst.quantidade_diarias == esp["quantidade_diarias"]
    val_ok = (
        inst.valor_total is not None
        and abs(float(inst.valor_total) - float(esp["valor_total"])) <= 0.01
    )
    rec_ok = inst.recomendacao == esp["recomendacao"]
    aut_ok = inst.exige_autorizacao_superior == esp["exige_autorizacao_superior"]
    return bool(qtd_ok and val_ok and rec_ok and aut_ok)


def _perguntar_ao_agente_pos_exclusao(db: SqliteDb, user_id: str, session_id: str, pergunta: str) -> str:
    """Abre uma nova sessão e verifica se o agente ainda sabe algo sobre o titular."""
    ag = Agent(
        model=OpenAIChat(id=MODELO_PADRAO, reasoning_effort="none"),
        db=db,
        instructions=(
            "Responda apenas com base no que você sabe pelas memórias ou histórico disponíveis "
            "para esta conversa. Se não houver nenhuma informação registrada sobre o usuário, "
            "diga claramente que não há registro."
        ),
        add_history_to_context=True,
        num_history_runs=6,
        markdown=False,
        telemetry=False,
    )
    resp = ag.run(pergunta, user_id=user_id, session_id=session_id)
    return str(getattr(resp, "content", "")).strip()


def executar_experimento_memoria() -> dict[str, Any]:
    pedidos_por_num = {p["numero"]: p for p in carregar_pedidos()}
    comps_por_num = {c["numero"]: c for c in carregar_complementacoes()}
    gabarito = json.loads((Path(__file__).resolve().parent / "gabarito.json").read_text(encoding="utf-8"))
    gab_comp = gabarito["complementacoes"]

    casos = ["DIA-2026-0111", "DIA-2026-0112"]
    configs = [
        ("sem_memoria", "1 · Sem memória", False, False),
        ("historico_sessao", "2 · Histórico da sessão (teto=6)", True, False),
        ("historico_mais_memorias", "3 · Histórico + memórias do usuário", True, True),
    ]

    resultados_configs: list[dict[str, Any]] = []
    banco_config3: Path | None = None
    agente_config3: Agent | None = None

    for slug, rotulo, add_hist, upd_mem in configs:
        db_file = PASTA_BANCOS_TEMP / f"{slug}.db" if add_hist else None
        if db_file is not None:
            _limpar_banco(db_file)

        agente = criar_agente(
            db_file=db_file,
            parallel_tool_calls=False,
            tool_call_limit=8,
            add_history_to_context=add_hist,
            num_history_runs=6 if add_hist else None,
            update_memory_on_run=upd_mem,
            usar_guardrail_pii=True,
        )

        casos_medidos: list[dict[str, Any]] = []
        for num in casos:
            ped = pedidos_por_num[num]
            comp = comps_por_num[num]
            # Turno 1: session_id = número do pedido, user_id = matrícula informada no pedido
            t1 = instruir_pedido(
                agente,
                ped,
                session_id=num,
                user_id=str(ped["matricula"]),
            )
            # Turno 2: complementação na mesma sessão do pedido
            msg_comp = (
                f"Complementação do pedido {num} (enviada em {comp['data']}):\n"
                f"{comp['texto']}\n"
                "Reavalie o pedido completo considerando os dados originais e esta complementação."
            )
            t2 = instruir_pedido(
                agente,
                ped,
                complementacoes=[comp["texto"]],
                session_id=num,
                user_id=str(ped["matricula"]),
                mensagem_override=msg_comp,
            )
            aplicada_ok = _conferir_contra_gabarito(num, t2, gab_comp)

            casos_medidos.append(
                {
                    "numero_pedido": num,
                    "turno1": {
                        "status": t1.status_execucao,
                        "recomendacao": t1.instrucao.recomendacao if t1.instrucao else None,
                        "chamadas_modelo": t1.chamadas_modelo,
                        "tokens_entrada": t1.tokens_entrada,
                        "tokens_saida": t1.tokens_saida,
                        "custo_usd": t1.custo_usd,
                        "tempo_s": t1.tempo_segundos,
                    },
                    "turno2_complementacao": {
                        "status": t2.status_execucao,
                        "aprovado_barreira": t2.aprovado_barreira,
                        "motivos_recusa": t2.motivos_recusa_barreira,
                        "recomendacao": t2.instrucao.recomendacao if t2.instrucao else None,
                        "matricula_final": t2.instrucao.matricula if t2.instrucao else None,
                        "quantidade_diarias": t2.instrucao.quantidade_diarias if t2.instrucao else None,
                        "valor_total": t2.instrucao.valor_total if t2.instrucao else None,
                        "chamadas_modelo": t2.chamadas_modelo,
                        "tokens_entrada": t2.tokens_entrada,
                        "tokens_saida": t2.tokens_saida,
                        "custo_usd": t2.custo_usd,
                        "tempo_s": t2.tempo_segundos,
                        "aplicada_ao_pedido_certo": aplicada_ok,
                    },
                    "custo_total_2_turnos_usd": round(t1.custo_usd + t2.custo_usd, 6),
                    "entrada_total_2_turnos": t1.tokens_entrada + t2.tokens_entrada,
                }
            )

        resultados_configs.append(
            {
                "slug": slug,
                "configuracao": rotulo,
                "casos": casos_medidos,
                "acertos_complementacao": sum(
                    1 for c in casos_medidos if c["turno2_complementacao"]["aplicada_ao_pedido_certo"]
                ),
                "custo_total_usd": round(sum(c["custo_total_2_turnos_usd"] for c in casos_medidos), 6),
            }
        )
        if slug == "historico_mais_memorias":
            banco_config3 = db_file
            agente_config3 = agente

    # Teste de eliminação LGPD no banco da configuração 3 (sessões + execuções + memórias)
    assert banco_config3 is not None and agente_config3 is not None
    db_c3 = SqliteDb(db_file=str(banco_config3))
    titulares = [
        ("206689", "Beatriz Moraes Cunha", "Qual é a minha matrícula, nome e viagem do pedido DIA-2026-0111?"),
        ("207418", "Carla Regina Souza", "Qual é a minha matrícula, nome e viagem do pedido DIA-2026-0112?"),
    ]
    eliminacoes: list[dict[str, Any]] = []
    for matricula, nome, pergunta in titulares:
        rel_elim = eliminar_dados_titular(agente_config3, db_c3, banco_config3, matricula, nome)
        pos_sessao = _perguntar_ao_agente_pos_exclusao(
            db_c3, user_id=matricula, session_id=f"verif_pos_elim_{matricula}", pergunta=pergunta
        )
        # Também testa com a matrícula trocada no caso de Carla para confirmar zero vestígio
        pos_sessao_trocada = None
        if matricula == "207418":
            pos_sessao_trocada = _perguntar_ao_agente_pos_exclusao(
                db_c3,
                user_id="207481",
                session_id="DIA-2026-0112",
                pergunta="Qual o pedido da servidora Carla Regina Souza?",
            )
            # Limpa também essa sessão de verificação para não deixar rastro
            db_c3.delete_session("DIA-2026-0112")
        db_c3.delete_session(f"verif_pos_elim_{matricula}")
        rel_elim["verificacao_pos_exclusao_em_nova_sessao"] = pos_sessao
        if pos_sessao_trocada is not None:
            rel_elim["verificacao_pos_exclusao_sessao_0112"] = pos_sessao_trocada
        rel_elim["estado_final_banco"] = inspecionar_banco_titular(banco_config3, matricula, nome)
        eliminacoes.append(rel_elim)

    payload = {
        "escopo": "Medição de memória nos 2 pedidos com diligência/complementação (Etapa 4)",
        "observacao_lgpd": (
            "A rotina de eliminação alcança somente o banco de trabalho do agente (SQLite). "
            "O processo oficial de concessão de diárias permanece sujeito às normas de despesa pública, "
            "transparência e guarda documental."
        ),
        "configuracoes": resultados_configs,
        "eliminacao_lgpd": eliminacoes,
    }

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    (PASTA_RESULTADOS / "medicao_memoria.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (PASTA_RESULTADOS / "teste_eliminacao.json").write_text(
        json.dumps(eliminacoes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Relatórios legíveis em Markdown / TXT
    linhas_md = [
        "# Medição de Memória e Custo por Turno (Etapa 4)",
        "",
        "| Configuração | Pedido | Entrada Turno 1 | Entrada Turno 2 (Comp.) | Saída Total | Custo Total (US$) | Aplicada ao pedido certo? |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | :---: |",
    ]
    for cfg in resultados_configs:
        for c in cfg["casos"]:
            t1 = c["turno1"]
            t2 = c["turno2_complementacao"]
            saida_tot = t1["tokens_saida"] + t2["tokens_saida"]
            linhas_md.append(
                f"| {cfg['configuracao']} | {c['numero_pedido']} | {t1['tokens_entrada']} | "
                f"{t2['tokens_entrada']} | {saida_tot} | {c['custo_total_2_turnos_usd']:.5f} | "
                f"{'SIM' if t2['aplicada_ao_pedido_certo'] else 'NÃO'} |"
            )
    (PASTA_RESULTADOS / "medicao_memoria.md").write_text("\n".join(linhas_md) + "\n", encoding="utf-8")

    linhas_txt = [
        "=== TESTE DA ROTINA DE ELIMINAÇÃO LGPD (TABELA POR TABELA) ===",
        "Aviso: a rotina alcança somente o banco de trabalho do agente, não o processo oficial de despesa.",
        "",
    ]
    for el in eliminacoes:
        linhas_txt.append(f"Titular: {el['nome']} (matrícula {el['matricula']})")
        linhas_txt.append(f"  Antes (por tabela): {el['antes']['ocorrencias_por_tabela']} (total={el['antes']['total_ocorrencias']})")
        linhas_txt.append(f"  Após Etapa 1 (sessões por user_id): {el['apos_etapa1_sessoes']['ocorrencias_por_tabela']} (total={el['apos_etapa1_sessoes']['total_ocorrencias']})")
        linhas_txt.append(f"  Após Etapa 2 (delete_user_memories por user_id): {el['apos_etapa2_memorias_por_user_id']['ocorrencias_por_tabela']} (total={el['apos_etapa2_memorias_por_user_id']['total_ocorrencias']})")
        linhas_txt.append(f"  Sessões residuais achadas na varredura: {el['sessoes_residuais_detectadas_na_varredura']}")
        linhas_txt.append(f"  Memórias residuais achadas na varredura: {el['memorias_residuais_detectadas_na_varredura']}")
        linhas_txt.append(f"  Após Etapa 3 (varredura completa): {el['apos_etapa3_varredura_completa']['ocorrencias_por_tabela']} (total={el['apos_etapa3_varredura_completa']['total_ocorrencias']})")
        linhas_txt.append(f"  Eliminação total confirmada: {el['eliminacao_total_confirmada']}")
        linhas_txt.append(f"  Resposta do agente em nova sessão pós-exclusão: {el['verificacao_pos_exclusao_em_nova_sessao']}")
        linhas_txt.append("")
    (PASTA_RESULTADOS / "teste_eliminacao.txt").write_text("\n".join(linhas_txt), encoding="utf-8")
    return payload


if __name__ == "__main__":
    res = executar_experimento_memoria()
    print((PASTA_RESULTADOS / "medicao_memoria.md").read_text(encoding="utf-8"))
    print((PASTA_RESULTADOS / "teste_eliminacao.txt").read_text(encoding="utf-8"))
