"""Sync mirror of AsyncDiScope.

KEEP IN SYNC with AsyncDiScope.py — this is a mechanical transformation:
  - drop async/await
  - dictdefault.a -> dictdefault
  - isasyncgen / isawaitable branches -> TypeError
  - aclose -> close
When you change one, apply the same change to the other.
"""
from __future__ import annotations

from dataclasses import dataclass
from inspect import isasyncgen, isawaitable, isgenerator
from typing import TYPE_CHECKING

from semifun.caching.cached_property import cached_property
from semifun.caching.dictdefault import dictdefault

from .tools import factory_field

if TYPE_CHECKING:
    from .SemifunApp import SemifunApp


@dataclass(frozen=True)
class SyncDiScope:
    app: SemifunApp
    parent_scope: SyncDiScope | None
    seed_data: dict
    ftype: str

    _cleanup_stack: list = factory_field(list)
    _resolving: set = factory_field(set)  # cycle detection: types currently being resolved


    @cached_property
    def _cache(self): return {**self.seed_data, SyncDiScope: self}

    def resolve_type(self, T):
        (ftype, fname) = (self.ftype + '_inject', T.__name__)
        if T in self._resolving:
            raise RecursionError(f"Circular dependency: #::{ftype}:{fname} is already being resolved")
        self._resolving.add(T)
        try:
            def compute_type():
                if fn := self.app.lookup_fn(ftype=ftype, fname=fname, strict=False):
                    args, kwargs = getattr(T, 'dependency_injection_args2', ((), {}))
                    return self.fn_call(fn=fn, args=args, kwargs=kwargs)
                elif self.parent_scope:
                    return self.parent_scope.resolve_type(T)
                else:
                    raise KeyError(f'#::{ftype}:{fname}')
            return dictdefault(self._cache, T, compute_type)
        finally:
            self._resolving.discard(T)

    def fn_call(self, *, fn, args, kwargs):
        """Call fn with passthrough args/kwargs, resolving Inject[T] params via DI."""
        inject_kwargs = {name: self.resolve_type(T) for name, T in self.app.inject_params(fn)}
        result = fn(*args, **kwargs, **inject_kwargs)
        if isgenerator(result):
            value = next(result)
            self._cleanup_stack.append(result)
            return value
        if isasyncgen(result):
            raise TypeError(f"sync DI context cannot handle async generator from {fn}")
        if isawaitable(result):
            raise TypeError(f"sync DI context cannot handle awaitable from {fn}")
        return result

    def fname_call(self, *, fname, args, kwargs):
        fn = self.app.lookup_fn(ftype=self.ftype, fname=fname, strict=True)
        return self.fn_call(fn=fn, args=args, kwargs=kwargs)

    def close(self):
        """Drain the cleanup stack in reverse order."""
        exception = None
        for gen in reversed(self._cleanup_stack):
            try:
                next(gen)
            except StopIteration:
                pass
            except BaseException as new_exc:
                if exception is not None:
                    new_exc.__context__ = exception
                exception = new_exc
        self._cleanup_stack.clear()
        if exception is not None:
            raise exception
