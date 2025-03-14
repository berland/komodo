import argparse
import os
from pathlib import Path
from typing import Dict, List, Mapping, MutableSet, Sequence, Union

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError

from .komodo_error import KomodoError, KomodoException


def load_yaml_from_string(value: str) -> dict:
    try:
        return YAML().load(value)
    except DuplicateKeyError as duplicate_key_error:
        raise SystemExit(duplicate_key_error) from None


class YamlFile(argparse.FileType):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__("r", *args, **kwargs)

    def __call__(self, value):
        file_handle = super().__call__(value)
        yml = load_yaml_from_string(file_handle)
        file_handle.close()
        return yml


class ReleaseFile(YamlFile):
    """Return the data from 'release' YAML file, but validate it first."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content: dict = None

    def __call__(self, value: str):
        yml: dict = super().__call__(value)
        self.validate_release_file(yml)
        self.content: dict = yml
        return self

    @classmethod
    def from_yaml_string(cls, value: str):
        yml = load_yaml_from_string(value)
        return cls.from_dictionary(yml)

    @classmethod
    def from_dictionary(cls, value: dict):
        s = cls()
        s.validate_release_file(value)
        s.content = value
        return s

    @staticmethod
    def validate_release_file(release_file_content: Mapping) -> None:
        message = (
            "The file you provided does not appear to be a release file "
            "produced by komodo. It may be a repository file. Release files "
            "have a format like the following:\n\n"
            'python: 3.8.6-builtin\nsetuptools: 68.0.0\nwheel: 0.40.0\nzopfli: "0.3"'
        )
        assert isinstance(release_file_content, Mapping), message
        errors = []
        for package_name, package_version in release_file_content.items():
            error = Package.validate_package_entry_with_errors(
                package_name,
                package_version,
            )
            errors.extend(error)
        handle_validation_errors(errors, message)


class ReleaseMatrixFile(YamlFile):
    """Return the data from 'release' YAML file, but validate it first."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content: dict = None

    def __call__(self, value: str):
        yml: dict = super().__call__(value)
        self.validate_release_matrix_file(yml)
        self.content: dict = yml
        return self

    @classmethod
    def from_yaml_string(cls, value: bytes):
        yml = load_yaml_from_string(value)
        cls.validate_release_matrix_file(yml)
        release_matrix_file = cls()
        release_matrix_file.content: dict = yml
        return release_matrix_file

    @staticmethod
    def validate_release_matrix_file(release_matrix_file_content: Mapping) -> None:
        message = (
            "The file you provided does not appear to be a release matrix file "
            "produced by komodo. It may be a repository file. Release matrix files "
            "have a format like the following:\n\n"
            "python: 3.8.6-builtin\nsetuptools: 68.0.0\nwheel:\n  rhel7: 0.40.0\n  rhel8: 0.40.1"
        )
        assert isinstance(release_matrix_file_content, dict), message
        errors = set()
        for package_name, package_version in release_matrix_file_content.items():
            _recursive_validate_version_matrix(package_version, package_name, errors)
        handle_validation_errors(errors, message)


class ReleaseDir:
    def __call__(self, value: str) -> Dict[str, YamlFile]:
        if not os.path.isdir(value):
            raise NotADirectoryError(value)
        result = {}
        for yaml_file in Path(value).glob("*.yml"):
            result[yaml_file.name.replace(".yml", "")] = ReleaseFile()(
                yaml_file
            ).content
        return result


