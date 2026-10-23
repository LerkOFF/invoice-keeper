from enum import StrEnum


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class Period(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @property
    def months(self) -> int:
        """Шаг повторения в месяцах. Даты всё равно считаются от якоря, а не цепочкой."""
        return {"monthly": 1, "quarterly": 3, "yearly": 12}[self.value]


class OccurrenceStatus(StrEnum):
    PAID = "paid"
    UNPAID = "unpaid"


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"
