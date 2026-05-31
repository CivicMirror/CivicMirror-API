from .clarity import ClarityAdapter
from .registry import register


@register
class IdahoAdapter(ClarityAdapter):
    state = "ID"
