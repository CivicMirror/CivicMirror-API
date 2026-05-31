from .clarity import ClarityAdapter
from .registry import register


@register
class OklahomaAdapter(ClarityAdapter):
    state = "OK"
