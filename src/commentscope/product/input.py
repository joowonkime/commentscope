"""Product API field and cursor validation."""
from uuid import uuid4

from commentscope.agents.web import WebError


def uid(prefix): return prefix+uuid4().hex


def text(value, maximum, *, empty=True):
    if not isinstance(value,str) or len(value)>maximum or not empty and not value.strip():
        raise WebError(400,'invalid_input')
    return value


def integer(value, minimum=0):
    if type(value) is not int or value<minimum: raise WebError(400,'invalid_revision')
    return value


def cursor(query):
    if set(query) - {'after_seq'} or any(len(values) != 1 for values in query.values()):
        raise WebError(400, 'invalid_cursor')
    return integer(int(query.get('after_seq', ['0'])[0]))
