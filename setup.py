from setuptools import setup, find_packages

setup(
    name="mkdocs-cdoc",
    version="1.0.0",
    description="MkDocs plugin for C/C++ autodoc (Hawkmoth-like)",
    keywords="mkdocs cdoc c hawkmoth documentation gtk-doc python",
    url="https://github.com/pawelsikora/mkdocs-cdoc/",
    author="Pawel Sikora",
    author_email="sikor6@gmail.com",
    packages=find_packages(),
    install_requires=[
        "mkdocs>=1.4",
    ],
    entry_points={
        "mkdocs.plugins": [
            "cdoc = mkdocs_cdoc.plugin:CdocPlugin",
        ],
    },
)
