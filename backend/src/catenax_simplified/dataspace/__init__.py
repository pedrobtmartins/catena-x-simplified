"""Single gateway to the participant's dataspace infrastructure (DTR, submodel server, EDC)."""

from .ports import DataspaceError, SubmodelReader, SubmodelRef, TwinRef, TwinRegistry

__all__ = ["DataspaceError", "SubmodelReader", "SubmodelRef", "TwinRef", "TwinRegistry"]
