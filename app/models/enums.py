from enum import StrEnum


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class Period(StrEnum):
    MONTHLY = "monthly"


class OccurrenceStatus(StrEnum):
    PAID = "paid"
    UNPAID = "unpaid"


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"
