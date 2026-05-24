from .clarity import ClarityAdapter
from .registry import register


@register
class SouthCarolinaAdapter(ClarityAdapter):
    state = "SC"
