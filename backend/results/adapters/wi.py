from .clarity import ClarityAdapter
from .registry import register


@register
class WisconsinAdapter(ClarityAdapter):
    state = "WI"
