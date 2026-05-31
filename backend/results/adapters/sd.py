from .clarity import ClarityAdapter
from .registry import register


@register
class SouthDakotaAdapter(ClarityAdapter):
    state = "SD"
