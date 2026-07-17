from typing import Any

from .base import BaseConverter
from .cog import COGConverter, COGMosaicConverter
from .geotiff import GeoTIFFConverter
from .stac import RioSTACConverter
from .vrt import VRTMosaicConverter

_REGISTRY: dict[str, type[BaseConverter]] = {
    "geotiff": GeoTIFFConverter,
    "cog": COGConverter,
    "cog-mosaic": COGMosaicConverter,
    "rio-stac": RioSTACConverter,
    "vrt": VRTMosaicConverter,
}


def register(name: str, driver: type[BaseConverter]):
    """Add a converter to the registry.

    Args:
        name (str): name of the converter, will be used as key in the registry
        driver (type[BaseConverter]): converter class
    """
    _REGISTRY[name] = driver


def get_converter(name: str, params: dict[str, Any]) -> BaseConverter:
    """Set up a converter instance.

    Args:
        name (str): name of the converter
        params (dict[str, Any]): parameters used for the converter, as key-value pairs

    Raises:
        ValueError: if the registry does not contain a converter with the given name

    Returns:
        BaseConverter: converter instance
    """
    if name not in _REGISTRY:
        raise ValueError(f"No converter registered for driver '{name}'")
    return _REGISTRY[name](**params)


def list_converters() -> list[str]:
    """List the names of the converters in the registry.

    Returns:
        list[str]: converter names
    """
    return list(_REGISTRY.keys())
