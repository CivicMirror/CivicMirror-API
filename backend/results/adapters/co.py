from .clarity import ClarityAdapter
from .registry import register


@register
class ColoradoAdapter(ClarityAdapter):
    state = "CO"
