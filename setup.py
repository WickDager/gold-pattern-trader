"""Setup script for gold-pattern-trader."""

from setuptools import setup, find_packages

setup(
    name="gold-pattern-trader",
    version="2.0.0",
    description="Automated XAUUSD trading bot using pattern invalidation "
                "and divergence detection on 1-minute data",
    url="https://github.com/yourusername/gold-pattern-trader",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "pandas>=1.5.0",
        "numpy>=1.23.0",
        "MetaTrader5>=5.0.45",
        "pywin32>=305",
    ],
    entry_points={
        "console_scripts": [
            "gold-pattern-trader=main:main",
        ],
    },
)
