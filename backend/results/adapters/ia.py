from .clarity import ClarityAdapter
from .registry import register


@register
class IowaAdapter(ClarityAdapter):
    state = "IA"
