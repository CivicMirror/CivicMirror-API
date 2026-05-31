from .clarity import ClarityAdapter
from .registry import register


@register
class MontanaAdapter(ClarityAdapter):
    state = "MT"
