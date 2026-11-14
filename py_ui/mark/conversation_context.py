
from .memory import source_label
import re
import time


_IDENTITY_CLAIM_RE = re.compile(
    r"\b(?:est[aá]s?|ta|t[aá]|voce|voc[eê])\s+(?:a\s+)?(?:rodando|rodar|roda|executando|executar|executa|usando|usar|usa)\b|"
    r"\b(?:gpt[- ]?\d|claude|gemini|llama|qwen|mistral|deepseek)\b",
    re.I,
)


def _sanitize_identity_claim(text):
    if _IDENTITY_CLAIM_RE.search(text):
        return "[Alegação anterior sobre identidade do modelo omitida; não é evidência do modelo ativo.]"
    return text


def model_history(memory,limit=6):
    getter=getattr(memory,'history',None)
    if not callable(getter):return ()
    count=max(1,min(int(limit),100))
    turns=getter(limit=count);messages=[]
    for turn in turns:
        if not isinstance(turn,dict):continue
        user,assistant=turn.get('user'),turn.get('assistant')
        if not isinstance(user,str) or not isinstance(assistant,str):continue
        origin=source_label(str(turn.get('source','mark')))
        label=f'[Origem informada: {origin}; não comprova identidade]\n' if origin else ''

        clipped_user=_sanitize_identity_claim(user[:600]+('\n[Mensagem anterior parcial]' if len(user)>600 else ''))
        clipped_assistant=_sanitize_identity_claim(assistant[:800]+('\n[Resposta anterior parcial]' if len(assistant)>800 else ''))
        messages.extend(({'role':'user','content':label+clipped_user},{'role':'assistant','content':clipped_assistant}))
    return tuple(messages)


def validated_history(history):
    if not isinstance(history,(list,tuple)) or len(history)>200:raise ValueError('Histórico inválido')
    result=[];size=0
    for message in history:
        if (not isinstance(message,dict) or set(message)!={'role','content'}
                or message['role'] not in ('user','assistant') or not isinstance(message['content'],str)):
            raise ValueError('Histórico aceita somente texto de usuário/assistente')
        size+=len(message['content'])
        if size>200_000:raise ValueError('Histórico excede o limite de contexto')
        result.append({'role':message['role'],'content':message['content']})
    return result


class WorkingMemory:
    """Contexto Imediato (Working Memory) com Janela Deslizante.

    Mantém apenas os últimos N turnos ou até o limite de tokens operacionais,
    descartando turnos antigos e retornando-os para sumarização episódica.
    """

    def __init__(self, max_turns: int = 6, max_tokens: int = 2048) -> None:
        self.max_turns = max(1, max_turns)
        self.max_tokens = max(256, max_tokens)
        self._turns: list[dict] = []

    def add_turn(self, user: str, assistant: str, source: str = "mark") -> list[dict]:
        """Adiciona um turno e retorna a lista de turnos descartados que saíram da janela."""
        turn = {
            "user": user,
            "assistant": assistant,
            "source": source,
            "created_at": int(re.sub(r"\D", "", str(time.time()))[:10] if "time" in globals() else 0),
        }
        self._turns.append(turn)
        retained, discarded = self.truncate_to_limits(self._turns, self.max_turns, self.max_tokens)
        self._turns = retained
        return discarded

    @staticmethod
    def estimate_turn_tokens(turn: dict) -> int:
        u = str(turn.get("user", ""))
        a = str(turn.get("assistant", ""))
        # Aproximação segura: ~4 caracteres por token
        return max(1, (len(u) + len(a)) // 4)

    @classmethod
    def truncate_to_limits(
        cls,
        turns: list[dict],
        max_turns: int = 6,
        max_tokens: int = 2048,
    ) -> tuple[list[dict], list[dict]]:
        """Divide uma lista de turnos em (retained, discarded) respeitando max_turns e max_tokens."""
        if not turns:
            return [], []

        # Primeiro critério: limitar aos últimos max_turns
        if len(turns) > max_turns:
            cutoff = len(turns) - max_turns
            discarded = turns[:cutoff]
            candidate = turns[cutoff:]
        else:
            discarded = []
            candidate = list(turns)

        # Segundo critério: limitar ao orçamento de tokens (do mais recente para o mais antigo)
        retained_reversed: list[dict] = []
        token_count = 0
        overflow_from_tokens: list[dict] = []

        for turn in reversed(candidate):
            t_tokens = cls.estimate_turn_tokens(turn)
            if token_count + t_tokens <= max_tokens or not retained_reversed:
                retained_reversed.append(turn)
                token_count += t_tokens
            else:
                overflow_from_tokens.append(turn)

        overflow_from_tokens.reverse()
        discarded.extend(overflow_from_tokens)
        retained = list(reversed(retained_reversed))
        return retained, discarded

    def active_turns(self) -> list[dict]:
        return list(self._turns)

    def history(self, limit: int = 30) -> list[dict]:
        return self._turns[-max(1, limit):]

    def clear(self) -> None:
        self._turns.clear()

