# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import typing

import tqdm


class ProgressMonitor(abc.ABC):
    """Receiver of progress reports for a file upload or download, counted in bytes.

    Methods such as :py:meth:`~roboto.domain.files.File.download` and
    :py:meth:`~roboto.domain.files.FileSystem.upload_files` report a transfer's progress through it, passing its
    ``update`` method as the progress callback, so most code never calls it. Used as a context manager, it closes when
    the ``with`` block exits, including on an exception.
    """

    @abc.abstractmethod
    def update(self, delta: int):
        """Record that more of the transfer has completed.

        Args:
            delta: Number of bytes transferred since the previous call, not the running total.
        """
        raise NotImplementedError("update")

    @abc.abstractmethod
    def close(self):
        """Stop reporting progress, marking the transfer as finished."""
        raise NotImplementedError("close")

    @abc.abstractmethod
    def is_closed(self) -> bool:
        """Return whether ``close`` has been called."""
        raise NotImplementedError("is_closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class NoopProgressMonitor(ProgressMonitor):
    """Progress monitor that discards every report.

    Methods such as :py:meth:`~roboto.domain.files.File.download` send their progress reports through it when the
    caller turns off progress output or a transfer has nothing to download, so most code never calls it. Its
    ``is_closed`` always returns ``False``, even after ``close``.
    """

    def update(self, uploaded_bytes: int):
        pass

    def close(self):
        pass

    def is_closed(self) -> bool:
        return False


class TqdmProgressMonitor(ProgressMonitor):
    """Progress monitor that draws a progress bar in the terminal, using the ``tqdm`` library.

    The bar shows the percentage complete, the amount transferred and the total, the transfer rate, the elapsed time,
    and ``desc``.

    Args:
        total: Size of the whole transfer, in ``unit``.
        desc: Label printed at the end of the bar, such as ``"Downloading 3 files"``.
        position: Line on which to draw the bar, counted from 0, so that several bars can show at once.
        leave: Whether the bar stays on screen after the monitor closes.
        unit: Unit of ``total`` and of each update. ``"B"`` shows sizes as kB, MB and up, in steps of 1024. ``None``
            uses ``tqdm``'s default unit, ``"it"``.
    """

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
