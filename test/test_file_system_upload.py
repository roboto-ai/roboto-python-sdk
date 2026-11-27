# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
from unittest import mock

import pytest

from roboto.association import Association
from roboto.domain.files import FileSystem
from roboto.storage import FileService
from roboto.testing import StubRobotoClient


@pytest.mark.parametrize("input_kind", ["list", "tuple", "iterator", "generator"])
@pytest.mark.parametrize("print_progress", [False, True])
def test_upload_files_preserves_iterable(tmp_path: pathlib.Path, input_kind: str, print_progress: bool):
    paths = [tmp_path / "first.bag", tmp_path / "second.bag"]
    for path, data in zip(paths, [b"first", b"second"]):
        path.write_bytes(data)
    inputs = {
        "list": paths,
        "tuple": tuple(paths),
        "iterator": iter(paths),
        "generator": (path for path in paths),
    }
    expected = {path: f"fl_{index}" for index, path in enumerate(paths)}
    destinations = {path: f"logs/{path.name}" for path in paths}
    service = mock.create_autospec(FileService, instance=True)
    service.upload.side_effect = lambda *, files, **kwargs: {path: expected[path] for path in files}
    association = Association.dataset("ds_test")
    filesystem = FileSystem(association, roboto_client=StubRobotoClient(), file_service=service, org_id="og_test")

    with mock.patch("roboto.domain.files.file_system.TqdmProgressMonitor", autospec=True) as progress:
        result = filesystem.upload_files(
            inputs[input_kind],
            file_destination_paths=destinations,
            max_batch_size=1,
            print_progress=print_progress,
            device_id="dv_test",
        )

    assert result == expected
    kwargs = service.upload.call_args.kwargs
    assert list(kwargs["files"]) == paths
    assert kwargs["association"] == association
    assert kwargs["destination_paths"] == destinations
    assert kwargs["batch_size"] == 1
    assert kwargs["device_id"] == "dv_test"
    assert kwargs["caller_org_id"] == "og_test"
    if print_progress:
        progress.assert_called_once_with(total=11, desc="Uploading 2 files")
    else:
        progress.assert_not_called()


@pytest.mark.parametrize("print_progress", [False, True])
def test_upload_files_accepts_empty_iterator(print_progress: bool):
    service = mock.create_autospec(FileService, instance=True)
    service.upload.side_effect = lambda *, files, **kwargs: {path: "fl_test" for path in files}
    filesystem = FileSystem(Association.dataset("ds_test"), roboto_client=StubRobotoClient(), file_service=service)

    assert filesystem.upload_files(iter([]), print_progress=print_progress) == {}
    assert list(service.upload.call_args.kwargs["files"]) == []
