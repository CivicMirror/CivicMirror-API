from .clarity import ClarityAdapter
from .registry import register


@register
class RhodeIslandAdapter(ClarityAdapter):
    state = "RI"
