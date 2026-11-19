"""Ferramentas de consulta e cálculo sobre os dados da SEMA-MT (Etapa 2).

Implementadas como funções Python puras (sem dependência de framework), com duas
regras de projeto:
1. Minimização de dados pessoais: CPF e e-mail do cadastro nunca são devolvidos ao modelo.
2. Contas no código: prazos, antecedência, quantidade, valor total, soma mensal e saldo
   saem prontos em Python para eliminar erros aritméticos do modelo.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

PASTA_BASE = Path(__file__).resolve().parent.parent
PASTA_DADOS = PASTA_BASE / "dados"
PASTA_RESULTADOS = PASTA_BASE / "resultados"


def _somar_dias_uteis(inicio: date, dias: int) -> date:
    """Soma dias úteis (segunda a sexta), sem considerar feriados."""
    atual = inicio
    restantes = dias
    while restantes > 0:
        atual += timedelta(days=1)
        if atual.weekday() < 5:
            restantes -= 1
    return atual


def _classe_destino(uf: str) -> str:
    uf_norm = uf.strip().upper()
    if uf_norm == "MT":
        return "interior_mt"
    if uf_norm == "DF":
        return "distrito_federal"
    return "outra_uf"


@lru_cache(maxsize=1)
def carregar_tabela_diarias() -> dict[str, Any]:
    """Carrega regras numéricas e valores do Anexo I a partir de tabela_diarias.json."""
    return json.loads((PASTA_DADOS / "tabela_diarias.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def carregar_unidades() -> dict[str, dict[str, Any]]:
    """Carrega unidades e saldos orçamentários a partir de unidades.json."""
    return json.loads((PASTA_DADOS / "unidades.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def carregar_servidores() -> dict[str, dict[str, str]]:
    """Carrega cadastro funcional indexado por matrícula a partir de servidores.csv."""
    with open(PASTA_DADOS / "servidores.csv", newline="", encoding="utf-8") as f:
        return {row["matricula"].strip(): row for row in csv.DictReader(f)}


@lru_cache(maxsize=1)
def carregar_historico() -> list[dict[str, str]]:
    """Carrega histórico de diárias concedidas a partir de historico_diarias.csv."""
    with open(PASTA_DADOS / "historico_diarias.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def carregar_pedidos() -> list[dict[str, Any]]:
    """Carrega a lista de pedidos protocolados de dados/pedidos.json."""
    return json.loads((PASTA_DADOS / "pedidos.json").read_text(encoding="utf-8"))


def carregar_complementacoes() -> list[dict[str, Any]]:
    """Carrega as complementações de diligência de dados/complementacoes.json."""
    return json.loads((PASTA_DADOS / "complementacoes.json").read_text(encoding="utf-8"))


def carregar_normas() -> str:
    """Carrega o texto da Instrução Normativa hipotética de dados/normas.md."""
    return (PASTA_DADOS / "normas.md").read_text(encoding="utf-8")


def consultar_servidor(matricula: str) -> str:
    """Consulta os dados funcionais estritamente necessários de um servidor pela matrícula.

    Use sempre como primeira verificação do pedido, informando `matricula` como string
    de 6 algarismos (ex.: "204317"). Devolve matrícula, nome cadastrado, cargo, grupo da
    tabela de diárias (A, B ou C), sigla e nome da unidade de lotação e município sede,
    omitindo CPF e e-mail por minimização. Compare o nome cadastrado com o nome no
    pedido; se a matrícula não existir ou o nome divergir, interrompa para diligência
    (art. 9º) sem calcular diárias nem consultar saldo.
    """
    mat = matricula.strip()
    servidores = carregar_servidores()
    registro = servidores.get(mat)
    if registro is None:
        return f"Matrícula '{mat}' não localizada no cadastro funcional (art. 9º — diligência)."

    unidades = carregar_unidades()
    sigla_unidade = registro["unidade"].strip().upper()
    nome_unidade = unidades.get(sigla_unidade, {}).get("nome", sigla_unidade)
    return (
        f"Matrícula: {registro['matricula']} | "
        f"Nome cadastrado: {registro['nome']} | "
        f"Cargo: {registro['cargo']} | "
        f"Grupo: {registro['grupo_diaria']} | "
        f"Unidade: {sigla_unidade} ({nome_unidade}) | "
        f"Município sede: {registro['municipio_sede']}."
    )


def consultar_historico_diarias(matricula: str, mes_partida: str) -> str:
    """Consulta prestações de contas pendentes ou vencidas e o total de diárias no mês.

    Use após confirmar que o cadastro do servidor confere com o pedido. Informe
    `matricula` como string de 6 algarismos (ex.: "205882") e `mes_partida` no formato
    "YYYY-MM" referente ao mês civil da data de partida (ex.: "2026-11"). Devolve a
    situação de prestação de contas (distinguindo prestação VENCIDA, que impede nova
    concessão pelo art. 7º, de prestação pendente ainda DENTRO DO PRAZO de 5 dias úteis,
    sem considerar feriados), o total de diárias já concedidas no mês informado e o saldo
    mensal restante até o limite de 10,0 diárias (art. 6º). Não use se o cadastro tiver
    divergência ou se a matrícula não constar do pedido.
    """
    mat = matricula.strip()
    mes = mes_partida.strip()[:7]
    if len(mes) != 7 or mes[4] != "-":
        return f"Formato inválido para mes_partida '{mes_partida}'. Use 'YYYY-MM'."

    tabela = carregar_tabela_diarias()
    data_analise = date.fromisoformat(tabela["data_da_analise"])
    prazo_uteis = int(tabela["prazo_prestacao_dias_uteis"])
    limite_mensal = float(tabela["limite_mensal_diarias"])

    historico = [h for h in carregar_historico() if h["matricula"].strip() == mat]
    vencidas: list[str] = []
    no_prazo: list[str] = []

    for h in historico:
        if h["prestacao_contas"].strip() == "pendente":
            retorno = date.fromisoformat(h["data_retorno"])
            vencimento = _somar_dias_uteis(retorno, prazo_uteis)
            if vencimento < data_analise:
                vencidas.append(
                    f"{h['pedido']} ({h['destino']}, retorno {h['data_retorno']}, "
                    f"prazo de {prazo_uteis} dias úteis venceu em {vencimento.isoformat()}, "
                    f"feriados não considerados, análise em {data_analise.isoformat()})"
                )
            else:
                no_prazo.append(
                    f"{h['pedido']} ({h['destino']}, retorno {h['data_retorno']}, "
                    f"prazo de {prazo_uteis} dias úteis vence em {vencimento.isoformat()}, "
                    f"feriados não considerados, dentro do prazo na análise de {data_analise.isoformat()})"
                )

    concedidas_mes = sum(
        float(h["quantidade"])
        for h in historico
        if h["data_partida"].strip()[:7] == mes
    )
    concedidas_mes = round(concedidas_mes, 2)
    saldo_mensal = round(max(0.0, limite_mensal - concedidas_mes), 2)

    if vencidas:
        status_prest = f"IMPEDITIVA — prestação de contas VENCIDA (art. 7º): {'; '.join(vencidas)}."
    elif no_prazo:
        status_prest = (
            f"REGULAR (sem prestação vencida; pendente DENTRO DO PRAZO não impede concessão, art. 7º): "
            f"{'; '.join(no_prazo)}."
        )
    else:
        status_prest = "REGULAR — nenhuma prestação de contas pendente ou vencida (art. 7º)."

    return (
        f"Matrícula {mat} | Prestação de contas: {status_prest} | "
        f"Diárias já concedidas em {mes}: {concedidas_mes:.1f} de {limite_mensal:.1f} permitidas "
        f"(saldo mensal restante antes deste pedido: {saldo_mensal:.1f} diária(s), art. 6º)."
    )


def calcular_diarias(
    grupo: str,
    destino_uf: str,
    data_pedido: str,
    data_partida: str,
    data_retorno: str,
    diarias_ja_concedidas_mes: float = 0.0,
) -> str:
    """Calcula em código antecedência, quantidade de diárias, valor total e soma mensal.

    Use somente depois de consultar o cadastro e o histórico, e apenas quando todas as
    datas estiverem presentes no pedido ou na complementação. NÃO use quando faltar
    data de retorno ou houver divergência de cadastro (art. 9º). Argumentos: `grupo`
    ("A", "B" ou "C" devolvido pelo cadastro), `destino_uf` (sigla de 2 letras da UF,
    como "MT", "DF" ou "RO"), `data_pedido`, `data_partida` e `data_retorno` no formato
    ISO "YYYY-MM-DD", e `diarias_ja_concedidas_mes` (número decimal retornado pelo
    histórico, ex.: 8.0). Devolve antecedência em dias corridos, quantidade de diárias,
    valor unitário, valor total em reais e soma total do mês frente ao limite de 10,0.
    """
    grupo_norm = grupo.strip().upper()
    tabela = carregar_tabela_diarias()
    if grupo_norm not in tabela["valores"]:
        return f"Grupo '{grupo}' inválido. Valores aceitos: A, B ou C."

    try:
        dt_pedido = date.fromisoformat(data_pedido.strip())
        dt_partida = date.fromisoformat(data_partida.strip())
        dt_retorno = date.fromisoformat(data_retorno.strip())
    except ValueError as exc:
        return f"Data inválida (use YYYY-MM-DD): {exc}."

    if dt_retorno < dt_partida:
        return "Inconsistência: data_retorno anterior a data_partida."

    antecedencia = (dt_partida - dt_pedido).days
    ant_min = int(tabela["antecedencia_minima_dias"])
    if antecedencia >= ant_min:
        status_ant = f"atende ao mínimo de {ant_min} dias corridos (art. 5º)"
    else:
        status_ant = (
            f"INFERIOR ao mínimo de {ant_min} dias corridos (art. 5º): exige situação "
            "emergencial legítima (§ 1º) E autorização expressa e escrita do Secretário Adjunto (§ 2º)"
        )

    pernoites = (dt_retorno - dt_partida).days
    qtd = 0.5 if pernoites == 0 else pernoites + 0.5
    classe = _classe_destino(destino_uf)
    valor_unit = float(tabela["valores"][grupo_norm][classe])
    valor_total = round(qtd * valor_unit, 2)

    limite_mensal = float(tabela["limite_mensal_diarias"])
    ja_usadas = round(float(diarias_ja_concedidas_mes), 2)
    total_mes = round(ja_usadas + qtd, 2)
    status_limite = (
        f"atende ao limite mensal de {limite_mensal:.1f} diárias (art. 6º)"
        if total_mes <= limite_mensal
        else f"EXCEDE o limite mensal de {limite_mensal:.1f} diárias (art. 6º)"
    )

    return (
        f"Antecedência: {antecedencia} dia(s) corrido(s) — {status_ant}. | "
        f"Pernoites: {pernoites} | Quantidade de diárias: {qtd:.1f} (art. 4º). | "
        f"Classe do destino: {classe} (UF={destino_uf.strip().upper()}) | "
        f"Valor unitário (Grupo {grupo_norm}): R$ {valor_unit:.2f} | "
        f"Valor total: R$ {valor_total:.2f} (art. 3º/Anexo I). | "
        f"Acumulado no mês: {ja_usadas:.1f} + {qtd:.1f} = {total_mes:.1f} diária(s) — {status_limite}."
    )


def consultar_saldo_diarias(unidade: str, valor: float) -> str:
    """Consulta o saldo da dotação de diárias de uma unidade e o compara com o valor pedido.

    Use depois de calcular o valor total das diárias. NÃO use em casos de diligência ou
    antes de `calcular_diarias`. `unidade` é a sigla da unidade de lotação devolvida pelo
    cadastro, como CFF ou GAB; `valor` é o total em reais, com ponto decimal, como 980.0.
    Devolve o saldo disponível em reais e a indicação de saldo suficiente ou INSUFICIENTE
    para o pedido (art. 8º).
    """
    sigla = unidade.strip().upper()
    unidades = carregar_unidades()
    if sigla not in unidades:
        return f"Unidade '{unidade}' não localizada. Siglas válidas: {', '.join(unidades)}."
    saldo = float(unidades[sigla]["saldo_diarias"])
    valor_num = float(valor)
    situacao = "suficiente" if saldo >= valor_num else "INSUFICIENTE"
    return f"Saldo da unidade {sigla}: R$ {saldo:.2f}. Saldo {situacao} para R$ {valor_num:.2f} (art. 8º)."


FERRAMENTAS = [
    consultar_servidor,
    consultar_historico_diarias,
    calcular_diarias,
    consultar_saldo_diarias,
]


def executar_testes_sem_agente() -> str:
    """Executa bateria de testes isolados sem agente e sem chave de API."""
    servidores = carregar_servidores()
    linhas: list[str] = []
    linhas.append("=== TESTE ISOLADO DAS FERRAMENTAS (SEM AGENTE E SEM CHAVE) ===")
    linhas.append("")
    linhas.append("1) Primeira linha das docstrings (especificação recebida pelo modelo):")
    for fn in FERRAMENTAS:
        primeira_linha = (fn.__doc__ or "").strip().splitlines()[0]
        linhas.append(f"  - {fn.__name__}: {primeira_linha}")
        assert fn.__doc__ and len(fn.__doc__.strip()) > 60, f"Docstring curta em {fn.__name__}"

    linhas.append("")
    linhas.append("2) Verificação de minimização (CPF e e-mail nunca saem no retorno) e casos dos pedidos:")

    # Caso 1: DIA-2026-0112 — matrícula trocada (207481 pertence a Rafael; Carla é 207418)
    res_0112_errada = consultar_servidor("207481")
    res_0112_certa = consultar_servidor("207418")
    for mat, res in [("207481", res_0112_errada), ("207418", res_0112_certa)]:
        reg = servidores[mat]
        assert reg["cpf"] not in res, "VAZAMENTO: CPF retornado pela ferramenta!"
        assert reg["email"] not in res, "VAZAMENTO: e-mail retornado pela ferramenta!"
    assert "Rafael Lima Antunes" in res_0112_errada
    assert "Carla Regina Souza" in res_0112_certa
    linhas.append(f"  [DIA-2026-0112 matrícula trocada 207481] -> {res_0112_errada}")
    linhas.append(f"  [DIA-2026-0112 matrícula correta 207418] -> {res_0112_certa}")

    # Caso 2: DIA-2026-0108 — prestação de contas vencida (203648)
    res_0108 = consultar_historico_diarias("203648", "2026-11")
    assert "VENCIDA" in res_0108 and "IMPEDITIVA" in res_0108
    linhas.append(f"  [DIA-2026-0108 prestação vencida]        -> {res_0108}")

    # Caso 3: DIA-2026-0102 — prestação pendente dentro do prazo (205882)
    res_0102 = consultar_historico_diarias("205882", "2026-11")
    assert "DENTRO DO PRAZO" in res_0102 and "REGULAR" in res_0102
    linhas.append(f"  [DIA-2026-0102 pendente no prazo]        -> {res_0102}")

    # Caso 4: DIA-2026-0103 — meia diária sem pernoite (Grupo B, MT, 2026-11-05 a 2026-11-05)
    res_0103 = calcular_diarias("B", "MT", "2026-10-07", "2026-11-05", "2026-11-05", 0.0)
    assert "0.5" in res_0103 and "R$ 140.00" in res_0103
    linhas.append(f"  [DIA-2026-0103 meia diária]              -> {res_0103}")

    # Caso 5: DIA-2026-0110 — saldo insuficiente na CRH (R$ 640,00 < R$ 1.800,00)
    calc_0110 = calcular_diarias("B", "RO", "2026-10-02", "2026-11-10", "2026-11-14", 0.0)
    res_0110 = consultar_saldo_diarias("CRH", 1800.0)
    assert "R$ 1800.00" in calc_0110 and "INSUFICIENTE" in res_0110
    linhas.append(f"  [DIA-2026-0110 cálculo RO]               -> {calc_0110}")
    linhas.append(f"  [DIA-2026-0110 saldo CRH]                -> {res_0110}")

    # Caso 6: DIA-2026-0109 — limite mensal excedido (8.0 + 3.5 = 11.5 > 10.0)
    hist_0109 = consultar_historico_diarias("208114", "2026-11")
    calc_0109 = calcular_diarias("B", "MT", "2026-10-06", "2026-11-23", "2026-11-26", 8.0)
    assert "8.0" in hist_0109 and "11.5" in calc_0109 and "EXCEDE" in calc_0109
    linhas.append(f"  [DIA-2026-0109 histórico nov]            -> {hist_0109}")
    linhas.append(f"  [DIA-2026-0109 cálculo limite mensal]    -> {calc_0109}")

    # Caso 7: DIA-2026-0104 — Grupo A, DF, 2.5 diárias = R$ 1.500,00
    calc_0104 = calcular_diarias("A", "DF", "2026-10-06", "2026-11-16", "2026-11-18", 0.0)
    assert "R$ 1500.00" in calc_0104
    linhas.append(f"  [DIA-2026-0104 cálculo DF Grupo A]       -> {calc_0104}")

    # Caso 8: DIA-2026-0105 / 0106 — antecedência < 10 dias
    calc_0106 = calcular_diarias("B", "MT", "2026-10-09", "2026-10-10", "2026-10-14", 0.0)
    assert "1 dia(s)" in calc_0106 and "INFERIOR ao mínimo" in calc_0106
    linhas.append(f"  [DIA-2026-0106 antecedência 1 dia]       -> {calc_0106}")

    linhas.append("")
    linhas.append("Todos os asserts de minimização e cálculo em código passaram com sucesso.")
    relatorio = "\n".join(linhas) + "\n"

    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    (PASTA_RESULTADOS / "teste_ferramentas.txt").write_text(relatorio, encoding="utf-8")
    return relatorio


if __name__ == "__main__":
    print(executar_testes_sem_agente())
