from __future__ import annotations

from .masterdata import MasterDataError
from .release_manifest import load_manifest

SERVER_TABLES = load_manifest()["server_master_bindings"]


def bound_fields(name, values):
    binding = SERVER_TABLES.get(name)
    if binding is None or not isinstance(values, list):
        raise MasterDataError("Server-only master binding requires review: " + name)
    fields = binding["fields"]
    limits = {"int": (-(2 ** 31), 2 ** 31 - 1), "long": (-(2 ** 63), 2 ** 63 - 1)}
    for row in values:
        if not isinstance(row, list) or len(row) != len(fields):
            raise MasterDataError("Server-only master row does not match its reviewed layout: " + name)
        for field, value in zip(fields, row):
            bounds = limits.get(field["type"])
            if bounds is None or type(value) is not int or not bounds[0] <= value <= bounds[1]:
                raise MasterDataError("Server-only master field does not match its reviewed type: " + name + "." + field["name"])
    return [field["name"] for field in fields]
