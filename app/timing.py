import math
import random


def varied_delay(base, spread=0):
    """Optional bounded timing variation; zero spread preserves exact delays."""
    if not math.isfinite(base) or not 0 <= base <= 3600:
        raise ValueError('Задержка должна быть от 0 до 3600 секунд.')
    if not math.isfinite(spread) or not 0 <= spread <= 60:
        raise ValueError('Разброс должен быть от 0 до 60 секунд.')
    if spread == 0:
        return base
    return round(random.uniform(max(0, base - spread), min(3600, base + spread)), 3)
