from .clarity import ClarityAdapter
from .registry import register


@register
class WestVirginiaAdapter(ClarityAdapter):
    state = "WV"
