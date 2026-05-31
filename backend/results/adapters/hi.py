from .clarity import ClarityAdapter
from .registry import register


@register
class HawaiiAdapter(ClarityAdapter):
    state = "HI"
