# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
from typing import Any, Optional

import tqdm


class ProgressMonitor(abc.ABC):
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


class ProgressMonitorFactory(abc.ABC):
    __ctx: dict[str, Any]

    def __init__(self, ctx: Optional[dict[str, Any]] = None):
        self.__ctx = ctx or {}

    @abc.abstractmethod
    def upload_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        raise NotImplementedError("upload_monitor")

    @abc.abstractmethod
    def download_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        raise NotImplementedError("download_monitor")

    def get_context(self) -> dict[str, Any]:
        return self.__ctx


class NoopProgressMonitor(ProgressMonitor):
    def update(self, uploaded_bytes: int):
        pass

    def close(self):
        pass

    def is_closed(self) -> bool:
        return False


class NoopProgressMonitorFactory(ProgressMonitorFactory):
    def upload_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        return NoopProgressMonitor()

    def download_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        return NoopProgressMonitor()


class TqdmProgressMonitor(ProgressMonitor):
    __tqdm: tqdm.tqdm
    __is_closed: bool
    __total: int
    __auto_close: bool
    __uploaded_bytes: int

    def __init__(
        self,
        total: int,
        desc: str,
        position: int = 0,
        leave: bool = True,
        unit: Optional[str] = "B",
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


class TqdmProgressMonitorFactory(ProgressMonitorFactory):
    __monitors: list[Optional[ProgressMonitor]]

    def __init__(
        self,
        concurrency: int = 1,
        ctx: Optional[dict[str, Any]] = None,
        unit: Optional[str] = "B",
    ):
        super().__init__(ctx=ctx)
        self.__monitors = [None] * concurrency

    def __first_available_slot(self) -> Optional[int]:
        for idx in range(len(self.__monitors)):
            if self.__monitors[idx] is None or self.__monitors[idx].is_closed():  # type: ignore[union-attr]
                return idx

        return None

    def __any_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        # This for sure is not fully threadsafe, but it 100% works for single threading and
        # _mostly_ works for multithreading.
        slot = self.__first_available_slot()
        if slot is None:
            raise ValueError("Number of concurrent monitors is exceeding concurrency!")

        progress_monitor_args = {
            "total": size,
            "desc": f"Src: {source}",
            "position": slot,
            "leave": len(self.__monitors) == 1,
        }

        if kwargs:
            progress_monitor_args.update(**kwargs)

        monitor = TqdmProgressMonitor(**progress_monitor_args)  # type: ignore[arg-type]

        self.__monitors[slot] = monitor

        return monitor

    def upload_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        return self.__any_monitor(source=source, size=size, kwargs=kwargs)

    def download_monitor(
        self, source: str, size: int, kwargs: Optional[dict[str, Any]] = None
    ) -> ProgressMonitor:
        return self.__any_monitor(source=source, size=size, kwargs=kwargs)
