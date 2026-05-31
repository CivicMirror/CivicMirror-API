from .clarity import ClarityAdapter
from .registry import register


@register
class NewHampshireAdapter(ClarityAdapter):
    state = "NH"
