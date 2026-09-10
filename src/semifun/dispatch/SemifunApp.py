from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from inspect import signature

from semifun.caching.cached_property import cached_property
from semifun.caching.dictdefault import dictdefault

from .AsyncDiScope import AsyncDiScope
from .Inject import injected_type
from .SyncDiScope import SyncDiScope
from .load_lookup_tables import load_lookup_tables
from .tools import factory_field


@dataclass(frozen=True)
class SemifunApp:
    # Testing only: provide _lookup_tables directly as a dict to entry_points_group.
    entry_points_group: str | dict
    _inject_params_cache: dict = factory_field(dict)

    def inject_params(self, fn):
        """Return [(param_name, T), ...] for Inject[T] params in fn's signature. Cached."""
        return dictdefault(self._inject_params_cache, fn, lambda: [
            (p.name, T) for p in signature(fn).parameters.values()
            if (T := injected_type(p.annotation)) is not None
        ])

    @cached_property
    def _lookup_tables(self) -> dict[str, dict[str, FnLoader]]: # [ftype][fname]
        if isinstance(self.entry_points_group, dict): return self.entry_points_group
        return load_lookup_tables(entry_points_group=self.entry_points_group)

    def lookup_fn(self, *, ftype, fname, strict):
        if res := self._lookup_tables.get(ftype, {}).get(fname, None): return res.fn
        if strict: raise KeyError(f'#::{ftype}:{fname}')
        return None

    def fn_items(self, *, ftype):
        return [
            (fname, fn_loader.fn)
            for fname, fn_loader in self._lookup_tables.get(ftype, {}).items()
        ]

    async def async_dispatch(self, *, parent_scope, seed_data, ftype, fname, args, kwargs):
        async with self.open_async_scope(parent_scope=parent_scope, seed_data=seed_data, ftype=ftype) as scope:
            fn = self.lookup_fn(ftype=ftype, fname=fname, strict=True)
            return await scope.fn_call(fn=fn, args=args, kwargs=kwargs)

    async def async_dispatch_all(self, *, parent_scope, seed_data, ftype, args, kwargs):
        async with self.open_async_scope(parent_scope=parent_scope, seed_data=seed_data, ftype=ftype) as scope:
            return {
                fname: await scope.fn_call(fn=fn, args=args, kwargs=kwargs)
                for fname, fn in self.fn_items(ftype=ftype)
            }

    @asynccontextmanager
    async def open_async_scope(self, *, parent_scope, seed_data, ftype):
        scope = AsyncDiScope(app=self, parent_scope=parent_scope, seed_data=seed_data, ftype=ftype)
        try: yield scope
        finally: await scope.aclose()

    # --- sync mirrors of async_dispatch / async_dispatch_all / open_async_scope ---
    # KEEP IN SYNC: drop async/await, AsyncDiScope -> SyncDiScope, aclose -> close.

    def sync_dispatch(self, *, parent_scope, seed_data, ftype, fname, args, kwargs):
        with self.open_sync_scope(parent_scope=parent_scope, seed_data=seed_data, ftype=ftype) as scope:
            fn = self.lookup_fn(ftype=ftype, fname=fname, strict=True)
            return scope.fn_call(fn=fn, args=args, kwargs=kwargs)

    def sync_dispatch_all(self, *, parent_scope, seed_data, ftype, args, kwargs):
        with self.open_sync_scope(parent_scope=parent_scope, seed_data=seed_data, ftype=ftype) as scope:
            return {
                fname: scope.fn_call(fn=fn, args=args, kwargs=kwargs)
                for fname, fn in self.fn_items(ftype=ftype)
            }

    @contextmanager
    def open_sync_scope(self, *, parent_scope, seed_data, ftype):
        scope = SyncDiScope(app=self, parent_scope=parent_scope, seed_data=seed_data, ftype=ftype)
        try: yield scope
        finally: scope.close()

    @cached_property
    def tmsgpack_codec_no_seed_data(self):
        return self.tmsgpack_codec(seed_data={})

    def tmsgpack_codec(self, *, seed_data):
        from tmsgpack.codec import TmsgpackCodec
        return TmsgpackCodec(
            sort_keys=True,
            di=_TmsgpackDiAdapter(app=self, seed_data=seed_data),
        )


@dataclass(frozen=True)
class _TmsgpackDiAdapter:
    """Adapts SemifunApp to the DependencyInjectorProtocol expected by TmsgpackCodec."""
    app: SemifunApp
    seed_data: dict

    @staticmethod
    def injected_type(annotation):
        return injected_type(annotation)

    def lookup_type(self, type_name):
        return self.app.lookup_fn(ftype='tmsgpack_codec', fname=type_name, strict=True)

    def with_seed_data(self, seed_data):
        return _TmsgpackDiAdapter(app=self.app, seed_data={**self.seed_data, **seed_data})

    def sync_call_with_args(self, *, fn, args, kwargs):
        with self.app.open_sync_scope(parent_scope=None, seed_data=self.seed_data, ftype='tmsgpack_codec') as scope:
            return scope.fn_call(fn=fn, args=args, kwargs=kwargs)


app = SemifunApp(entry_points_group='semifun.dispatch.app')

