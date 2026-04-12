from setuptools import setup, find_packages

setup(
    name="claude-analytics",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    extras_require={"ai": ["anthropic>=0.39.0"]},
    include_package_data=True,
    package_data={"claude_analytics": ["template.html"]},
    entry_points={
        "console_scripts": [
            "claude-analytics=claude_analytics.cli:main",
        ],
    },
    python_requires=">=3.8",
)