class ManifestFile(YamlFile):
    """Return the data from 'manifest' YAML, but validate it first."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content: dict = None

    def __call__(self, value: str) -> Dict[str, Dict[str, str]]:
        yml = super().__call__(value)
        self.validate_manifest_file(yml)
        return yml

    @staticmethod
    def validate_manifest_file(manifest_file_content: dict):
        message = (
            "The file you provided does not appear to be a manifest file "
            "produced by komodo. It may be a release file. Manifest files "
            "have a format like the following:\n\n"
            "python:\n  maintainer: foo@example.com\n  version: 3-builtin\n"
            "treelib:\n  maintainer: foo@example.com\n  version: 1.6.1\n"
        )
        assert isinstance(manifest_file_content, dict), message
        errors = []
        for package_name, metadata in manifest_file_content.items():
            if not isinstance(metadata, dict):
                errors.append(f"Invalid metadata for package '{package_name}'")
                continue
            if not isinstance(metadata["version"], str):
                errors.append(
                    f"Invalid version type in metadata for package '{package_name}'",
                )
        handle_validation_errors(errors, message)


class RepositoryFile(YamlFile):
    """Return the data from 'repository' YAML, but validate it first."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content: dict = None

    def __call__(self, value: str):
        self.content: dict = super().__call__(value)
        self.validate_repository_file()
        return self

    @classmethod
    def from_yaml_string(cls, value: str):
        yml = load_yaml_from_string(value)
        return cls.from_dictionary(yml)

    @classmethod
    def from_dictionary(cls, value: dict):
        s = cls()
        s.content = value
        s.validate_repository_file()
        return s

    def validate_package_entry(
        self,
        package_name: str,
        package_version: str,
    ) -> KomodoError:
        repository_entries = self.content
        if package_name not in repository_entries:
            for real_packagename in [
                lowercase_pkg
                for lowercase_pkg in repository_entries
                if lowercase_pkg.lower() == package_name.lower()
            ]:
                msg = f"Package '{package_name}' not found in repository. Did you mean '{real_packagename}'?"
                raise KomodoException(
                    msg,
                )
            msg = f"Package '{package_name}' not found in repository"
            raise KomodoException(msg)
        if package_version not in repository_entries[package_name]:
            if f"v{package_version}" in repository_entries[package_name]:
                msg = f"Version '{package_version}' of package '{package_name}' not found in repository. Did you mean 'v{package_version}'?"
                raise KomodoException(
                    msg,
                )
            msg = f"Version '{package_version}' of package '{package_name}' not found in repository. Did you mean '{next(iter(repository_entries[package_name].keys()))}'?"
            raise KomodoException(
                msg,
            )

    def lint_maintainer(self, package, version) -> KomodoError:
        repository_entries = self.content
        try:
            self.validate_package_entry(package, version)
        except KomodoException as komodo_exception:
            raise KomodoException(
                KomodoError(
                    package=package, version=version, err=str(komodo_exception)
                ),
            ) from komodo_exception
        return KomodoError(
            package=package,
            version=version,
            maintainer=repository_entries[package][version]["maintainer"],
        )

    def validate_repository_file(self) -> None:
        repository_file_content: dict = self.content
        message = (
            "The file you provided does not appear to be a repository file "
            "produced by komodo. It may be a release file. Repository files "
            "have a format like the following:\n\n"
            "pytest-runner:\n  6.0.0:\n    make: pip\n    "
            "maintainer: scout\n    depends:\n      - wheel\n      - "
            """setuptools\n      - python\n\npython:\n  "3.8":\n    ..."""
        )
        assert isinstance(repository_file_content, dict), message
        errors = []
        for package_name, versions in repository_file_content.items():
            try:
                Package.validate_package_name(package_name)
                if not isinstance(versions, dict):
                    errors.append(
                        f"Versions of package '{package_name}' is not formatted"
                        f" correctly ({versions})",
                    )
                    continue
                validation_errors = self.validate_versions(package_name, versions)
                if validation_errors:
                    errors.extend(validation_errors)
            except (ValueError, TypeError) as value_or_type_error:
                errors.append(str(value_or_type_error))

        handle_validation_errors(errors, message)

    def validate_versions(self, package_name: str, versions: dict) -> List[str]:
        """Validates versions-dictionary of a package and returns a list of error messages."""
        errors = []
        for version, version_metadata in versions.items():
            Package.validate_package_version(package_name, version)
            make_errors = Package.validate_package_make_with_errors(
                package_name,
                version,
                version_metadata.get("make"),
            )
            errors.extend(make_errors)
            maintainer_errors = Package.validate_package_maintainer_with_errors(
                package_name,
                version,
                version_metadata.get("maintainer"),
            )
            errors.extend(maintainer_errors)
            for (
                package_property,
                package_property_value,
            ) in version_metadata.items():
                validation_errors = self.validate_package_properties(
                    package_name,
                    version,
                    package_property,
                    package_property_value,
                )
                errors.extend(validation_errors)
        return errors

    def validate_package_properties(
        self,
        package_name: str,
        package_version: str,
        package_property: str,
        package_property_value: str,
    ) -> List[str]:
        """Validates package properties of the specified package
        and returns a list of error messages.
        """
        pre_checked_properties = ["make", "maintainer"]
        errors = []
        if package_property in pre_checked_properties:
            return errors
        if package_property == "depends":
            if not isinstance(package_property_value, list):
                errors.append(
                    f"Dependencies for package {package_name} have"
                    f" invalid type {package_property_value}",
                )
                return errors
            for dependency in package_property_value:
                if not isinstance(dependency, str):
                    errors.append(
                        f"Package {package_name} version {package_version} has"
                        f" invalid dependency type({dependency})",
                    )
                    continue
                if dependency not in self.content:
                    errors.append(
                        f"Dependency '{dependency}' not found for"
                        f" package '{package_name}'",
                    )
        else:
            try:
                Package.validate_package_property_type(
                    package_name,
                    package_version,
                    package_property,
                    package_property_value,
                )
            except (ValueError, TypeError) as value_or_type_error:
                errors.append(str(value_or_type_error))
        return errors


