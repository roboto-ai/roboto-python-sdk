# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap


class Science(TemplatedExternalTool):
    options_scope = "science"
    help = softwrap("""A high level tool to build scies with.""")

    default_version = "0.15.1"
    default_known_versions = [
        "0.15.1|linux_arm64|928dddc37d98117b4310d7779b677f04ce25839898e947531b3db9bf4b473d70|9444039",
        "0.15.1|linux_x86_64|a1b7986a8db40495ffdd7a8e8a20ed6d02f3213f8e2bdd5f3c9f4ce48dd8265f|10948381",
        "0.15.1|macos_arm64|51aec4fcea783dddc78d54aaa07bbb8a3002d3a0308c75bd12f27eadbc53b3d1|8880820",
        "0.15.1|macos_x86_64|d57b503c4e1073d7c89c12719b6fca43ffc956e2dfdcd68df180d5899c01b885|9617696",
    ]

    default_url_template = (
        "https://github.com/a-scie/lift/releases/download/v{version}/science-{platform}"
    )

    default_url_platform_mapping = {
        "linux_arm64": "linux-aarch64",
        "linux_x86_64": "linux-x86_64",
        "macos_arm64": "macos-aarch64",
        "macos_x86_64": "macos-x86_64",
    }

    # args = ArgsListOption(example="--release")


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *Science.rules(),  # type: ignore[call-arg]
    )
