"""Barreiras em código e filtro de dados pessoais (Etapa 3).

Implementa:
1. Filtro PII (PIIDetectionGuardrail) com padrões norte-americanos desligados e
   expressões regulares brasileiras para CPF (máscara válida, sem validar dígitos
   verificadores) e conta/agência bancária, preservando matrícula, datas e nº do pedido.
2. Barreira determinística pós-execução que confere todos os argumentos passados às
   ferramentas e os valores devolvidos na Instrucao contra o pedido/complementação e os
   retornos reais das ferramentas.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from agno.guardrails import PIIDetectionGuardrail

from src.ferramentas import carregar_servidores
from src.modelos import FerramentaConsultada, Instrucao

MENSAGEM_PADRAO_ERRO = (
    "Não foi possível concluir a instrução automática deste pedido com segurança. "
    "O processo foi encaminhado para análise manual pela Coordenadoria de Diárias e Passagens."
)

CRITERIOS_OBRIGATORIOS = (
    "cadastro",
    "dados_completos",
    "antecedencia",
    "prestacao_contas",
    "limite_mensal",
    "saldo_orcamentario",
)

# Um padrão para CPF (máscara válida, sem validar dígito verificador)
# e um padrão para conta e agência bancária (preservando datas YYYY-MM-DD,
# matrículas de 6 dígitos e números de pedido DIA-2026-XXXX).
PADROES_PII_BR: dict[str, str] = {
    "CPF": r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
    "CONTA_E_AGENCIA": (
        r"(?i)(?:"
        r"\b(?:conta(?:\s+(?:corrente|poupan[cç]a|banc[aá]ria))?|c/?c\.?|ag[eê]ncia|ag\.?)"
        r"\s*(?:n[º°o.]?\s*)?:?\s*\d{3,12}(?:-[\dXx])?\b"
        r"|\b\d{4,12}-[\dXx]\b"
        r")"
    ),
}


def criar_guardrail_pii() -> PIIDetectionGuardrail:
    """Cria o PIIDetectionGuardrail configurado apenas para CPF e conta/agência brasileiros."""
    return PIIDetectionGuardrail(
        mask_pii=True,
        enable_ssn_check=False,
        enable_credit_card_check=False,
        enable_email_check=False,
        enable_phone_check=False,
        custom_patterns=PADROES_PII_BR,
    )


def mascarar_pii_texto(texto: str) -> str:
    """Aplica exatamente as mesmas máscaras de PADROES_PII_BR em um texto qualquer."""
    resultado = texto
    for padrao in PADROES_PII_BR.values():
        regex = re.compile(padrao)
        resultado = regex.sub(lambda m: "*" * len(m.group(0)), resultado)
    return resultado


def _extrair_matriculas_e_datas(
    pedido: dict[str, Any],
    complementacoes: Optional[list[str]] = None,
) -> tuple[set[str], set[str], set[str]]:
    """Extrai o conjunto fechado de matrículas, datas e meses presentes no pedido/complementação."""
    matriculas: set[str] = set()
    datas: set[str] = set()

    mat_pedido = str(pedido.get("matricula") or "").strip()
    if mat_pedido:
        matriculas.add(mat_pedido)

    for campo in ("data_pedido", "data_partida", "data_retorno"):
        valor = pedido.get(campo)
        if valor:
            datas.add(str(valor).strip())

    for texto in complementacoes or []:
        for m in re.findall(r"\b\d{6}\b", texto):
            matriculas.add(m)
        for d in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", texto):
            datas.add(d)
        for d_br in re.findall(r"\b(\d{2})/(\d{2})/(\d{4})\b", texto):
            datas.add(f"{d_br[2]}-{d_br[1]}-{d_br[0]}")

    meses = {d[:7] for d in datas if len(d) >= 7}
    return matriculas, datas, meses


def _extrair_campos_servidor(resultado: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    m_nome = re.search(r"Nome cadastrado:\s*([^|]+?)\s*\|", resultado)
    m_grupo = re.search(r"Grupo:\s*([ABC])\s*\|", resultado)
    m_unidade = re.search(r"Unidade:\s*([A-Z]{2,5})\b", resultado)
    return (
        m_nome.group(1).strip() if m_nome else None,
        m_grupo.group(1).strip() if m_grupo else None,
        m_unidade.group(1).strip() if m_unidade else None,
    )


def _extrair_valores_calculo(resultado: str) -> tuple[Optional[float], Optional[float]]:
    m_qtd = re.search(r"Quantidade de diárias:\s*(\d+(?:\.\d+)?)", resultado)
    m_val = re.search(r"Valor total:\s*R\$\s*(\d+(?:\.\d+)?)", resultado)
    return (
        float(m_qtd.group(1)) if m_qtd else None,
        float(m_val.group(1)) if m_val else None,
    )


def validar_execucao(
    pedido: dict[str, Any],
    complementacoes: Optional[list[str]],
    ferramentas: list[FerramentaConsultada],
    instrucao: Instrucao,
) -> tuple[bool, list[str]]:
    """Confere em código os argumentos das ferramentas e a coerência da Instrucao.

    Garante que nenhuma matrícula, data ou valor inventado pelo modelo chegue ao
    servidor conferente.
    """
    motivos: list[str] = []
    matriculas_aut, datas_aut, meses_aut = _extrair_matriculas_e_datas(pedido, complementacoes)

    numero_pedido = str(pedido.get("numero", "")).strip()
    if instrucao.numero_pedido.strip() != numero_pedido:
        motivos.append(
            f"numero_pedido divergente: esperado '{numero_pedido}', obtido '{instrucao.numero_pedido}'."
        )

    mat_instrucao = instrucao.matricula.strip()
    if mat_instrucao not in matriculas_aut:
        motivos.append(
            f"Matrícula '{mat_instrucao}' na instrução não consta do pedido nem da complementação."
        )

    criterios_presentes = {v.criterio for v in instrucao.verificacoes}
    faltantes = [c for c in CRITERIOS_OBRIGATORIOS if c not in criterios_presentes]
    if faltantes:
        motivos.append(f"Critérios obrigatórios ausentes em verificacoes: {', '.join(faltantes)}.")

    # Rastreamento do que foi passado e devolvido pelas ferramentas nesta execução
    chamadas_por_nome: dict[str, list[FerramentaConsultada]] = {}
    grupo_cadastro: Optional[str] = None
    unidade_cadastro: Optional[str] = None
    nome_cadastro: Optional[str] = None
    mat_cadastro: Optional[str] = None
    qtd_calculada: Optional[float] = None
    valor_calculado: Optional[float] = None

    for ch in ferramentas:
        chamadas_por_nome.setdefault(ch.nome, []).append(ch)
        args = ch.argumentos or {}
        res = ch.resultado or ""

        if ch.nome == "consultar_servidor":
            mat_arg = str(args.get("matricula", "")).strip()
            if mat_arg not in matriculas_aut:
                motivos.append(
                    f"consultar_servidor recebeu matrícula '{mat_arg}' fora do pedido/complementação."
                )
            nome_res, grupo_res, unid_res = _extrair_campos_servidor(res)
            if nome_res:
                mat_cadastro = mat_arg
                nome_cadastro = nome_res
                grupo_cadastro = grupo_res
                unidade_cadastro = unid_res

        elif ch.nome == "consultar_historico_diarias":
            mat_arg = str(args.get("matricula", "")).strip()
            mes_arg = str(args.get("mes_partida", "")).strip()[:7]
            if mat_arg not in matriculas_aut:
                motivos.append(
                    f"consultar_historico_diarias recebeu matrícula '{mat_arg}' fora do pedido/complementação."
                )
            if mes_arg not in meses_aut:
                motivos.append(
                    f"consultar_historico_diarias recebeu mês '{mes_arg}' não autorizado pelo pedido."
                )

        elif ch.nome == "calcular_diarias":
            for campo_data in ("data_pedido", "data_partida", "data_retorno"):
                val_data = str(args.get(campo_data, "")).strip()
                if val_data not in datas_aut:
                    motivos.append(
                        f"calcular_diarias recebeu {campo_data}='{val_data}' fora do pedido/complementação."
                    )
            data_part_pedido = str(pedido.get("data_partida") or "").strip()
            data_ped_pedido = str(pedido.get("data_pedido") or "").strip()
            if str(args.get("data_pedido", "")).strip() != data_ped_pedido:
                motivos.append("calcular_diarias recebeu data_pedido diferente da do pedido.")
            if str(args.get("data_partida", "")).strip() != data_part_pedido:
                motivos.append("calcular_diarias recebeu data_partida diferente da do pedido.")

            # Se nem o pedido nem a complementação informaram data_retorno (ex.: só há data_pedido e data_partida),
            # não pode existir cálculo com data de retorno igual à de partida se o pedido original tinha retorno nulo sem complementação.
            if not pedido.get("data_retorno") and len(datas_aut) <= 2:
                motivos.append(
                    "calcular_diarias foi chamada sem que haja data_retorno no pedido nem na complementação."
                )

            uf_arg = str(args.get("destino_uf", "")).strip().upper()
            uf_ped = str(pedido.get("destino_uf", "")).strip().upper()
            if uf_arg != uf_ped:
                motivos.append(f"calcular_diarias recebeu destino_uf='{uf_arg}' diferente de '{uf_ped}'.")

            grupo_arg = str(args.get("grupo", "")).strip().upper()
            if grupo_cadastro and grupo_arg != grupo_cadastro:
                motivos.append(
                    f"calcular_diarias recebeu grupo='{grupo_arg}', divergente do cadastro ('{grupo_cadastro}')."
                )

            q, v = _extrair_valores_calculo(res)
            if q is not None and v is not None:
                qtd_calculada = q
                valor_calculado = v

        elif ch.nome == "consultar_saldo_diarias":
            unid_arg = str(args.get("unidade", "")).strip().upper()
            if unidade_cadastro and unid_arg != unidade_cadastro:
                motivos.append(
                    f"consultar_saldo_diarias recebeu unidade='{unid_arg}', divergente do cadastro ('{unidade_cadastro}')."
                )
            try:
                val_arg = float(args.get("valor"))
            except (TypeError, ValueError):
                val_arg = None
                motivos.append("consultar_saldo_diarias recebeu valor inválido.")
            if val_arg is not None and valor_calculado is not None:
                if abs(val_arg - valor_calculado) > 0.01:
                    motivos.append(
                        f"consultar_saldo_diarias recebeu valor={val_arg:.2f}, divergente do calculado ({valor_calculado:.2f})."
                    )

    # Regras estruturais específicas por recomendação
    if instrucao.recomendacao == "diligencia":
        if instrucao.quantidade_diarias is not None or instrucao.valor_total is not None:
            motivos.append(
                "Instrução em diligência deve manter quantidade_diarias=None e valor_total=None."
            )
    else:
        # Em caso de mérito (apto_para_autorizacao ou nao_recomendado), exige-se análise completa
        obrigatorias_agora = ("consultar_historico_diarias", "calcular_diarias", "consultar_saldo_diarias")
        for nome_tool in obrigatorias_agora:
            if nome_tool not in chamadas_por_nome:
                motivos.append(f"Ferramenta obrigatória '{nome_tool}' não foi chamada antes do mérito.")

        if "consultar_servidor" not in chamadas_por_nome and not complementacoes:
            motivos.append("Ferramenta obrigatória 'consultar_servidor' não foi chamada.")

        # Confere no cadastro oficial que a matrícula da instrução realmente pertence ao nome do pedido
        servidores = carregar_servidores()
        reg_servidor = servidores.get(mat_instrucao)
        nome_pedido = str(pedido.get("nome", "")).strip()
        if reg_servidor is None or reg_servidor["nome"].strip() != nome_pedido:
            motivos.append(
                f"Instrução de mérito emitida para matrícula '{mat_instrucao}' cujo titular cadastrado "
                f"diverge de '{nome_pedido}'."
            )
        elif mat_cadastro and mat_cadastro != mat_instrucao:
            motivos.append(
                f"Matrícula consultada no cadastro ('{mat_cadastro}') difere da instrução ('{mat_instrucao}')."
            )
        elif nome_cadastro and nome_cadastro != nome_pedido:
            motivos.append(
                f"Nome devolvido pelo cadastro ('{nome_cadastro}') diverge do pedido ('{nome_pedido}')."
            )
        elif reg_servidor is not None:
            # Se consultar_servidor veio do turno anterior (complementação sem reconsulta), garante consistência de grupo/unidade
            grupo_esperado = reg_servidor["grupo_diaria"].strip().upper()
            unidade_esperada = reg_servidor["unidade"].strip().upper()
            for ch in chamadas_por_nome.get("calcular_diarias", []):
                g = str((ch.argumentos or {}).get("grupo", "")).strip().upper()
                if g != grupo_esperado:
                    motivos.append(f"calcular_diarias usou grupo='{g}', esperado '{grupo_esperado}'.")
            for ch in chamadas_por_nome.get("consultar_saldo_diarias", []):
                u = str((ch.argumentos or {}).get("unidade", "")).strip().upper()
                if u != unidade_esperada:
                    motivos.append(f"consultar_saldo_diarias usou unidade='{u}', esperada '{unidade_esperada}'.")

        if instrucao.quantidade_diarias is None or instrucao.valor_total is None:
            motivos.append("Instrução de mérito deve informar quantidade_diarias e valor_total.")
        else:
            if qtd_calculada is None or abs(float(instrucao.quantidade_diarias) - qtd_calculada) > 0.01:
                motivos.append(
                    f"quantidade_diarias ({instrucao.quantidade_diarias}) não está ancorada no cálculo ({qtd_calculada})."
                )
            if valor_calculado is None or abs(float(instrucao.valor_total) - valor_calculado) > 0.01:
                motivos.append(
                    f"valor_total ({instrucao.valor_total}) não está ancorado no cálculo ({valor_calculado})."
                )

    if instrucao.recomendacao == "apto_para_autorizacao":
        nao_atende = [v.criterio for v in instrucao.verificacoes if v.situacao == "nao_atende"]
        if nao_atende:
            motivos.append(
                f"Recomendação 'apto_para_autorizacao' incompatível com critérios nao_atende: {', '.join(nao_atende)}."
            )

    return (len(motivos) == 0), motivos
