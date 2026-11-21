"""Gateway errors. API handlers map them to the contract's error shape {detail (Polish), code}."""
from __future__ import annotations


class LLMError(Exception):
    code = "llm_error"
    status = 502
    detail = "Model językowy nie odpowiedział poprawnie."

    def __init__(self, msg: str = "", **extra):
        super().__init__(msg or self.detail)
        self.extra = extra


class SovereignUnavailable(LLMError):
    code = "sovereign_unavailable"
    status = 503
    detail = ("Model w Polsce jest teraz niedostępny. Poufnych danych nie wysyłamy do chmury, "
              "więc ta część analizy AI jest wstrzymana. Spróbuj ponownie później.")


class RefusedForSensitivity(LLMError):
    code = "refused_for_sensitivity"
    status = 422
    detail = "To zadanie nie może przetwarzać poufnych danych."


class ProviderDown(LLMError):
    code = "llm_unavailable"
    status = 503
    detail = "Model językowy jest chwilowo niedostępny. Spróbuj za chwilę."


class BillingDepleted(LLMError):
    """Provider refuses with HTTP 402 (prepaid credits used up)."""
    code = "llm_billing"
    status = 503
    detail = "Limit środków na model w chmurze jest wyczerpany. Odpowiedź AI będzie dostępna po doładowaniu konta."


class BudgetExceeded(LLMError):
    code = "llm_budget_exceeded"
    status = 429
    detail = "Dzienny limit kosztów modelu został wyczerpany."


class ReplayMiss(LLMError):
    code = "llm_replay_miss"
    status = 503
    detail = "Brak nagranej odpowiedzi modelu dla tego zapytania."


class InvalidOutput(LLMError):
    code = "llm_invalid_output"
    status = 502
    detail = "Model zwrócił odpowiedź w złym formacie."


class Transient(LLMError):
    """Retryable backend failure (429, 5xx, timeout)."""
    code = "llm_transient"


def error_body(e: LLMError) -> dict:
    return {"detail": e.detail, "code": e.code}
