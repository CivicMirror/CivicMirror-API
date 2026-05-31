from .clarity import ClarityAdapter
from .registry import register


@register
class IndianaAdapter(ClarityAdapter):
    state = "IN"
