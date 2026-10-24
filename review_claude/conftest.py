"""conftest.py — zorg dat ÉÓNZE custom_components wint van de test-plugin.

pytest_homeassistant_custom_component importeert via
`from .testing_config.custom_components.test_constant_deprecation import ...`,
waardoor het package `custom_components` al in sys.modules staat (gericht op de
testing_config-map van de plugin) vóórdat onze tests iets importeren. Een
vervroegde insert van repo_root op sys.path helpt dan niet: Python gebruikt het
gecachte module-object. Deze conftest loopt als eerste en vervangt de cache-entry
door ons eigen package, zodat `import custom_components.energyprijs` werkt.
"""
import importlib.util
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent


def _force_own_custom_components() -> None:
    mod = sys.modules.get("custom_components")
    ours = repo_root / "custom_components"
    if mod is not None and str(ours) not in [str(p) for p in getattr(mod, "__path__", [])]:
        # Verwijder plugin-versie + submodules uit de cache.
        for name in [m for m in list(sys.modules)
                     if m == "custom_components" or m.startswith("custom_components.")]:
            del sys.modules[name]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    # Laad ons package onmiddellijk, vóór elke plugin-import eronder kan komen.
    spec = importlib.util.spec_from_file_location(
        "custom_components", ours / "__init__.py",
        submodule_search_locations=[str(ours)],
    )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules["custom_components"] = loaded
    spec.loader.exec_module(loaded)


_force_own_custom_components()


# ── Config-flow-tests: de plugin-fixture `enable_custom_integrations` popt onze
# repo op sys.path en ververst HA's custom-component-loader. In deze repo wonen
# de integraties direct onder custom_components/, dus dat werkt out-of-the-box.
