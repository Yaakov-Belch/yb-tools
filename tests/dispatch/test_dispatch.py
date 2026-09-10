"""Tests for semifun.dispatch — sync and async dispatch with DI."""
import pytest
from semifun.dispatch.Inject import Inject, parametric_type
from semifun.dispatch.SemifunApp import SemifunApp
from semifun.dispatch.load_lookup_tables import LoadedFn


# --- helpers ---

class UserId: pass
class UserName: pass

def make_UserId(): return 42
def make_UserName(uid: Inject[UserId]): return f"user_{uid}"

DB = parametric_type('DB')

def make_DB(collection: str): return f"<DB:{collection}>"


def _app(ftype, fns, inject_fns=None):
    tables = {ftype: {name: LoadedFn(fn=fn) for name, fn in fns.items()}}
    if inject_fns:
        tables[ftype + '_inject'] = {name: LoadedFn(fn=fn) for name, fn in inject_fns.items()}
    return SemifunApp(entry_points_group=tables)


# --- basic sync dispatch ---

def test_sync_dispatch_no_injection():
    def hello(name): return f"hello {name}"
    app = _app('test', {'hello': hello})
    result = app.sync_dispatch(
        parent_scope=None, seed_data={}, ftype='test',
        fname='hello', args=('world',), kwargs={},
    )
    assert result == "hello world"


def test_sync_dispatch_with_injection():
    def greet(uid: Inject[UserId]): return f"hello user {uid}"
    app = _app('test', {'greet': greet}, {'UserId': make_UserId})
    result = app.sync_dispatch(
        parent_scope=None, seed_data={}, ftype='test',
        fname='greet', args=(), kwargs={},
    )
    assert result == "hello user 42"


def test_sync_dispatch_chained_injection():
    def greet(name: Inject[UserName]): return f"hello {name}"
    app = _app('test', {'greet': greet}, {'UserId': make_UserId, 'UserName': make_UserName})
    result = app.sync_dispatch(
        parent_scope=None, seed_data={}, ftype='test',
        fname='greet', args=(), kwargs={},
    )
    assert result == "hello user_42"


def test_sync_dispatch_seed_data():
    def greet(uid: Inject[UserId]): return f"hello user {uid}"
    app = _app('test', {'greet': greet})  # no inject table needed
    result = app.sync_dispatch(
        parent_scope=None, seed_data={UserId: 99}, ftype='test',
        fname='greet', args=(), kwargs={},
    )
    assert result == "hello user 99"


# --- dispatch_all ---

def test_sync_dispatch_all():
    def hello(): return "hello"
    def bye(): return "bye"
    app = _app('test', {'hello': hello, 'bye': bye})
    result = app.sync_dispatch_all(
        parent_scope=None, seed_data={}, ftype='test',
        args=(), kwargs={},
    )
    assert result == {'hello': 'hello', 'bye': 'bye'}


# --- parametric types ---

def test_sync_parametric_type():
    def get_data(items: Inject[DB('items')], users: Inject[DB('users')]):
        return {'items': items, 'users': users}
    app = _app('test', {'get_data': get_data}, {'DB': make_DB})
    result = app.sync_dispatch(
        parent_scope=None, seed_data={}, ftype='test',
        fname='get_data', args=(), kwargs={},
    )
    assert result == {'items': '<DB:items>', 'users': '<DB:users>'}


def test_parametric_instance_equality():
    a1 = DB('items')
    a2 = DB('items')
    b = DB('users')
    assert a1 == a2
    assert hash(a1) == hash(a2)
    assert a1 != b


def test_parametric_instance_kwargs():
    a = DB('items', timeout=30)
    b = DB('items', timeout=30)
    c = DB('items', timeout=60)
    assert a == b
    assert a != c
    assert a.dependency_injection_args2 == (('items',), {'timeout': 30})


# --- cycle detection ---

def test_sync_cycle_detection():
    class A: pass
    class B: pass
    def make_A(b: Inject[B]): return A()
    def make_B(a: Inject[A]): return B()
    def start(a: Inject[A]): return a
    app = _app('test', {'start': start}, {'A': make_A, 'B': make_B})
    with pytest.raises(RecursionError, match="Circular dependency"):
        app.sync_dispatch(
            parent_scope=None, seed_data={}, ftype='test',
            fname='start', args=(), kwargs={},
        )


# --- async dispatch ---

@pytest.mark.asyncio
async def test_async_dispatch_with_injection():
    def greet(uid: Inject[UserId]): return f"hello user {uid}"
    app = _app('test', {'greet': greet}, {'UserId': make_UserId})
    result = await app.async_dispatch(
        parent_scope=None, seed_data={}, ftype='test',
        fname='greet', args=(), kwargs={},
    )
    assert result == "hello user 42"


@pytest.mark.asyncio
async def test_async_parametric_type():
    def get_data(items: Inject[DB('items')], users: Inject[DB('users')]):
        return {'items': items, 'users': users}
    app = _app('test', {'get_data': get_data}, {'DB': make_DB})
    result = await app.async_dispatch(
        parent_scope=None, seed_data={}, ftype='test',
        fname='get_data', args=(), kwargs={},
    )
    assert result == {'items': '<DB:items>', 'users': '<DB:users>'}


@pytest.mark.asyncio
async def test_async_cycle_detection():
    class A: pass
    class B: pass
    def make_A(b: Inject[B]): return A()
    def make_B(a: Inject[A]): return B()
    def start(a: Inject[A]): return a
    app = _app('test', {'start': start}, {'A': make_A, 'B': make_B})
    with pytest.raises(RecursionError, match="Circular dependency"):
        await app.async_dispatch(
            parent_scope=None, seed_data={}, ftype='test',
            fname='start', args=(), kwargs={},
        )


# --- generator cleanup ---

def test_sync_generator_cleanup():
    cleanup_called = []
    def resource():
        cleanup_called.append('setup')
        yield 'the_resource'
        cleanup_called.append('teardown')
    app = _app('test', {'resource': resource})
    with app.open_sync_scope(parent_scope=None, seed_data={}, ftype='test') as scope:
        fn = app.lookup_fn(ftype='test', fname='resource', strict=True)
        result = scope.fn_call(fn=fn, args=(), kwargs={})
        assert result == 'the_resource'
        assert cleanup_called == ['setup']
    assert cleanup_called == ['setup', 'teardown']


# --- missing function ---

def test_missing_fn_raises():
    app = _app('test', {})
    with pytest.raises(KeyError, match='#::test:nonexistent'):
        app.sync_dispatch(
            parent_scope=None, seed_data={}, ftype='test',
            fname='nonexistent', args=(), kwargs={},
        )
