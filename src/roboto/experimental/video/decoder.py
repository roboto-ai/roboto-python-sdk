# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""GOP-aware compressed-video stream decoding backed by PyAV.

Compressed-video topics store one encoded frame per message. Unlike still
images, those frames are not independently decodable: a delta frame is only
meaningful relative to the frames since the preceding keyframe (its group of
pictures, "GOP"). The decoder here consumes an in-order stream of encoded
frames, maintains that state, and yields decoded frames mapped back to their
source messages' log times.

The decoder is codec-agnostic: a :py:class:`~roboto.experimental.video.codec.VideoCodec`
supplies the PyAV decoder name and keyframe predicate, so H.265/VP9/AV1 reuse
this GOP machinery unchanged (see :py:mod:`.codec`).

Requires the ``roboto[video]`` extra (PyAV; Pillow/numpy for the pixel
accessors on :py:class:`DecodedVideoFrame`).
"""

from __future__ import annotations

import collections.abc
import typing

from ...compat import import_optional_dependency
from ...logging import default_logger
from .codec import H264, VideoCodec

if typing.TYPE_CHECKING:
    import av  # pants: no-infer-dep
    import numpy  # pants: no-infer-dep
    import PIL.Image  # pants: no-infer-dep

logger = default_logger()


class DecodedVideoFrame:
    """A decoded video frame paired with the log time of its source message.

    Pixel data stays in the decoder's native representation until one of the
    accessors is called, so frames that a caller samples past are never
    converted.
    """

    def __init__(self, log_time: int, frame: av.VideoFrame) -> None:
        self.__log_time = log_time
        self.__frame = frame

    @property
    def log_time(self) -> int:
        """Log time (nanoseconds since Unix epoch) of the message this frame came from."""
        return self.__log_time

    @property
    def is_keyframe(self) -> bool:
        """Whether this frame is a keyframe (clean decoder entry point)."""
        return bool(self.__frame.key_frame)

    @property
    def width(self) -> int:
        """Frame width in pixels."""
        return int(self.__frame.width)

    @property
    def height(self) -> int:
        """Frame height in pixels."""
        return int(self.__frame.height)

    def to_image(self) -> PIL.Image.Image:
        """Convert the frame to a PIL RGB image.

        Returns:
            The frame's pixels as a :py:class:`PIL.Image.Image` in RGB mode.

        Raises:
            ImportError: If Pillow is not installed (``roboto[video]``).
        """
        import_optional_dependency("PIL", "video")
        return self.__frame.to_image()

    def to_ndarray(self) -> numpy.ndarray:
        """Convert the frame to an ``(height, width, 3)`` uint8 RGB array.

        Returns:
            The frame's pixels as a numpy array in RGB channel order.

        Raises:
            ImportError: If numpy is not installed (``roboto[video]``).
        """
        import_optional_dependency("numpy", "video")
        return self.__frame.to_ndarray(format="rgb24")


def decode_stream(
    encoded_frames: collections.abc.Iterable[tuple[int, bytes]],
    codec: VideoCodec,
) -> collections.abc.Generator[DecodedVideoFrame, None, None]:
    """Decode an in-order stream of encoded frames of a single codec.

    Frames before the first keyframe are skipped — without the preceding GOP
    state no decoder can render them. Individually corrupt frames are likewise
    skipped (with a warning) and decoding resumes at the next decodable frame.
    A fresh decoder session is created per call; concatenating unrelated
    streams into one call is only valid if each starts with a keyframe.

    Args:
        encoded_frames: ``(log_time, data)`` pairs in ascending log-time order,
            where ``data`` is one encoded frame in ``codec``'s bitstream format.
        codec: The codec of every frame in ``encoded_frames``; supplies the
            PyAV decoder name and the keyframe predicate.

    Yields:
        One :py:class:`DecodedVideoFrame` per decodable input frame, carrying
        the source message's log time.

    Raises:
        ImportError: If PyAV is not installed (``roboto[video]``).

    Examples:
        >>> from roboto.experimental.video.codec import H264
        >>> from roboto.experimental.video import decode_stream
        >>> for frame in decode_stream(encoded_frames, H264):  # doctest: +SKIP
        ...     frame.to_image().save(f"frame-{frame.log_time}.jpeg")
    """
    av_module = import_optional_dependency("av", "video")

    codec_context = av_module.CodecContext.create(codec.pyav_codec_name, "r")
    if codec.decoder_thread_count is not None:
        codec_context.thread_count = codec.decoder_thread_count
    # Input packets are stamped with their fed-order index as pts so decoded
    # frames (which the codec may emit later, e.g. on flush) map back to their
    # source message's log time regardless of internal reordering.
    log_times: list[int] = []
    reached_keyframe = False

    def decoded_frames(packet: typing.Optional[av.Packet]) -> list[av.VideoFrame]:
        try:
            return codec_context.decode(packet)
        except av_module.FFmpegError:
            log_time = log_times[packet.pts] if packet is not None and packet.pts is not None else None
            logger.warning("Skipping undecodable %s frame (log_time=%s)", codec.name, log_time)
            return []

    def to_decoded_frame(frame: av.VideoFrame) -> DecodedVideoFrame:
        # We stamp every fed packet's pts with its index into log_times (below), and PyAV
        # echoes that pts onto the decoded frame, so frame.pts is always a valid index back.
        if frame.pts is None:
            raise ValueError("decoded frame is missing the pts stamped on its packet")
        return DecodedVideoFrame(log_time=log_times[frame.pts], frame=frame)

    for log_time, data in encoded_frames:
        if not reached_keyframe:
            if not codec.is_keyframe(data):
                continue
            reached_keyframe = True
        packet = av_module.Packet(data)
        packet.pts = len(log_times)
        packet.dts = len(log_times)
        log_times.append(log_time)
        for frame in decoded_frames(packet):
            yield to_decoded_frame(frame)

    for frame in decoded_frames(None):
        yield to_decoded_frame(frame)


def decode_h264_stream(
    encoded_frames: collections.abc.Iterable[tuple[int, bytes]],
) -> collections.abc.Generator[DecodedVideoFrame, None, None]:
    """Decode an in-order stream of Annex B-framed H.264 frames.

    Thin wrapper over :py:func:`decode_stream` bound to the H.264 codec; see it
    for the GOP, corruption-recovery, and log-time-mapping semantics.

    Args:
        encoded_frames: ``(log_time, data)`` pairs in ascending log-time order,
            where ``data`` is one Annex B-framed H.264 frame.

    Yields:
        One :py:class:`DecodedVideoFrame` per decodable input frame, carrying
        the source message's log time.

    Raises:
        ImportError: If PyAV is not installed (``roboto[video]``).

    Examples:
        >>> from roboto.experimental.video import decode_h264_stream
        >>> for frame in decode_h264_stream(encoded_frames):  # doctest: +SKIP
        ...     frame.to_image().save(f"frame-{frame.log_time}.jpeg")
    """
    return decode_stream(encoded_frames, H264)
