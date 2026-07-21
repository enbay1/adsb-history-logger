from setuptools import setup

# Present only so debhelper's pybuild picks the classic (setup.py-based)
# plugin, which installs into the Python-version-independent
# /usr/lib/python3/dist-packages instead of a version-specific path.
# All actual metadata lives in pyproject.toml.
setup()