class UpgradeProposalsFile(YamlFile):
    """Return the data from 'upgrade_proposals' YAML, but validate it first."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content: dict = None

    def __call__(self, value: str) -> Dict[str, Dict[str, str]]:
        yml = super().__call__(value)
        self.validate_upgrade_proposals_file(yml)
        self.content: dict = yml
        return self

    @classmethod
    def from_yaml_string(cls, value):
        yml = load_yaml_from_string(value)
        return cls.from_dictionary(yml)

    @classmethod
    def from_dictionary(cls, yml):
        s = cls()
        s.validate_upgrade_proposals_file(yml)
        s.content = yml
        return s

    def validate_upgrade_key(self, upgrade_key: str) -> None:
        assert upgrade_key in self.content, (
            f"No section for this release ({upgrade_key}) in upgrade_proposals.yml"
        )

    @staticmethod
    def validate_upgrade_proposals_file(upgrade_proposals_file_content: dict) -> None:
        message = (
            "The file you provided does not appear to be an upgrade_proposals file"
            " produced by komodo. It may be a release file. Upgrade_proposals files"
            ' have a format like the following:\n2022-08:\n2022-09:\n  python: "3.9"\n'
            '  zopfli:\n    rhel7: "0.3"\n    rhel8: 0.2.9\n  libecalc: 8.2.9'
        )
        errors = []
        assert isinstance(upgrade_proposals_file_content, dict), message
        for (
            release_version,
            packages_to_upgrade,
        ) in upgrade_proposals_file_content.items():
            if not isinstance(release_version, str):
                errors.append(
                    f"Release version ({release_version}) is not of type string",
                )
                continue
            if packages_to_upgrade is None:
                continue
            if not isinstance(packages_to_upgrade, dict):
                errors.append(
                    "New package upgrades have to be listed in dictionary format"
                    f" ({packages_to_upgrade})",
                )
                continue
            errors = set()
            for package_name, package_version in packages_to_upgrade.items():
                _recursive_validate_version_matrix(
                    package_version, package_name, errors
                )
        handle_validation_errors(errors, message)


class PackageStatusFile(YamlFile):
    """Return the data from 'package_status' YAML, but validate it first."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.content: dict = None

    def __call__(self, value: str):
        yml = super().__call__(value)
        self.content: dict = yml
        self.validate_package_status_file()
        return self

    @classmethod
    def from_yaml_string(cls, value: str):
        yml = load_yaml_from_string(value)
        return cls.from_dictionary(yml)

    @classmethod
    def from_dictionary(cls, value: dict):
        s = cls()
        s.content = value
        s.validate_package_status_file()
        return s

    def validate_package_status_file(self) -> None:
        package_status = self.content
        message = (
            "The file you provided does not appear to be a package_status file"
            " produced by komodo. It may be a release file. Package_status files have"
            " a format like the following:\n\nzopfli:\n  visibility:"
            " private\npython:\n  visibility: public\n  maturity: stable\n "
            " importance: high"
        )

        assert isinstance(package_status, dict), message

        errors = []
        for package_name, status in package_status.items():
            try:
                Package.validate_package_name(package_name)
                if not isinstance(status, dict):
                    errors.append(f"Invalid package data for {package_name} - {status}")
                    continue
                Package.validate_package_visibility(
                    package_name,
                    status.get("visibility"),
                )
            except (ValueError, TypeError) as value_or_type_error:
                errors.append(str(value_or_type_error))
                continue
            visibility = status["visibility"]
            if visibility == "public":
                maturity_errors = Package.validate_package_maturity_with_errors(
                    package_name,
                    status.get("maturity"),
                )
                errors.extend(maturity_errors)

                importance_errors = Package.validate_package_importance_with_errors(
                    package_name,
                    status.get("importance"),
                )
                errors.extend(importance_errors)

        handle_validation_errors(errors, message)


