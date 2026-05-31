from .clarity import ClarityAdapter
from .registry import register


@register
class AlaskaAdapter(ClarityAdapter):
    state = "AK"
