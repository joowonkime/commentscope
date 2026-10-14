"""Opt-in schema visibility BEFORE request caching; transport grammar is unchanged.

llama.cpp's response_format constrains decoding but does not teach the model the
output contract. Only application-owned schemas belong in this system suffix.
"""
import json


class SchemaVisibleCalls:
    def __init__(self, calls, systems):
        self.calls = calls
        self.systems = frozenset(systems)

    def __call__(self, system, data, schema):
        if system in self.systems:
            system += '\n\nRequired JSON output schema:\n' + json.dumps(
                schema, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return self.calls(system, data, schema)