class Package:
    VALID_VISIBILITIES = ["public", "private", "private-plugin"]
    VALID_IMPORTANCES = ["low", "medium", "high"]
    VALID_MATURITIES = ["experimental", "stable", "deprecated"]
    VALID_MAKES = ["cmake", "sh", "pip", "rsync", "noop", "download"]

    @staticmethod
    def validate_package_name(package_name: str) -> None:
        if isinstance(package_name, str):
            return
        msg = f"Package name ({package_name}) should be of type string"
        raise TypeError(msg)

    @staticmethod
    def validate_package_version(
        package_name: Union[str, None],
        package_version: str,
        is_matrix_file: bool = False,
    ) -> None:
        if isinstance(package_version, str) or (
            is_matrix_file and package_version is None
        ):
            return
        else:
            msg = (
                f"Package '{package_name}' has invalid version type ({package_version})"
            )
            raise TypeError(
                msg,
            )

    @staticmethod
    def validate_package_entry(
        package_name: str, package_version, is_matrix_file=False
    ) -> None:
        Package.validate_package_name(package_name)
        Package.validate_package_version(package_name, package_version, is_matrix_file)

    @staticmethod
    def validate_package_entry_with_errors(
        package_name: str,
        package_version: str,
        is_matrix_file: bool = False,
    ) -> List[str]:
        """Validates package name and version, and returns a list of error messages."""
        errors = []
        try:
            Package.validate_package_entry(
                package_name, package_version, is_matrix_file
            )
        except (ValueError, TypeError) as value_or_type_error:
            errors.append(str(value_or_type_error))
        return errors

    @staticmethod
    def validate_package_importance(package_name: str, package_importance: str) -> None:
        if isinstance(package_importance, str):
            if package_importance in Package.VALID_IMPORTANCES:
                return
            msg = f"{package_name} has invalid importance value ({package_importance})"
            raise ValueError(
                msg,
            )
        msg = f"{package_name} has invalid importance type ({package_importance})"
        raise TypeError(
            msg,
        )

    @staticmethod
    def validate_package_importance_with_errors(
        package_name,
        package_importance: str,
    ) -> List[str]:
        """Validates package importance of a package and returns a list of error messages."""
        errors = []
        try:
            Package.validate_package_importance(package_name, package_importance)
        except (ValueError, TypeError) as value_or_type_error:
            errors.append(str(value_or_type_error))
        return errors

    @staticmethod
    def validate_package_visibility(package_name: str, package_visibility: str) -> None:
        if isinstance(package_visibility, str):
            if package_visibility in Package.VALID_VISIBILITIES:
                return
            msg = f"Package '{package_name}' has invalid visibility value ({package_visibility})"
            raise ValueError(
                msg,
            )
        msg = f"Package '{package_name}' has invalid visibility type ({package_visibility})"
        raise TypeError(
            msg,
        )

    @staticmethod
    def validate_package_maturity(package_name: str, package_maturity: str) -> None:
        if isinstance(package_maturity, str):
            if package_maturity in Package.VALID_MATURITIES:
                return
            msg = f"Package '{package_name}' has invalid maturity value ({package_maturity})"
            raise ValueError(
                msg,
            )
        msg = f"Package '{package_name}' has invalid maturity type ({package_maturity})"
        raise TypeError(
            msg,
        )

    @staticmethod
    def validate_package_maturity_with_errors(
        package_name: str,
        package_maturity: str,
    ) -> List[str]:
        """Validates package maturity of a package and returns a list of error messages."""
        errors = []
        try:
            Package.validate_package_maturity(package_name, package_maturity)
        except (ValueError, TypeError) as value_or_type_error:
            errors.append(str(value_or_type_error))
        return errors

    @staticmethod
    def validate_package_make(
        package_name: str,
        package_version: str,
        package_make: str,
    ) -> None:
        if isinstance(package_make, str):
            if package_make in Package.VALID_MAKES:
                return
            msg = f"Package '{package_name}' version {package_version} has invalid make value ({package_make})"
            raise ValueError(
                msg,
            )
        msg = f"Package '{package_name}' version {package_version} has invalid make type ({package_make})"
        raise TypeError(
            msg,
        )

    @staticmethod
    def validate_package_make_with_errors(
        package_name: str,
        package_version: str,
        package_make: str,
    ) -> List[str]:
        """Validates make of a package and returns a list of error messages."""
        errors = []
        try:
            Package.validate_package_make(package_name, package_version, package_make)
        except (ValueError, TypeError) as value_or_type_error:
            errors.append(str(value_or_type_error))
        return errors

    @staticmethod
    def validate_package_maintainer(
        package_name: str,
        package_version: str,
        package_maintainer: str,
    ) -> None:
        if isinstance(package_maintainer, str):
            return
        msg = f"Package '{package_name}' version {package_version} has invalid maintainer type ({package_maintainer})"
        raise TypeError(
            msg,
        )

    @staticmethod
    def validate_package_maintainer_with_errors(
        package_name: str,
        package_version: str,
        package_maintainer: str,
    ) -> List[str]:
        """Validates maintainer of a package and returns a list of error messages."""
        errors = []
        try:
            Package.validate_package_maintainer(
                package_name,
                package_version,
                package_maintainer,
            )
        except TypeError as type_error:
            errors.append(str(type_error))
        return errors

    @staticmethod
    def validate_package_source(
        package_name: str,
        package_version: str,
        package_source: str,
    ) -> None:
        if isinstance(package_source, (str, type(None))):
            return
        msg = f"Package '{package_name}' version {package_version} has invalid source type ({package_source})"
        raise TypeError(
            msg,
        )

    @staticmethod
    def validate_package_source_with_errors(
        package_name: str,
        package_version: str,
        package_source: str,
    ) -> List[str]:
        """Validates source of a package and returns a list of error messages."""
        errors = []
        try:
            Package.validate_package_source(
                package_name,
                package_version,
                package_source,
            )
        except TypeError as type_error:
            errors.append(str(type_error))
        return errors

    @staticmethod
    def validate_package_property_type(
        package_name: str,
        package_version: str,
        package_property: str,
        package_property_value: str,
    ):
        if not isinstance(package_property, str):
            msg = f"Package '{package_name}' version has invalid property type ({package_property})"
            raise TypeError(
                msg,
            )
        if not isinstance(package_property_value, str):
            msg = f"Package '{package_name}' version '{package_version}' property '{package_property}' has invalid property value type ({package_property_value})"
            raise TypeError(
                msg,
            )


def handle_validation_errors(errors: Sequence[str], message: str):
    if errors:
        raise SystemExit("\n".join([*errors, message]))


def load_package_status_file(package_status_string: str):
    return PackageStatusFile.from_yaml_string(package_status_string)


def load_repository_file(repository_file_string):
    return RepositoryFile.from_yaml_string(repository_file_string)


def _recursive_validate_version_matrix(
    version_or_matrix: Union[dict, str], package_name: str, errors: MutableSet
) -> None:
    if isinstance(version_or_matrix, Mapping):
        for nested_version_or_matrix in version_or_matrix.values():
            _recursive_validate_version_matrix(
                nested_version_or_matrix, package_name, errors
            )
    else:
        new_errors = Package.validate_package_entry_with_errors(
            package_name,
            version_or_matrix,
            is_matrix_file=True,
        )
        for new_error in new_errors:
            errors.add(new_error)
