# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
    """Decoded video frame, paired with the log time of the message that held its encoded bytes.

    ``decode_stream`` builds these; you do not construct one directly. The pixels stay in the decoder's format until
    ``to_image`` or ``to_ndarray`` converts them, so a frame you skip is never converted.
    """

    def __init__(self, log_time: int, frame: av.VideoFrame) -> None:
        self.__log_time = log_time
        self.__frame = frame

    @property
    def log_time(self) -> int:
        """Log time of the message that held this frame's encoded bytes, in nanoseconds since the Unix epoch."""
        return self.__log_time

    @property
    def is_keyframe(self) -> bool:
        """Whether this frame is a keyframe, which decodes without any earlier frame."""
        return bool(self.__frame.key_frame)

    @property
    def width(self) -> int:
        """Width of the frame, in pixels."""
        return int(self.__frame.width)

    @property
    def height(self) -> int:
        """Height of the frame, in pixels."""
        return int(self.__frame.height)

    def to_image(self) -> PIL.Image.Image:
        """Return the frame's pixels as a ``PIL.Image.Image`` in RGB mode.

        Raises:
            ImportError: The ``roboto[video]`` extra is not installed.
        """
        import_optional_dependency("PIL", "video")
        return self.__frame.to_image()

    def to_ndarray(self) -> numpy.ndarray:
        """Return the frame's pixels as a ``numpy.ndarray`` of shape ``(height, width, 3)``, in ``uint8`` RGB.

        Raises:
            ImportError: The ``roboto[video]`` extra is not installed.
        """
        import_optional_dependency("numpy", "video")
        return self.__frame.to_ndarray(format="rgb24")


def decode_stream(
    encoded_frames: collections.abc.Iterable[tuple[int, bytes]],
    codec: VideoCodec,
) -> collections.abc.Generator[DecodedVideoFrame, None, None]:
    """Yield the frames decoded from a stream of encoded frames of one codec.

    A frame other than a keyframe decodes only after the frames back to the keyframe before it, so the frames before
    the first keyframe are skipped. A frame that fails to decode is skipped with a logged warning, and decoding
    continues with the next frame. Each call starts a new decoder, so to decode several separate streams in one call,
    each must begin with a keyframe.

    Args:
        encoded_frames: ``(log_time, data)`` pairs in ascending log-time order, where ``log_time`` is in nanoseconds
            since the Unix epoch and ``data`` is one encoded frame in the codec's bitstream format.

    Yields:
        One ``DecodedVideoFrame`` for each frame that decodes, carrying the log time of the message that held it.

    Raises:
        ImportError: The ``roboto[video]`` extra is not installed. It surfaces on the first iteration.

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
    # Each packet's pts is its index in log_times. The decoder copies a packet's pts onto the frame decoded from it,
    # which can come out several packets later or only at the flush, so frame.pts finds that frame's log time.
    log_times: list[int] = []
    reached_keyframe = False

    def decoded_frames(packet: typing.Optional[av.Packet]) -> list[av.VideoFrame]:
        try:
            return codec_context.decode(packet)
        except av_module.FFmpegError:
            # Drops only this packet, or at the flush the frames still buffered, so one corrupt frame does not end
            # the stream. Exceptions other than FFmpegError propagate.
            log_time = log_times[packet.pts] if packet is not None and packet.pts is not None else None
            logger.warning("Skipping undecodable %s frame (log_time=%s)", codec.name, log_time)
            return []

    def to_decoded_frame(frame: av.VideoFrame) -> DecodedVideoFrame:
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
    """Yield the frames decoded from a stream of encoded H.264 frames.

    Calls ``decode_stream`` with the ``H264`` codec, so its skipping of frames before the first keyframe and of frames
    that fail to decode applies here too.

    Args:
        encoded_frames: ``(log_time, data)`` pairs in ascending log-time order, where ``log_time`` is in nanoseconds
            since the Unix epoch and ``data`` is one H.264 frame in Annex B framing, where a start code
            (``00 00 01`` or ``00 00 00 01``) precedes each unit of the frame.

    Yields:
        One ``DecodedVideoFrame`` for each frame that decodes, carrying the log time of the message that held it.

    Raises:
        ImportError: The ``roboto[video]`` extra is not installed. It surfaces on the first iteration.

    Examples:
        >>> from roboto.experimental.video import decode_h264_stream
        >>> for frame in decode_h264_stream(encoded_frames):  # doctest: +SKIP
        ...     frame.to_image().save(f"frame-{frame.log_time}.jpeg")
    """
    return decode_stream(encoded_frames, H264)
