"""Integration guards for the renamed installed distribution."""
from importlib.metadata import distribution
from pathlib import Path
import json


def test_installed_command_and_package_resources():
    import imaging_scientist

    installed = distribution("imaging-scientist")
    entry = next(e for e in installed.entry_points if e.name == "imaging-scientist")
    assert callable(entry.load())
    package_dir = Path(imaging_scientist.__file__).parent
    config = json.loads((package_dir / "langgraph_dev/langgraph.json").read_text())
    assert "AIScientist" in config["graphs"]  # Existing session graph ID stays stable.
    for target in config["graphs"].values():
        module = target.split(":")[0]
        assert module.startswith("imaging_scientist.")
        assert (package_dir.parent / (module.replace(".", "/") + ".py")).is_file()
    assert (package_dir / "skills").is_dir()


def test_local_brand_does_not_offer_upstream_update():
    from imaging_scientist.update_check import is_update_available

    assert is_update_available() == (False, None)
