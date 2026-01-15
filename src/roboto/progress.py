# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import typing

import tqdm


class ProgressMonitor(abc.ABC):
    """Progress Monitor for file upload"""

    @abc.abstractmethod
    def update(self, delta: int):
        raise NotImplementedError("update")

    @abc.abstractmethod
    def close(self):
        raise NotImplementedError("close")

    @abc.abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError("is_closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class NoopProgressMonitor(ProgressMonitor):
    """A Noop Progress Monitor"""

    def update(self, uploaded_bytes: int):
        pass

    def close(self):
        pass

    def is_closed(self) -> bool:
        return False


class TqdmProgressMonitor(ProgressMonitor):
    """A Tqdm Progress Monitor"""

    __tqdm: tqdm.tqdm
    __is_closed: bool

    def __init__(
        self,
        total: int,
        desc: str,
        position: int = 0,
        leave: bool = True,
        unit: typing.Optional[str] = "B",
    ):
        tqdm_args = {
            "total": total,
            "desc": desc,
            "bar_format": "{percentage:.1f}%|{bar:25} | {n_fmt}/{total_fmt} | {rate_fmt} | {elapsed} | {desc}",
            "position": position,
            "leave": leave,
        }

        if unit is not None:
            tqdm_args["unit"] = unit
            if unit == "B":
                tqdm_args["unit_scale"] = True
                tqdm_args["unit_divisor"] = 1024

        self.__tqdm = tqdm.tqdm(**tqdm_args)
        self.__is_closed = False

    def update(self, uploaded_bytes: int):
        self.__tqdm.update(uploaded_bytes)

    def close(self):
        self.__tqdm.close()
        self.__is_closed = True

    def is_closed(self) -> bool:
        return self.__is_closed
