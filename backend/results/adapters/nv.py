from .clarity import ClarityAdapter
from .registry import register


@register
class NevadaAdapter(ClarityAdapter):
    state = "NV"
