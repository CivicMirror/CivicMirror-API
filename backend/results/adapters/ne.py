from .clarity import ClarityAdapter
from .registry import register


@register
class NebraskaAdapter(ClarityAdapter):
    state = "NE"
