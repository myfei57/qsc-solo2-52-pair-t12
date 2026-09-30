"""Tiny pytest-compatible runner (pytest is unavailable in this environment).

Supports the subset used by this suite: module-level ``test_*`` functions,
``pytest.raises`` context managers, and the ``runtime``/``cycled``/
``tmp_path`` fixtures. Not a pytest replacement in general.
"""

from __future__ import annotations

import contextlib
import importlib
import inspect
import pathlib
import sys
import tempfile
import types

FAILURES: list[str] = []
PASS = 0


class _Raises:
    def __init__(self, exc_type):
        self.exc_type = exc_type
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"expected {self.exc_type.__name__} but nothing was raised")
        if not issubclass(exc_type, self.exc_type):
            return False
        self.value = exc
        return True


def raises(exc_type):
    return _Raises(exc_type)


class _Mark:
    def parametrize(self, *args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    def __getattr__(self, name):
        def decorator(*args, **kwargs):
            if args and callable(args[0]):
                return args[0]

            def wrap(fn):
                return fn

            return wrap

        return decorator


def fixture(*args, **kwargs):
    def decorator(fn):
        fn._fixture = True
        return fn

    if args and callable(args[0]):
        return decorator(args[0])
    return decorator


class _Approx:
    def __init__(self, expected, rel=1e-6):
        self.expected = expected
        self.rel = rel

    def __eq__(self, other):
        return abs(other - self.expected) <= abs(self.expected) * self.rel + 1e-9


def approx(expected, rel=1e-6):
    return _Approx(expected, rel)


pytest = types.ModuleType("pytest")
pytest.raises = raises
pytest.approx = approx
pytest.fixture = fixture
pytest.mark = _Mark()
sys.modules.setdefault("pytest", pytest)

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import tests.conftest as conftest  # noqa: E402


FIXTURE_CACHE: dict = {}


def fixture_value(name: str, module, tmpdir: pathlib.Path, stack: tuple = ()):
    if name == "tmp_path":
        return tmpdir
    if name in stack:
        raise RuntimeError(f"fixture cycle: {stack}")
    if name == "runtime":
        return _runtime_fixture(module)
    if name == "cycled":
        from tests.support import run_full_cycle

        rt = _runtime_fixture(module)
        run_full_cycle(rt)
        return rt
    fn = getattr(module, name, None) or getattr(conftest, name, None)
    if fn is None or not getattr(fn, "_fixture", False):
        raise RuntimeError(f"unknown fixture {name}")
    sig = inspect.signature(fn)
    kwargs = {
        pname: fixture_value(pname, module, tmpdir, stack + (name,))
        for pname in sig.parameters
    }
    return fn(**kwargs)


def _runtime_fixture(module):
    from mixplant.runtime import PlantRuntime
    from mixplant.config import StationConfig

    plant = PlantRuntime(StationConfig(web_dir=ROOT / "web"), storage="memory")
    plant.bootstrap()
    return plant


def main() -> int:
    global PASS
    test_dir = ROOT / "tests"
    for path in sorted(test_dir.glob("test_*.py")):
        mod_name = f"tests.{path.stem}"
        module = importlib.import_module(mod_name)
        for name, fn in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(fn):
                continue
            with tempfile.TemporaryDirectory() as tmp:
                sig = inspect.signature(fn)
                kwargs = {}
                for pname, param in sig.parameters.items():
                    if param.default is not inspect.Parameter.empty:
                        continue
                    kwargs[pname] = fixture_value(pname, module, pathlib.Path(tmp))
                try:
                    fn(**kwargs)
                    PASS += 1
                except Exception as exc:  # noqa: BLE001
                    FAILURES.append(f"{mod_name}::{name}: {type(exc).__name__}: {exc}")
    print(f"{PASS} passed, {len(FAILURES)} failed")
    for failure in FAILURES:
        print("FAIL", failure)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
