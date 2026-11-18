"""Agente organizador de tarefas no Trello, feito com o Google ADK + Gemini.

Cada função Python abaixo vira uma ferramenta (tool) do agente. O Gemini lê o
nome, a docstring e os parâmetros de cada função para decidir qual chamar.
"""

import os
import unicodedata
from datetime import datetime, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google.adk.agents import Agent
from trello import TrelloClient

load_dotenv()

# Nome do quadro no Trello. Se o seu quadro tiver outro nome, troque no .env.
NOME_QUADRO = os.getenv("TRELLO_BOARD_NAME", "DIO")
# Fuso usado para as datas (o Trello guarda tudo em UTC).
FUSO = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))

# Cada status aceito pelo agente e os nomes de lista que ele pode ter no quadro.
LISTAS_POR_STATUS = {
    "a fazer": ["a fazer", "to do", "todo"],
    "em andamento": ["em andamento", "doing", "fazendo"],
    "concluido": ["concluido", "done", "feito", "finalizado"],
}

# Variações que o usuário (ou o modelo) pode escrever para cada status.
SINONIMOS_STATUS = {
    "a fazer": "a fazer", "afazer": "a fazer", "to do": "a fazer", "todo": "a fazer",
    "pendente": "a fazer", "nao iniciado": "a fazer",
    "em andamento": "em andamento", "andamento": "em andamento", "doing": "em andamento",
    "fazendo": "em andamento", "em progresso": "em andamento", "iniciado": "em andamento",
    "concluido": "concluido", "concluida": "concluido", "done": "concluido",
    "feito": "concluido", "feita": "concluido", "finalizado": "concluido",
    "finalizada": "concluido", "pronto": "concluido", "pronta": "concluido",
    "terminado": "concluido", "terminada": "concluido",
}


# ---------------------------------------------------------------------------
# Funções auxiliares (não são ferramentas do agente)
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem espaços extras: 'Concluído ' -> 'concluido'."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().replace("_", " ").replace("-", " ").split())


def _status_canonico(status: str) -> str | None:
    """Converte qualquer variação de status em 'a fazer', 'em andamento' ou 'concluido'."""
    return SINONIMOS_STATUS.get(_normalizar(status))


def _conectar_quadro():
    """Abre a conexão com o Trello e devolve o quadro configurado.

    Antes, cada ferramenta repetia esse código; agora ele fica num lugar só.
    """
    client = TrelloClient(
        api_key=os.getenv("TRELLO_API_KEY"),
        api_secret=os.getenv("TRELLO_API_SECRET"),
        token=os.getenv("TRELLO_TOKEN"),
    )
    for quadro in client.list_boards():
        if _normalizar(quadro.name) == _normalizar(NOME_QUADRO):
            return quadro
    raise LookupError(f"Quadro '{NOME_QUADRO}' não encontrado no Trello.")


def _lista_do_status(quadro, status: str):
    """Encontra a lista do quadro que corresponde ao status canônico."""
    nomes_aceitos = LISTAS_POR_STATUS[status]
    for lista in quadro.list_lists():
        if _normalizar(lista.name) in nomes_aceitos:
            return lista
    raise LookupError(f"Lista para o status '{status}' não encontrada no quadro.")


def _nome_status_da_lista(nome_lista: str) -> str:
    for status, nomes in LISTAS_POR_STATUS.items():
        if _normalizar(nome_lista) in nomes:
            return status
    return nome_lista


