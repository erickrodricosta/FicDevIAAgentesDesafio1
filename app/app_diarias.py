"""Formulário de conferência de pedidos de diárias da SEMA-MT (Etapa 5).

Interface Streamlit no padrão da Aula 06:
- Não importa o Agno nem lê chave de API diretamente (usa apenas a fronteira em src/agente.py).
- Mantém um único agente em cache (@st.cache_resource), informando session_id e user_id por chamada.
- Exibe progresso em tempo real via st.status enquanto aguarda a saída estruturada.
- Mantém a minuta em campo editável, registra decisão do conferente + divergências em JSONL,
  permite complementação na mesma sessão e oferece eliminação verificável (LGPD) no banco do agente.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import streamlit as st

from src.agente import criar_agente, executar_eliminacao_no_banco, instruir_pedido
from src.ferramentas import PASTA_BASE, carregar_complementacoes, carregar_pedidos
from src.memoria import (
    carregar_conferencias_humanas,
    inspecionar_banco_titular,
    registrar_conferencia_humana,
)
from src.modelos import ResultadoInstrucao

DB_FORMULARIO = PASTA_BASE / "tmp" / "memoria_formulario.db"

ROTULOS_FERRAMENTAS = {
    "consultar_servidor": "Consultando cadastro funcional do servidor...",
    "consultar_historico_diarias": "Consultando histórico de diárias e prestações de contas...",
    "calcular_diarias": "Calculando antecedência, quantidade, valor e limite mensal...",
    "consultar_saldo_diarias": "Verificando saldo orçamentário da unidade de lotação...",
}

ROTULOS_RECOMENDACAO = {
    "apto_para_autorizacao": "Apto para autorização",
    "diligencia": "Diligência (incompleto ou divergente)",
    "nao_recomendado": "Não recomendado (impedimento normativo)",
}


@st.cache_resource
def agente_em_cache():
    """Mantém um único agente sem session_id nem user_id fixos na construção."""
    DB_FORMULARIO.parent.mkdir(parents=True, exist_ok=True)
    return criar_agente(
        db_file=DB_FORMULARIO,
        parallel_tool_calls=False,
        tool_call_limit=8,
        add_history_to_context=True,
        num_history_runs=6,
        update_memory_on_run=False,
        usar_guardrail_pii=True,
        debug_mode=False,
    )


def _inicializar_estado() -> None:
    st.session_state.setdefault("ultimo_resultado", None)
    st.session_state.setdefault("ultimo_pedido", None)
    st.session_state.setdefault("complementacoes_por_pedido", {})
    st.session_state.setdefault("user_id_sessao_por_pedido", {})


def _renderizar_resultado_instrucao(
    resultado: ResultadoInstrucao,
    pedido: dict[str, Any],
    complementacoes_por_num: dict[str, dict[str, Any]],
) -> None:
    # Em falha de API ou recusa da barreira: exibe somente a mensagem padrão (nada do conteúdo recusado).
    if resultado.erro_api or not resultado.aprovado_barreira or resultado.instrucao is None:
        st.error(resultado.mensagem_padrao or "Pedido encaminhado para análise manual.")
        return

    inst = resultado.instrucao
    st.subheader(f"Instrução do Pedido {inst.numero_pedido}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Recomendação", ROTULOS_RECOMENDACAO.get(inst.recomendacao, inst.recomendacao))
    with col2:
        qtd_txt = f"{inst.quantidade_diarias:.1f}" if inst.quantidade_diarias is not None else "N/A (diligência)"
        st.metric("Diárias", qtd_txt)
    with col3:
        val_txt = f"R$ {inst.valor_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if inst.valor_total is not None else "N/A (diligência)"
        st.metric("Valor total", val_txt)
    with col4:
        st.metric(
            "Autorização superior (§ 2º)",
            "Exige escrita" if inst.exige_autorizacao_superior else "Não exigida",
        )

    if inst.exige_autorizacao_superior:
        st.warning(
            "Pedido com antecedência inferior a 10 dias por urgência: exige autorização expressa e escrita "
            "do Secretário Adjunto registrada no processo (Art. 5º, § 2º)."
        )

    if inst.alertas:
        st.warning("**Alertas ao conferente:**\n" + "\n".join(f"- {a}" for a in inst.alertas))

    if inst.pendencias:
        st.info("**Pendências para diligência:**\n" + "\n".join(f"- {p}" for p in inst.pendencias))

    st.markdown("#### Verificações normativas")
    linhas_verif = [
        {
            "Critério": v.criterio,
            "Situação": v.situacao,
            "Fundamento": v.detalhe,
        }
        for v in inst.verificacoes
    ]
    st.table(linhas_verif)

    with st.expander("Consultas realizadas, argumentos e métricas da execução"):
        st.caption(
            f"Chamadas ao modelo: {resultado.chamadas_modelo} | "
            f"Entrada: {resultado.tokens_entrada} tokens | "
            f"Saída: {resultado.tokens_saida} tokens | "
            f"Custo estimado: US$ {resultado.custo_usd:.5f} | "
            f"Tempo: {resultado.tempo_segundos:.2f} s"
        )
        for i, ch in enumerate(resultado.ferramentas, start=1):
            st.markdown(f"**{i}. `{ch.nome}`** — argumentos: `{ch.argumentos}`")
            if ch.resultado:
                st.text(ch.resultado)

    # Diligência: complementação na mesma sessão
    if inst.recomendacao == "diligencia":
        st.markdown("---")
        st.markdown("#### Complementação em diligência (mesma sessão do pedido)")
        comp_padrao = complementacoes_por_num.get(inst.numero_pedido, {})
        with st.form(f"form_complementacao_{inst.numero_pedido}"):
            texto_comp = st.text_area(
                "Texto da complementação do solicitante",
                value=comp_padrao.get("texto", ""),
                height=100,
                help="A complementação será enviada na mesma sessão para recuperar os dados já informados.",
            )
            enviar_comp = st.form_submit_button("Enviar complementação", type="primary")

        if enviar_comp:
            if not texto_comp.strip():
                st.warning("Informe o texto da complementação antes de enviar.")
            else:
                lista_comps = st.session_state["complementacoes_por_pedido"].setdefault(
                    inst.numero_pedido, []
                )
                lista_comps.append(texto_comp.strip())
                user_id_sessao = st.session_state["user_id_sessao_por_pedido"].get(
                    inst.numero_pedido, str(pedido["matricula"])
                )
                msg_comp = (
                    f"Complementação do pedido {inst.numero_pedido} (enviada em {date.today().isoformat()}):\n"
                    f"{texto_comp.strip()}\n"
                    "Reavalie o pedido completo considerando os dados originais e esta complementação."
                )
                with st.status("Reavaliando pedido com a complementação...", expanded=True) as status:
                    novo_res = instruir_pedido(
                        agente_em_cache(),
                        pedido,
                        complementacoes=lista_comps,
                        session_id=inst.numero_pedido,
                        user_id=user_id_sessao,
                        mensagem_override=msg_comp,
                        ao_chamar_ferramenta=lambda nome: st.write(
                            ROTULOS_FERRAMENTAS.get(nome, f"Executando {nome}...")
                        ),
                    )
                    status.update(
                        label=f"Complementação processada em {novo_res.tempo_segundos:.2f} s",
                        state="complete" if novo_res.aprovado_barreira else "error",
                    )
                st.session_state["ultimo_resultado"] = novo_res
                st.rerun()

    # Lugar físico da conferência humana: minuta editável + decisão do conferente
    st.markdown("---")
    st.markdown("#### Conferência Humana e Minuta de Despacho")
    st.caption(
        "Em cumprimento ao Art. 10 da IN SEMA nº 07/2026, o agente apenas instrui e sugere; "
        "a conferência cabe ao servidor e a decisão ao ordenador de despesa."
    )

    col_sug, col_minuta = st.columns([1, 2])
    with col_sug:
        st.text_input(
            "Encaminhamento sugerido pelo agente",
            value=ROTULOS_RECOMENDACAO.get(inst.recomendacao, inst.recomendacao),
            disabled=True,
        )
        decisao_conferente = st.selectbox(
            "Encaminhamento decidido pelo conferente",
            options=["apto_para_autorizacao", "diligencia", "nao_recomendado"],
            index=["apto_para_autorizacao", "diligencia", "nao_recomendado"].index(inst.recomendacao),
            format_func=lambda k: ROTULOS_RECOMENDACAO.get(k, k),
            key=f"decisao_conf_{inst.numero_pedido}_{len(st.session_state['complementacoes_por_pedido'].get(inst.numero_pedido, []))}",
        )
        divergiu = decisao_conferente != inst.recomendacao
        motivo_divergencia = st.text_area(
            "Motivo da divergência (obrigatório quando divergir do agente)",
            placeholder="Descreva o motivo técnico ou normativo da divergência...",
            height=90,
            key=f"motivo_div_{inst.numero_pedido}",
        )
    with col_minuta:
        minuta_editada = st.text_area(
            "Minuta do despacho (editável pelo servidor antes de baixar/encaminhar)",
            value=inst.minuta_despacho,
            height=240,
            key=f"minuta_edit_{inst.numero_pedido}_{len(st.session_state['complementacoes_por_pedido'].get(inst.numero_pedido, []))}",
        )

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Registrar conferência humana", type="primary"):
            if divergiu and not motivo_divergencia.strip():
                st.error("Informe o motivo da divergência antes de registrar a conferência.")
            else:
                registrar_conferencia_humana(
                    {
                        "numero_pedido": inst.numero_pedido,
                        "matricula": inst.matricula,
                        "sugestao_agente": inst.recomendacao,
                        "decisao_conferente": decisao_conferente,
                        "divergiu": divergiu,
                        "motivo_divergencia": motivo_divergencia.strip(),
                        "minuta_final": minuta_editada,
                    }
                )
                st.success("Conferência humana registrada em resultados/conferencias_humanas.jsonl.")
    with col_btn2:
        st.download_button(
            label="Baixar minuta conferida (.txt)",
            data=minuta_editada,
            file_name=f"despacho_{inst.numero_pedido}.txt",
            mime="text/plain",
        )

    historico_conf = carregar_conferencias_humanas()
    if historico_conf:
        total_c = len(historico_conf)
        div_c = sum(1 for r in historico_conf if r.get("divergiu"))
        taxa = (div_c / total_c) * 100.0
        st.caption(
            f"Histórico de conferências registradas: {total_c} | Divergências: {div_c} ({taxa:.1f}%)"
        )


def main() -> None:
    st.set_page_config(page_title="SEMA-MT — Instrução de Pedidos de Diárias", layout="wide")
    _inicializar_estado()

    st.title("SEMA-MT — Instrução de Pedidos de Diárias")
    st.caption(
        "Coordenadoria de Diárias e Passagens | Instrução Normativa SEMA nº 07/2026 (hipotética) — "
        "O sistema instrui e redige a minuta; a decisão pertence ao ordenador de despesa."
    )

    pedidos_lista = carregar_pedidos()
    pedidos_por_num = {p["numero"]: p for p in pedidos_lista}
    complementacoes_por_num = {c["numero"]: c for c in carregar_complementacoes()}

    aba_instrucao, aba_lgpd = st.tabs(["Instrução e Conferência", "Eliminação de Dados (LGPD)"])

    with aba_instrucao:
        opcoes = ["(Preenchimento manual)"] + [
            f"{p['numero']} — {p['nome']} ({p['destino_municipio']}/{p['destino_uf']})"
            for p in pedidos_lista
        ]
        escolha = st.selectbox("Carregar pedido de exemplo (opcional)", opcoes)
        if escolha == "(Preenchimento manual)":
            chave_form = "manual"
            padrao = {
                "numero": "DIA-2026-9001",
                "data_pedido": "2026-10-09",
                "matricula": "",
                "nome": "",
                "destino_municipio": "",
                "destino_uf": "MT",
                "data_partida": "2026-11-20",
                "data_retorno": "2026-11-22",
                "transporte": "veículo oficial",
                "justificativa": "",
            }
        else:
            num_sel = escolha.split(" — ")[0].strip()
            chave_form = num_sel
            padrao = pedidos_por_num[num_sel]

        with st.form(f"form_pedido_{chave_form}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                numero = st.text_input("Número do pedido", value=str(padrao.get("numero", "")), key=f"num_{chave_form}")
                matricula = st.text_input("Matrícula (6 dígitos)", value=str(padrao.get("matricula", "")), key=f"mat_{chave_form}")
                transporte = st.text_input("Transporte", value=str(padrao.get("transporte", "veículo oficial")), key=f"tr_{chave_form}")
            with c2:
                nome = st.text_input("Nome completo do servidor", value=str(padrao.get("nome", "")), key=f"nome_{chave_form}")
                destino_municipio = st.text_input("Município de destino", value=str(padrao.get("destino_municipio", "")), key=f"mun_{chave_form}")
                destino_uf = st.text_input("UF de destino", value=str(padrao.get("destino_uf", "MT")), key=f"uf_{chave_form}")
            with c3:
                data_pedido = st.text_input("Data do pedido (YYYY-MM-DD)", value=str(padrao.get("data_pedido", "")), key=f"dp_{chave_form}")
                data_partida = st.text_input("Data de partida (YYYY-MM-DD)", value=str(padrao.get("data_partida", "")), key=f"dpart_{chave_form}")
                data_retorno_str = st.text_input(
                    "Data de retorno (YYYY-MM-DD, deixe vazio se ausente)",
                    value=str(padrao.get("data_retorno") or ""),
                    key=f"dret_{chave_form}",
                )

            justificativa = st.text_area("Justificativa do deslocamento", value=str(padrao.get("justificativa", "")), height=110, key=f"just_{chave_form}")
            enviado = st.form_submit_button("Instruir pedido", type="primary")

        if enviado:
            pedido_atual = {
                "numero": numero.strip(),
                "data_pedido": data_pedido.strip(),
                "matricula": matricula.strip(),
                "nome": nome.strip(),
                "destino_municipio": destino_municipio.strip(),
                "destino_uf": destino_uf.strip().upper(),
                "data_partida": data_partida.strip(),
                "data_retorno": data_retorno_str.strip() or None,
                "transporte": transporte.strip(),
                "justificativa": justificativa.strip(),
            }
            st.session_state["complementacoes_por_pedido"][pedido_atual["numero"]] = []
            st.session_state["user_id_sessao_por_pedido"][pedido_atual["numero"]] = pedido_atual["matricula"]

            with st.status("Instruindo pedido...", expanded=True) as status:
                resultado = instruir_pedido(
                    agente_em_cache(),
                    pedido_atual,
                    session_id=pedido_atual["numero"],
                    user_id=pedido_atual["matricula"],
                    ao_chamar_ferramenta=lambda fn: st.write(
                        ROTULOS_FERRAMENTAS.get(fn, f"Executando {fn}...")
                    ),
                )
                status.update(
                    label=f"Instrução concluída em {resultado.tempo_segundos:.2f} s",
                    state="complete" if resultado.aprovado_barreira else "error",
                )
            st.session_state["ultimo_pedido"] = pedido_atual
            st.session_state["ultimo_resultado"] = resultado

        if st.session_state.get("ultimo_resultado") is not None:
            _renderizar_resultado_instrucao(
                st.session_state["ultimo_resultado"],
                st.session_state["ultimo_pedido"],
                complementacoes_por_num,
            )

    with aba_lgpd:
        st.subheader("Eliminação de Dados do Titular no Banco do Agente (LGPD)")
        st.info(
            "Importante: esta rotina alcança somente o banco de trabalho do agente (SQLite). "
            "Os registros oficiais de concessão de diárias constituem despesa pública e permanecem "
            "sujeitos à transparência e aos prazos legais de guarda e prestação de contas."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            mat_lgpd = st.text_input("Matrícula do titular", value="207418")
        with col_b:
            nome_lgpd = st.text_input("Nome completo do titular", value="Carla Regina Souza")

        col_ins, col_del = st.columns(2)
        with col_ins:
            if st.button("Inspecionar banco tabela por tabela"):
                estado = inspecionar_banco_titular(DB_FORMULARIO, mat_lgpd, nome_lgpd)
                st.json(estado)
        with col_del:
            if st.button("Executar eliminação completa", type="primary"):
                rel = executar_eliminacao_no_banco(agente_em_cache(), DB_FORMULARIO, mat_lgpd, nome_lgpd)
                if rel["eliminacao_total_confirmada"]:
                    st.success("Eliminação verificada: 0 ocorrências restantes em todas as tabelas do banco.")
                else:
                    st.error("Ainda restaram registros no banco após a rotina.")
                st.markdown("**Antes da eliminação:**")
                st.json(rel["antes"]["ocorrencias_por_tabela"])
                st.markdown("**Após exclusão padrão por user_id (sessões + memórias):**")
                st.json(rel["apos_etapa2_memorias_por_user_id"]["ocorrencias_por_tabela"])
                st.markdown("**Após varredura completa por matrícula e nome (estado final do banco):**")
                st.json(rel["apos_etapa3_varredura_completa"]["ocorrencias_por_tabela"])


if __name__ == "__main__":
    main()
