from .clarity import ClarityAdapter
from .registry import register


@register
class LouisianaAdapter(ClarityAdapter):
    state = "LA"
