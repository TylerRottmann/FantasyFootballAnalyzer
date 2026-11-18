"""Request-local timing helpers. Inactive unless middleware enables profiling."""
from collections import defaultdict
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

from django.shortcuts import render as django_render


current_profile = ContextVar('request_performance_profile', default=None)


class RequestProfile:
    def __init__(self):
        self.seconds = defaultdict(float)
        self.last_checkpoint = perf_counter()


def checkpoint(name):
    """Record a consecutive stage, including SQL and Python work within it."""
    profile = current_profile.get()
    if profile is not None:
        now = perf_counter()
        profile.seconds[name] += now - profile.last_checkpoint
        profile.last_checkpoint = now


def timed_call(name, function, *args, **kwargs):
    profile = current_profile.get()
    if profile is None:
        return function(*args, **kwargs)
    started = perf_counter()
    try:
        return function(*args, **kwargs)
    finally:
        profile.seconds[name] += perf_counter() - started


def timed(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            return timed_call(name, function, *args, **kwargs)
        return wrapped
    return decorate


def timed_render(*args, **kwargs):
    return timed_call('render', django_render, *args, **kwargs)
