from setuptools import setup, find_packages

setup(
    name="mkdocs-cdoc",
    version="1.0.4",
    description="MkDocs plugin for C/C++ autodoc (Hawkmoth-like)",
    keywords="mkdocs cdoc c hawkmoth documentation python",
    url="https://github.com/pawelsikora/mkdocs-cdoc/",
    author="Pawel Sikora",
    author_email="sikor6@gmail.com",
    packages=find_packages(),
    install_requires=[
        "mkdocs>=1.4",
    ],
    classifiers = [
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Documentation",
        "Topic :: Software Development :: Documentation",
        "Framework :: MkDocs",
    ],
    entry_points={
        "mkdocs.plugins": [
            "cdoc = mkdocs_cdoc.plugin:CdocPlugin",
        ],
    },
)