def _data_para_trello(data: str) -> str:
    """Converte a data informada para o formato ISO com fuso horário.

    Correção do 'dia a menos': quando se manda só '2026-11-18', o Trello entende
    meia-noite em UTC, que no Brasil (UTC-3) ainda é dia 17 às 21h. Aqui a data
    vira 18/11 às 12:00 no fuso local, com o deslocamento explícito, então o
    card mostra o dia certo.
    """
    texto = (data or "").strip()
    formatos_data = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")
    formatos_data_hora = ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M")

    for formato in formatos_data_hora:
        try:
            momento = datetime.strptime(texto, formato).replace(tzinfo=FUSO)
            return momento.isoformat()
        except ValueError:
            pass
    for formato in formatos_data:
        try:
            dia = datetime.strptime(texto, formato).date()
            return datetime.combine(dia, time(12, 0), tzinfo=FUSO).isoformat()
        except ValueError:
            pass
    raise ValueError(
        f"Data '{data}' em formato não reconhecido. Use AAAA-MM-DD ou DD/MM/AAAA."
    )


def _data_legivel(due) -> str:
    """Mostra a data de vencimento do card no fuso local, como DD/MM/AAAA."""
    if not due:
        return "sem data"
    try:
        momento = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
        return momento.astimezone(FUSO).strftime("%d/%m/%Y")
    except ValueError:
        return str(due)


def _buscar_card(quadro, nome_tarefa: str):
    """Procura um card pelo nome (ignora maiúsculas e acentos)."""
    alvo = _normalizar(nome_tarefa)
    cards = quadro.open_cards()
    for card in cards:
        if _normalizar(card.name) == alvo:
            return card
    parecidos = [c for c in cards if alvo in _normalizar(c.name)]
    if len(parecidos) == 1:
        return parecidos[0]
    return None


# ---------------------------------------------------------------------------
# Ferramentas do agente
# ---------------------------------------------------------------------------

def get_temporal_context() -> dict:
    """Retorna a data e a hora atuais. Use no início da conversa e sempre que
    precisar saber qual é 'hoje' ou 'amanhã'."""
    agora = datetime.now(FUSO)
    return {
        "status": "sucesso",
        "data_hora": agora.strftime("%d/%m/%Y %H:%M:%S"),
        "data_iso": agora.strftime("%Y-%m-%d"),
        "dia_da_semana": ["segunda", "terça", "quarta", "quinta", "sexta",
                          "sábado", "domingo"][agora.weekday()],
    }


def adicionar_tarefa(nome_tarefa: str, descricao: str, data_entrega: str) -> dict:
    """Cria um card na lista 'A fazer' do quadro do Trello.

    Args:
        nome_tarefa: título curto da tarefa.
        descricao: detalhes da tarefa.
        data_entrega: data de entrega no formato AAAA-MM-DD (ou DD/MM/AAAA).
    """
    try:
        quadro = _conectar_quadro()
        lista = _lista_do_status(quadro, "a fazer")
        due = _data_para_trello(data_entrega)
        card = lista.add_card(name=nome_tarefa, desc=descricao, due=due)
        return {
            "status": "sucesso",
            "mensagem": f"Tarefa '{card.name}' criada em '{lista.name}' "
                        f"para {_data_legivel(due)}.",
        }
    except Exception as erro:
        return {"status": "erro", "mensagem": f"Não consegui criar a tarefa: {erro}"}


def listar_tarefas(status: str = "todas") -> dict:
    """Lista as tarefas do quadro.

    Args:
        status: 'todas' (padrão), 'a fazer', 'em andamento' ou 'concluido'.
            Aceita variações como 'concluído', 'feito', 'doing', 'pendente'.
    """
    try:
        quadro = _conectar_quadro()
        if _normalizar(status) in ("", "todas", "todos", "tudo", "all"):
            listas = quadro.list_lists()
        else:
            canonico = _status_canonico(status)
            if canonico is None:
                return {
                    "status": "erro",
                    "mensagem": f"Status '{status}' inválido. Use 'a fazer', "
                                "'em andamento' ou 'concluido'.",
                }
            listas = [_lista_do_status(quadro, canonico)]

        tarefas = []
        for lista in listas:
            for card in lista.list_cards():
                tarefas.append({
                    "nome": card.name,
                    "descricao": card.desc,
                    "data_entrega": _data_legivel(card.due),
                    "status": _nome_status_da_lista(lista.name),
                })
        return {"status": "sucesso", "total": len(tarefas), "tarefas": tarefas}
    except Exception as erro:
        return {"status": "erro", "mensagem": f"Não consegui listar as tarefas: {erro}"}


