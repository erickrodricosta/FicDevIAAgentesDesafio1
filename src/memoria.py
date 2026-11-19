"""Gestão de persistência, inspeção LGPD, eliminação completa e registro de conferência (Etapas 4 e 5)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from src.ferramentas import PASTA_RESULTADOS

ARQUIVO_CONFERENCIAS = PASTA_RESULTADOS / "conferencias_humanas.jsonl"


def _listar_tabelas(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cur.fetchall()]


def inspecionar_banco_titular(
    db_file: str | Path,
    matricula: str,
    nome: str,
) -> dict[str, Any]:
    """Percorre todas as tabelas do SQLite contando e localizando ocorrências de matrícula ou nome."""
    caminho = Path(db_file)
    mat_limpa = matricula.strip()
    nome_limpo = nome.strip().lower()

    if not caminho.exists():
        return {
            "db_file": str(caminho),
            "matricula": mat_limpa,
            "nome": nome.strip(),
            "tabelas_existentes": [],
            "ocorrencias_por_tabela": {},
            "total_ocorrencias": 0,
            "detalhes_ocorrencias": {},
        }

    ocorrencias: dict[str, int] = {}
    detalhes: dict[str, list[dict[str, Any]]] = {}

    with sqlite3.connect(str(caminho), timeout=10.0) as conn:
        tabelas = _listar_tabelas(conn)
        for tabela in tabelas:
            cur = conn.execute(f'SELECT rowid, * FROM "{tabela}"')
            colunas = [desc[0] for desc in cur.description]
            encontrados: list[dict[str, Any]] = []
            for row in cur.fetchall():
                mapa = dict(zip(colunas, row))
                texto_linha = " ".join(str(v) for v in row[1:] if v is not None)
                tem_mat = bool(mat_limpa) and (mat_limpa in texto_linha)
                tem_nome = bool(nome_limpo) and (nome_limpo in texto_linha.lower())
                if tem_mat or tem_nome:
                    encontrados.append(
                        {
                            "rowid": mapa.get("rowid"),
                            "session_id": mapa.get("session_id"),
                            "user_id": mapa.get("user_id"),
                            "memory_id": mapa.get("memory_id") or mapa.get("id"),
                            "por_matricula": tem_mat,
                            "por_nome": tem_nome,
                        }
                    )
            ocorrencias[tabela] = len(encontrados)
            if encontrados:
                detalhes[tabela] = encontrados

    return {
        "db_file": str(caminho),
        "matricula": mat_limpa,
        "nome": nome.strip(),
        "tabelas_existentes": tabelas,
        "ocorrencias_por_tabela": ocorrencias,
        "total_ocorrencias": sum(ocorrencias.values()),
        "detalhes_ocorrencias": detalhes,
    }


def inspecionar_termos_no_banco(db_file: str | Path, termos: list[str]) -> dict[str, dict[str, int]]:
    """Verifica se qualquer termo sensível (ex.: CPF, conta bancária) aparece nas tabelas do SQLite."""
    caminho = Path(db_file)
    if not caminho.exists():
        return {}

    resultado: dict[str, dict[str, int]] = {}
    with sqlite3.connect(str(caminho), timeout=10.0) as conn:
        for tabela in _listar_tabelas(conn):
            cur = conn.execute(f'SELECT * FROM "{tabela}"')
            linhas = [" ".join(str(c) for c in row if c is not None) for row in cur.fetchall()]
            contagens: dict[str, int] = {}
            for termo in termos:
                qtd = sum(1 for linha in linhas if termo in linha)
                if qtd > 0:
                    contagens[termo] = qtd
            if contagens:
                resultado[tabela] = contagens
    return resultado


def _normalizar_lista_sessoes(resp: Any) -> list[dict[str, Any]]:
    if isinstance(resp, tuple):
        resp = resp[0]
    if not resp:
        return []
    saida = []
    for item in resp:
        if isinstance(item, dict):
            saida.append(item)
        else:
            saida.append({"session_id": getattr(item, "session_id", None)})
    return saida


def _normalizar_lista_memorias(resp: Any) -> list[Any]:
    if isinstance(resp, tuple):
        resp = resp[0]
    return list(resp or [])


def eliminar_dados_titular(
    agente: Optional[Agent],
    db: SqliteDb,
    db_file: str | Path,
    matricula: str,
    nome: str,
) -> dict[str, Any]:
    """Elimina sessões, execuções e memórias do titular no banco do agente e verifica tabela por tabela.

    1) Apaga sessões filtradas pelo `user_id` (matrícula), levando junto as execuções;
    2) Lista e apaga memórias de usuário com `delete_user_memories`;
    3) Confere o banco tabela por tabela procurando matrícula e nome (necessário, por exemplo,
       no caso DIA-2026-0112 em que a sessão foi gravada sob matrícula digitada erroneamente)
       e elimina os registros residuais encontrados até zerar todas as tabelas.
    """
    mat = matricula.strip()
    antes = inspecionar_banco_titular(db_file, mat, nome)

    # Etapa 1: exclusão das sessões pelo user_id do titular
    sessoes_raw = _normalizar_lista_sessoes(db.get_sessions(user_id=mat, deserialize=False))
    sids_user = [s["session_id"] for s in sessoes_raw if s.get("session_id")]
    for sid in sids_user:
        if agente is not None:
            agente.delete_session(sid, user_id=mat)
        else:
            db.delete_session(sid, user_id=mat)
    apos_sessoes = inspecionar_banco_titular(db_file, mat, nome)

    # Etapa 2: listagem e exclusão das memórias via delete_user_memories
    memorias = _normalizar_lista_memorias(db.get_user_memories(user_id=mat, deserialize=True))
    mids_user: list[str] = []
    for m in memorias:
        mid = m.get("memory_id") or m.get("id") if isinstance(m, dict) else (getattr(m, "memory_id", None) or getattr(m, "id", None))
        if mid:
            mids_user.append(str(mid))
    if mids_user:
        db.delete_user_memories(memory_ids=mids_user, user_id=mat)
    apos_memorias = inspecionar_banco_titular(db_file, mat, nome)

    # Etapa 3: varredura tabela por tabela buscando matrícula e nome
    sids_residuais: list[str] = []
    mids_residuais: list[str] = []
    residuos_detectados = apos_memorias["detalhes_ocorrencias"]

    for tabela, itens in residuos_detectados.items():
        for item in itens:
            if item.get("session_id"):
                sid = str(item["session_id"])
                if sid not in sids_residuais:
                    sids_residuais.append(sid)
            if "memor" in tabela.lower() and item.get("memory_id"):
                mid = str(item["memory_id"])
                if mid not in mids_residuais:
                    mids_residuais.append(mid)

    for sid in sids_residuais:
        db.delete_session(session_id=sid, user_id=None)
    if mids_residuais:
        db.delete_user_memories(memory_ids=mids_residuais, user_id=None)

    apos_varredura = inspecionar_banco_titular(db_file, mat, nome)

    # Garantia final por rowid caso alguma tabela auxiliar ainda retenha referência ao titular
    limpeza_sql_residual: dict[str, int] = {}
    if apos_varredura["total_ocorrencias"] > 0 and Path(db_file).exists():
        with sqlite3.connect(str(db_file), timeout=10.0) as conn:
            for tabela, itens in apos_varredura["detalhes_ocorrencias"].items():
                rowids = [item["rowid"] for item in itens if item.get("rowid") is not None]
                if rowids:
                    placeholders = ",".join("?" for _ in rowids)
                    conn.execute(f'DELETE FROM "{tabela}" WHERE rowid IN ({placeholders})', rowids)
                    limpeza_sql_residual[tabela] = len(rowids)
            conn.commit()
        apos_varredura = inspecionar_banco_titular(db_file, mat, nome)

    return {
        "matricula": mat,
        "nome": nome.strip(),
        "sessoes_apagadas_por_user_id": sids_user,
        "memorias_apagadas_por_user_id": mids_user,
        "sessoes_residuais_detectadas_na_varredura": sids_residuais,
        "memorias_residuais_detectadas_na_varredura": mids_residuais,
        "limpeza_sql_residual": limpeza_sql_residual,
        "antes": antes,
        "apos_etapa1_sessoes": apos_sessoes,
        "apos_etapa2_memorias_por_user_id": apos_memorias,
        "apos_etapa3_varredura_completa": apos_varredura,
        "eliminacao_total_confirmada": apos_varredura["total_ocorrencias"] == 0,
    }


def registrar_conferencia_humana(
    registro: dict[str, Any],
    arquivo: Path = ARQUIVO_CONFERENCIAS,
) -> Path:
    """Grava uma conferência humana em resultados/conferencias_humanas.jsonl."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **registro,
    }
    with open(arquivo, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return arquivo


def carregar_conferencias_humanas(arquivo: Path = ARQUIVO_CONFERENCIAS) -> list[dict[str, Any]]:
    """Lê o histórico de conferências humanas registradas."""
    if not arquivo.exists():
        return []
    registros: list[dict[str, Any]] = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            registros.append(json.loads(linha))
    return registros
