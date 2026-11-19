"""Contratos Pydantic e modelos de resultado para a instrução de diárias (Etapa 3)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Verificacao(BaseModel):
    """Resultado individual de um dos seis critérios normativos da IN SEMA nº 07/2026."""

    criterio: Literal[
        "cadastro",
        "dados_completos",
        "antecedencia",
        "prestacao_contas",
        "limite_mensal",
        "saldo_orcamentario",
    ] = Field(description="Identificador exato do critério normativo verificado.")
    situacao: Literal["atende", "nao_atende", "nao_verificado"] = Field(
        description="Situação da verificação: atende, nao_atende ou nao_verificado."
    )
    detalhe: str = Field(
        description="Dado objetivo que fundamenta a situação, como veio da ferramenta ou do pedido."
    )


class Instrucao(BaseModel):
    """Contrato estruturado mínimo da saída do agente para tela e medição."""

    numero_pedido: str = Field(description="Número do pedido protocolado, ex.: DIA-2026-0101.")
    matricula: str = Field(description="Matrícula do solicitante considerada na instrução.")
    quantidade_diarias: Optional[float] = Field(
        description="Quantidade total de diárias calculada pela ferramenta; deve ser nulo na diligência."
    )
    valor_total: Optional[float] = Field(
        description="Valor total em reais calculado pela ferramenta; deve ser nulo na diligência."
    )
    verificacoes: list[Verificacao] = Field(
        description="Lista completa das seis verificações normativas do pedido."
    )
    recomendacao: Literal["apto_para_autorizacao", "diligencia", "nao_recomendado"] = Field(
        description="Recomendação técnica ao ordenador: apto_para_autorizacao, diligencia ou nao_recomendado."
    )
    exige_autorizacao_superior: bool = Field(
        description="True apenas quando houver urgência legítima com antecedência inferior a 10 dias e pedido apto."
    )
    pendencias: list[str] = Field(
        description="Itens que o solicitante precisa corrigir ou complementar em diligência."
    )
    alertas: list[str] = Field(
        description="Alertas ao conferente: ordens embutidas na justificativa, dados pessoais mascarados, ressalvas."
    )
    minuta_despacho: str = Field(
        description="Minuta formal de despacho para conferência humana e submissão ao ordenador de despesa."
    )


class FerramentaConsultada(BaseModel):
    """Registro auditável de uma chamada de ferramenta feita pelo agente."""

    nome: str
    argumentos: dict[str, Any] = Field(default_factory=dict)
    resultado: Optional[str] = None
    erro: bool = False


class ResultadoInstrucao(BaseModel):
    """Envelope retornado pela fronteira instruir_pedido() com telemetria e veredito da barreira."""

    numero_pedido: str
    session_id: str
    user_id: str
    status_execucao: str
    erro_api: bool = False
    aprovado_barreira: bool = False
    motivos_recusa_barreira: list[str] = Field(default_factory=list)
    mensagem_padrao: Optional[str] = None
    instrucao: Optional[Instrucao] = None
    ferramentas: list[FerramentaConsultada] = Field(default_factory=list)
    chamadas_modelo: int = 0
    tokens_entrada_por_chamada: list[int] = Field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_totais: int = 0
    custo_usd: float = 0.0
    tempo_segundos: float = 0.0
    erro_detalhe_interno: Optional[str] = None
