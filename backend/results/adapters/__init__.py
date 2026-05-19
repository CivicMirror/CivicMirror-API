from .registry import get_adapter, list_supported_states

__all__ = ['get_adapter', 'list_supported_states']

# Concrete adapters are imported in ResultsConfig.ready() (results/apps.py)
# to ensure they register themselves at Django startup.
