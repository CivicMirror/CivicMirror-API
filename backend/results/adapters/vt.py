from .clarity import ClarityAdapter
from .registry import register


@register
class VermontAdapter(ClarityAdapter):
    state = "VT"
