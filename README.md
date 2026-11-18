# Agente de Tarefas no Trello (Google ADK + Gemini)

Um agente de conversa que organiza as tarefas do dia num quadro do Trello.
Ele foi feito com o **Agent Development Kit (ADK)** do Google e o modelo
**Gemini**: cada função Python em [`agenttaskmanager/agent.py`](agenttaskmanager/agent.py)
vira uma ferramenta que o agente pode chamar.

Projeto baseado no agente 04 do repositório
[agent-carbon-footprint](https://github.com/digitalinnovationone/agent-carbon-footprint/tree/main/agents/agent04)
da DIO, com melhorias descritas abaixo.

## O que o agente faz

1. Começa a conversa dizendo a data de hoje e pergunta quais são as tarefas do dia.
2. Cria um card na lista **A fazer** para cada tarefa, com nome, descrição e data de entrega.
3. Lista as tarefas, todas ou só as de um status.
4. Move o card entre **A fazer**, **Em andamento** e **Concluído** quando você conta o que já fez.
5. Remove uma tarefa, depois de pedir confirmação.

### Ferramentas

| Ferramenta | O que faz |
|---|---|
| `get_temporal_context()` | Devolve data, hora e dia da semana atuais (fuso de São Paulo). |
| `adicionar_tarefa(nome_tarefa, descricao, data_entrega)` | Cria um card na lista "A fazer". |
| `listar_tarefas(status="todas")` | Lista os cards, opcionalmente filtrando por status. |
| `mudar_status_tarefa(nome_tarefa, novo_status)` | Move o card para outra lista. |
| `remover_tarefa(nome_tarefa)` | Apaga o card. |

**Como o agente escolhe a ferramenta:** o ADK envia ao Gemini o nome, a docstring
e os parâmetros de cada função. Quando você diz "terminei o relatório", o modelo
percebe que a descrição de `mudar_status_tarefa` combina com o pedido e a chama
com `nome_tarefa="relatório"` e `novo_status="concluido"`. Cada ferramenta devolve
um dicionário com `status` (`sucesso` ou `erro`) e uma mensagem, que o modelo usa
para responder.

## Estrutura

```
agente04/
├── agenttaskmanager/
│   ├── __init__.py
│   ├── agent.py        # ferramentas + root_agent
│   └── .env.exemplo    # modelo das variáveis de ambiente
├── requirements.txt
├── .gitignore          # ignora .env e o ambiente virtual
└── README.md
```

## Como configurar

### 1. Trello

1. Crie um quadro chamado **DIO** (ou outro nome, veja `TRELLO_BOARD_NAME`) com
   as listas **A fazer**, **Em andamento** e **Concluído**.
   O agente também reconhece "To Do", "Doing" e "Done".
2. Acesse o [portal de Power-Ups](https://trello.com/power-ups/admin/), clique em
   **New** e crie um aplicativo (nome, área de trabalho, e-mail de contato). O
   campo de URL do iframe pode ficar em branco.
3. Na página do Power-Up, abra **API Key** e copie a **chave** e o **segredo**.
4. Gere o **token** abrindo no navegador (troque `SUA_API_KEY`):

   ```
   https://trello.com/1/authorize?expiration=never&name=AgenteTarefas&scope=read,write&response_type=token&key=SUA_API_KEY
   ```

   Clique em **Permitir** e copie o token mostrado. Guarde-o: ele não aparece de novo.

O passo a passo completo, com imagens, está no
[guia do Trello](https://github.com/digitalinnovationone/agent-carbon-footprint/blob/main/agents/agent04/readme.md).

### 2. Ambiente Python

Use **Python 3.10 ou superior** (mínimo do ADK hoje). No Windows (PowerShell):

```powershell
cd agente04
python -m venv .lab-dio
.\.lab-dio\Scripts\Activate.ps1
pip install -r requirements.txt
```

No Linux/macOS, ative com `source .lab-dio/bin/activate`.

> O `requirements.txt` original listava `datetime` e `dotenv`. `datetime` já vem
> com o Python e o pacote certo para ler o `.env` é o `python-dotenv`. O `tzdata`
> fornece os fusos horários no Windows.

### 3. Credenciais

```powershell
Copy-Item agenttaskmanager\.env.exemplo agenttaskmanager\.env
```

Preencha o `.env`:

| Variável | De onde vem |
|---|---|
| `GOOGLE_API_KEY` | Chave gratuita do [Google AI Studio](https://aistudio.google.com/apikey) |
| `TRELLO_API_KEY` / `TRELLO_API_SECRET` | Página do seu Power-Up |
| `TRELLO_TOKEN` | URL de autorização do passo 1.4 |
| `TRELLO_BOARD_NAME` | Nome do seu quadro (padrão `DIO`) |
| `TIMEZONE` | Fuso das datas (padrão `America/Sao_Paulo`) |

O `.env` está no `.gitignore` e nunca deve ser enviado ao GitHub.

### 4. Rodar

Na pasta `agente04` (a que **contém** `agenttaskmanager/`):

```powershell
adk web
```

Abra http://localhost:8000, escolha `agenttaskmanager` e converse. Também dá para
usar o terminal com `adk run agenttaskmanager`.

> A chave gratuita do Gemini tem limite diário de requisições. Teste com
> conversas curtas.

## Melhorias em relação ao código original

### Principal: data chegando ao Trello com um dia a menos

**Problema.** O código original mandava a data como texto puro, por exemplo
`2026-11-18`. O Trello interpreta isso como meia-noite em **UTC**. No Brasil
(UTC-3) esse horário ainda é **17/11 às 21h**, então o card aparecia com um dia
a menos.

**Solução.** A função `_data_para_trello` lê a data (aceita `AAAA-MM-DD` e
`DD/MM/AAAA`), coloca o horário de **12:00 no fuso local** e envia em ISO com o
deslocamento explícito: `2026-11-18T12:00:00-03:00`. Meio-dia dá margem para
qualquer fuso do Brasil sem mudar de dia. Na hora de listar, `_data_legivel`
converte a data de volta para o fuso local, então a lista mostra o mesmo dia
que o card.

**Como testar.** Peça "crie a tarefa Revisar slides para amanhã" e confira no
quadro que a data do card é a de amanhã, não a de hoje. Depois peça "liste
minhas tarefas" e veja a mesma data na resposta.

### Outras melhorias

- **Status com acento e variações.** "Concluído", "concluida", "feito",
  "doing", "pendente" etc. são normalizados (minúsculas, sem acento) antes da
  comparação. Antes, "concluído" com acento dava status inválido.
  *Teste:* "terminei o relatório" ou "marque Revisar slides como Concluído".
- **Ferramenta `remover_tarefa`.** A instrução original prometia remover
  tarefas, mas não havia ferramenta para isso. Agora existe, e a instrução
  pede confirmação antes de apagar.
- **`try/except` em todas as ferramentas.** Todas devolvem
  `{"status": "erro", "mensagem": ...}` em vez de quebrar a conversa (por
  exemplo, quadro ou lista inexistente, token errado).
- **Conexão com o Trello numa função só.** `_conectar_quadro()` substitui o
  código repetido em cada ferramenta (e a chamada duplicada a `list_boards()`).
- **Nome do quadro configurável** pela variável `TRELLO_BOARD_NAME`, sem
  editar o código.
- **Instrução alinhada às ferramentas.** O texto do agente descreve
  exatamente as cinco ferramentas que existem.

## Roteiro de teste no `adk web`

1. "Oi" → o agente diz a data de hoje e pergunta as tarefas.
2. "Hoje preciso estudar ADK, revisar o README e pagar a conta de luz até sexta"
   → três cards em **A fazer**, o último com a data de sexta.
3. "Quais tarefas estão a fazer?" → lista os três.
4. "Comecei a estudar ADK" → card vai para **Em andamento**.
5. "Terminei o README, está concluído" → card vai para **Concluído**.
6. "Remova a tarefa da conta de luz" → o agente pede confirmação e apaga.

## Evidências

<!-- Coloque aqui os prints da conversa no adk web ao lado do quadro, por exemplo:
![Conversa e quadro](docs/print-conversa.png)
-->
