import re
from app.models import SemaforoResponse


def normalize_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def validate_cnpj(cnpj: str) -> bool:
    cnpj = normalize_cnpj(cnpj)
    if len(cnpj) != 14:
        return False

    # Rejeita sequências todas iguais (ex: 00000000000000)
    if len(set(cnpj)) == 1:
        return False

    # Validação dos dígitos verificadores
    def calc_digit(cnpj_slice, weights):
        total = sum(int(d) * w for d, w in zip(cnpj_slice, weights))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    d1 = calc_digit(cnpj[:12], weights1)
    d2 = calc_digit(cnpj[:13], weights2)

    return cnpj[-2:] == f"{d1}{d2}"


def get_semaforo(situacao: str | None) -> SemaforoResponse:
    normalized = (situacao or "").strip().upper()

    if normalized == "ATIVA":
        return SemaforoResponse(
            cor="verde",
            mensagem="Empresa ativa e regular.",
            situacao=normalized or "DESCONHECIDA",
        )

    if normalized in {"INAPTA", "SUSPENSA", "BAIXADA", "NULA"}:
        messages = {
            "INAPTA": "Empresa inapta.",
            "SUSPENSA": "Empresa com inscrição suspensa.",
            "BAIXADA": "Empresa baixada (encerrada).",
            "NULA": "Inscrição nula.",
        }
        return SemaforoResponse(
            cor="vermelho",
            mensagem=messages.get(normalized, "Situação irregular."),
            situacao=normalized,
        )

    return SemaforoResponse(
        cor="amarelo",
        mensagem=f"Situação não reconhecida: {normalized or 'desconhecida'}.",
        situacao=normalized or "DESCONHECIDA",
    )
