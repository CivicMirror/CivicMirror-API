from .clarity import ClarityAdapter
from .registry import register


@register
class WyomingAdapter(ClarityAdapter):
    state = "WY"
