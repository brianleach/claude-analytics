from setuptools import setup, find_packages

setup(
    name="claude-analytics",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["anthropic>=0.39.0"],
    entry_points={
        "console_scripts": [
            "claude-analytics=claude_analytics.cli:main",
        ],
    },
    python_requires=">=3.8",
)
