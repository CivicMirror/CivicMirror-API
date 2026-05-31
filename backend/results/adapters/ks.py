from .clarity import ClarityAdapter
from .registry import register


@register
class KansasAdapter(ClarityAdapter):
    state = "KS"
