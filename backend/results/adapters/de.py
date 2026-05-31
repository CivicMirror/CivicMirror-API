from .clarity import ClarityAdapter
from .registry import register


@register
class DelawareAdapter(ClarityAdapter):
    state = "DE"
