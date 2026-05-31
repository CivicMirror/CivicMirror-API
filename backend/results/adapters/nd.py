from .clarity import ClarityAdapter
from .registry import register


@register
class NorthDakotaAdapter(ClarityAdapter):
    state = "ND"