def mudar_status_tarefa(nome_tarefa: str, novo_status: str) -> dict:
    """Move o card de uma tarefa para outra lista do quadro.

    Args:
        nome_tarefa: nome da tarefa (como aparece no card).
        novo_status: 'a fazer', 'em andamento' ou 'concluido'. Aceita
            variações como 'concluído', 'feito', 'fazendo', 'doing'.
    """
    try:
        canonico = _status_canonico(novo_status)
        if canonico is None:
            return {
                "status": "erro",
                "mensagem": f"Status '{novo_status}' inválido. Use 'a fazer', "
                            "'em andamento' ou 'concluido'.",
            }
        quadro = _conectar_quadro()
        card = _buscar_card(quadro, nome_tarefa)
        if card is None:
            return {"status": "erro",
                    "mensagem": f"Tarefa '{nome_tarefa}' não encontrada no quadro."}
        destino = _lista_do_status(quadro, canonico)
        card.change_list(destino.id)
        return {"status": "sucesso",
                "mensagem": f"Tarefa '{card.name}' movida para '{destino.name}'."}
    except Exception as erro:
        return {"status": "erro", "mensagem": f"Não consegui mudar o status: {erro}"}


def remover_tarefa(nome_tarefa: str) -> dict:
    """Remove (apaga) o card de uma tarefa do quadro. Só use depois que o
    usuário confirmar que quer remover.

    Args:
        nome_tarefa: nome da tarefa (como aparece no card).
    """
    try:
        quadro = _conectar_quadro()
        card = _buscar_card(quadro, nome_tarefa)
        if card is None:
            return {"status": "erro",
                    "mensagem": f"Tarefa '{nome_tarefa}' não encontrada no quadro."}
        nome = card.name
        card.delete()
        return {"status": "sucesso", "mensagem": f"Tarefa '{nome}' removida do quadro."}
    except Exception as erro:
        return {"status": "erro", "mensagem": f"Não consegui remover a tarefa: {erro}"}


root_agent = Agent(
    name="agenttaskmanager",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    description="Agente que organiza as tarefas do dia num quadro do Trello.",
    instruction=f"""
Você é um assistente de produtividade que organiza as tarefas do usuário no
quadro '{NOME_QUADRO}' do Trello. Responda sempre em português, de forma curta.

Ao iniciar a conversa:
- Chame get_temporal_context, cumprimente o usuário dizendo a data de hoje e
  pergunte quais são as tarefas do dia.

Suas ferramentas:
1. adicionar_tarefa: crie um card para CADA tarefa que o usuário citar, com
   nome curto, descrição e data de entrega no formato AAAA-MM-DD. Se o
   usuário não disser a data, use a data de hoje (de get_temporal_context).
   Converta 'amanhã', 'sexta' etc. para a data correta.
2. listar_tarefas: mostre as tarefas, todas ou filtrando por status
   ('a fazer', 'em andamento', 'concluido').
3. mudar_status_tarefa: quando o usuário contar que começou ou terminou algo,
   mova o card para 'em andamento' ou 'concluido'. Se não tiver certeza de
   qual tarefa é, liste as tarefas antes e pergunte.
4. remover_tarefa: apague um card, mas só depois de o usuário confirmar.

Regras:
- Se uma ferramenta devolver status 'erro', explique o problema ao usuário em
  linguagem simples, sem inventar que deu certo.
- Não invente tarefas que o usuário não disse.
""",
    tools=[
        get_temporal_context,
        adicionar_tarefa,
        listar_tarefas,
        mudar_status_tarefa,
        remover_tarefa,
    ],
)
