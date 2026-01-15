# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
This is a collection of utilities used by the similarity search example notebook
to format and display the results of a Roboto similarity search.
"""

import base64
import io
import math

from IPython.core.pylabtools import print_figure
from IPython.display import HTML, display
import matplotlib.pyplot
import matplotlib.ticker
import PIL.Image

import roboto
import roboto.analytics

NANO_SEC_PER_SEC = 1e9


def images_frames_to_encoded_gif(image_frames, fps=10, loops=math.inf, resize_factor=0.5) -> str:
    images = [PIL.Image.open(io.BytesIO(frame)) for frame in image_frames]
    resized_images = [
        img.resize(
            (int(img.width * resize_factor), int(img.height * resize_factor)),
            PIL.Image.Resampling.LANCZOS,
        )
        for img in images
    ]

    buffer = io.BytesIO()
    frame_duration_ms = (1 / fps) * 1000

    # Save the images as a GIF
    resized_images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=resized_images[1:],
        duration=frame_duration_ms,
        loop=0 if loops == math.inf else loops,  # 0 means loop forever
    )

    buffer.seek(0)

    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def format_log_time(log_time: int) -> str:
    sec, nano_sec = divmod(log_time, NANO_SEC_PER_SEC)
    return f"{int(sec)}.{int(nano_sec)}"


def plot_match(match: roboto.analytics.Match) -> matplotlib.pyplot.Figure:
    fig, ax = matplotlib.pyplot.subplots()

    fig.set_size_inches(5, 3)
    ax.plot(match.subsequence)
    ax.set_xticks([match.start_time, match.end_time])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda val, _: format_log_time(val)))
    matplotlib.pyplot.setp(ax.spines.values(), lw=0.5)

    return fig


def format_match(
    match: roboto.analytics.Match,
    image_topic_name: str,
    additional_image_context_duration_seconds: float = 1.5,
    roboto_client: roboto.RobotoClient | None = None,
) -> str:
    additional_image_context_duration_ns = int(additional_image_context_duration_seconds * NANO_SEC_PER_SEC)
    FALLBACK_GIF = "R0lGODlhAQABAIAAAAUEBA=="  # 1x1 transparent GIF
    gif = FALLBACK_GIF
    if match.context.file_id is not None:
        try:
            file = roboto.File.from_id(match.context.file_id, roboto_client=roboto_client)
            image_topic = file.get_topic(image_topic_name)
            image_topic_data = image_topic.get_data(
                message_paths_include=["data"],
                start_time=match.start_time - additional_image_context_duration_ns,
                end_time=match.end_time + additional_image_context_duration_ns,
            )
            image_frames = [msg["data"] for msg in image_topic_data]
            gif = images_frames_to_encoded_gif(image_frames)
        except BaseException:
            pass

    fig = plot_match(match)
    plot_image = print_figure(
        fig,
        bbox_inches="tight",
        base64=True,
        dpi=600,
    )
    matplotlib.pyplot.close(fig)

    return f"""\
    <div style="display: flex; align-items: center; margin-bottom: 20px; width: 100%;">
      <div style="flex: 0 0 10%; margin-right: 10px; text-align: center;">
        {round(match.distance, 3)}
      </div>
      <div style="flex: 1; margin-right: 10px; text-align: center;">
        <img
          src="data:image/png;base64,{plot_image}"
          style="height: auto; max-width: 100%; display: inline-block; vertical-align: middle;"
        />
      </div>
      <div style="flex: 1; margin-right: 10px; text-align: center;">
        <img
          src="data:image/gif;base64,{gif}"
          style="height: auto; max-width: 100%; display: inline-block; vertical-align: middle;"
        />
      </div>
      <div style="flex: 0 0 10%; margin-right: 10px; text-align: center;">
        <a
          href="https://app.roboto.ai/files/{match.context.file_id}"
          target="_blank"
        >
          View in Roboto
        </a>
      </div>
    </div>
    """


def print_match_results(
    matches: list[roboto.analytics.Match],
    image_topic: str,
    additional_image_context_duration_seconds: float = 1.5,
    roboto_client: roboto.RobotoClient | None = None,
) -> None:
    HEADER_HTML = """\
    <div style="display: flex; align-items: center; margin-bottom: 10px; width: 100%; font-weight: bold;">
        <div style="flex: 0 0 10%; margin-right: 10px; text-align: center;">Distance</div>
        <div style="flex: 1; margin-right: 10px; text-align: center;">Matching sequence</div>
        <div style="flex: 1; text-align: center;">Camera topic</div>
        <div style="flex: 0 0 10%; margin-right: 10px; text-align: center;">Link</div>
    </div>
    """
    display(HTML(HEADER_HTML))

    for match in matches:
        display(
            HTML(
                format_match(
                    match,
                    image_topic,
                    additional_image_context_duration_seconds,
                    roboto_client,
                )
            )
        )
