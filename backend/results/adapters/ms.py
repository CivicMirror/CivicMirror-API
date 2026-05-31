from .clarity import ClarityAdapter
from .registry import register


@register
class MississippiAdapter(ClarityAdapter):
    state = "MS"
