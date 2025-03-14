#!/usr/bin/env python

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from collections import namedtuple

import yaml
from packaging.version import parse

from .komodo_error import KomodoError, KomodoException
from .pypi_dependencies import PypiDependencies
from .yaml_file_types import ReleaseFile, RepositoryFile

Report = namedtuple(
    "LintReport",
    [
        "release_name_errors",
        "maintainer_errors",
        "version_errors",
    ],
)

MISSING_PACKAGE = "missing package"
MISSING_VERSION = "missing version"
MISSING_DEPENDENCY = "missing dependency"
MISSING_MAINTAINER = "missing maintainer"
MISSING_MAKE = "missing make information"
MALFORMED_VERSION = "malformed version"
MAIN_VERSION = "dangerous version (main branch)"
MASTER_VERSION = "dangerous version (master branch)"
FLOAT_VERSION = "dangerous version (float interpretable)"


def lint_version_numbers(package, version, repo):
    package_release = repo[package][version]
    maintainer = package_release.get("maintainer", MISSING_MAINTAINER)

    try:
        logging.info(f"Using {package} {version}")
        if "main" in version:
            return KomodoError(package, version, maintainer, err=MAIN_VERSION)
        if "master" in version:
            return KomodoError(package, version, maintainer, err=MASTER_VERSION)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            parsed_version = parse(version)
            # A warning coincides with finding "Legacy" in repr(v)
        if "Legacy" in repr(
            parsed_version
        ):  # don't know if possible to check otherwise
            return KomodoError(package, version, maintainer)
    except Exception as err:  # pylint: disable=broad-exception-caught
        # Log any exception:
        return KomodoError(package, version, maintainer, err=str(err))
    return None


def lint(
    release_file: ReleaseFile,
    repository_file: RepositoryFile,
) -> Report:
    maintainers, versions = [], []
    for package_name, package_version in release_file.content.items():
        try:
            lint_maintainer = repository_file.lint_maintainer(
                package_name,
                package_version,
            )  # throws komodoexception on missing package or version in repository
            if lint_maintainer:
                maintainers.append(lint_maintainer)

            lint_version_number = lint_version_numbers(
                package_name,
                package_version,
                repository_file.content,
            )
            if lint_version_number:
                versions.append(lint_version_number)
        except KomodoException as komodo_exception:
            maintainers.append(komodo_exception.error)
    return Report(
        release_name_errors=[],
        maintainer_errors=maintainers,
        version_errors=versions,
    )


def check_dependencies(
    release_file: ReleaseFile, repository_file: RepositoryFile, full_python_version: str
) -> list[KomodoError]:
    all_dependencies = dict(release_file.content.items())

    dependencies = PypiDependencies(
        all_dependencies, python_version=full_python_version
    )
    for name, version in release_file.content.items():
        if (
            name not in repository_file.content
            or version not in repository_file.content[name]
        ):
            raise ValueError(f"Missing package in repository file: {name}=={version}")
        package_repo = repository_file.content[name][version]
        if package_repo.get("source") != "pypi":
            dependencies.add_user_specified(name, package_repo.get("depends", []))

    failed_requirements = dependencies.failed_requirements()
    if failed_requirements:
        package_set = sorted(set(failed_requirements.values()))
        deps = [
            KomodoError(
                err="Failed requirements:",
                depends=[str(r) for r in failed_requirements],
                package=", ".join(package_set),
            )
        ]
    else:
        deps = []
    dependencies.dump_cache()

    return deps


def get_args(args=None):
    parser = argparse.ArgumentParser(
        description="Lint komodo setup.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "packagefile",
        type=ReleaseFile(),
        help="A Komodo release file mapping package name to version, in YAML format.",
    )
    parser.add_argument(
        "repofile",
        type=RepositoryFile(),
        help="A Komodo repository file, in YAML format.",
    )
    parser.add_argument(
        "--verbose",
        help="Massive amount of outputs.",
        action="store_const",
        dest="loglevel",
        const=logging.INFO,
    )
    parser.add_argument(
        "--check-pypi-dependencies",
        dest="check_pypi_dependencies",
        help="Checks package metadata",
        action="store_true",
        default=False,
    )
    return parser.parse_args(args)


def lint_main(args=None):
    args = get_args(args)
    logging.basicConfig(format="%(message)s", level=args.loglevel)

    if args.check_pypi_dependencies:
        python_version = args.packagefile.content["python"]
        with open("builtin_python_versions.yml", encoding="utf-8") as f:
            full_python_version = yaml.safe_load(f)[python_version]
        deps = check_dependencies(args.packagefile, args.repofile, full_python_version)
    else:
        full_python_version = None
        deps = []

    report = lint(args.packagefile, args.repofile)
    maintainers, versions = (report.maintainer_errors, report.version_errors)
    print(f"{len(maintainers)} packages")
    if not any(err.err for err in maintainers + deps + versions):
        print("No errors found")
        sys.exit(0)

    for err in maintainers + deps + versions:
        if err.err:
            print(f"{err.err}")
            if err.package:
                print(f"{err.package}")
            if err.depends:
                print("  " + "\n  ".join(err.depends))

    if not any(err.err for err in maintainers + deps):
        sys.exit(0)  # currently we allow erronous version numbers

    sys.exit("Error in komodo configuration.")


if __name__ == "__main__":
    lint_main()
