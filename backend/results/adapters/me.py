from .clarity import ClarityAdapter
from .registry import register


@register
class MaineAdapter(ClarityAdapter):
    state = "ME"
