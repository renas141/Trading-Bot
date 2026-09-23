from datetime import datetime, timezone
from decimal import Decimal

from app.domain import Direction
from app.strategies.models import Signal

D = Decimal
NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def signal(direction: Direction = Direction.LONG) -> Signal:
    return Signal("BTC/EUR", NOW, direction, D("0.5"), ("Test fixture only",), "test", "1", stop_price=D("99"))
