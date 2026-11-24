# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import plotly.graph_objects as go  # pants: no-infer-dep
import requests
from tqdm import tqdm


def plot_indicators(indicators, row_count=1):
    """Show numbers as a grid of Plotly indicators, filling each row left to right before starting the next.

    Args:
        indicators: Dictionaries with the keys ``"title"`` and ``"value"``, and optionally ``"suffix"``, text shown
            after the value.
        row_count: Number of rows in the grid. The column count is the fewest that fit every indicator.
    """
    fig = go.Figure()
    col_count = len(indicators) // row_count if len(indicators) % row_count == 0 else len(indicators) // row_count + 1

    for i, indicator in enumerate(indicators):
        col = i % col_count
        row = i // col_count
        x_start, x_end = col / col_count, (col + 1) / col_count
        y_start, y_end = 1 - (row + 1) / row_count, 1 - row / row_count

        fig.add_trace(
            go.Indicator(
                mode="number",
                number={"suffix": indicator.get("suffix", "")},
                title={"text": indicator["title"]},
                value=indicator["value"],
                domain={"x": [x_start, x_end], "y": [y_start, y_end]},
            )
        )

    fig.update_layout(paper_bgcolor="white", margin={"t": 0, "b": 0, "l": 0, "r": 0}, height=250)
    fig.show()


def create_bar_chart(x, y, title, xaxis_title, yaxis_title):
    fig = go.Figure([go.Bar(name="Count", x=x, y=y)])
    fig.update_layout(title=title, xaxis_title=xaxis_title, yaxis_title=yaxis_title, xaxis_tickangle=-45)
    fig.show()


def get_countries_by_reverse_gps(latitude_list, longitude_list):
    """Count the locations in each country, by looking up each coordinate with the Photon reverse geocoding service.

    Makes one request to https://photon.komoot.io per location. A location with a missing or zero latitude or
    longitude, or one the service names no country for, is skipped with a printed message; a location whose request
    returns a status other than 200 is skipped silently.

    Args:
        latitude_list: Latitudes of the locations, in degrees.
        longitude_list: Longitudes of the locations, in degrees, in the same order as ``latitude_list``.

    Returns:
        Number of locations in each country, keyed by the country's English name.

    Raises:
        requests.RequestException: A request fails, such as when the service does not respond within 30 seconds.
    """
    country_dict = {}
    for lat, lon in tqdm(zip(latitude_list, longitude_list), total=len(latitude_list), desc="Processing locations"):
        if lat and lon and lat != 0 and lon != 0:
            url = f"https://photon.komoot.io/reverse?lat={lat}&lon={lon}&lang=en"
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                features = response.json().get("features", [])
                country = features[0].get("properties", {}).get("country") if features else None
                if country:
                    country_dict[country] = country_dict.get(country, 0) + 1
                else:
                    print("Country information not found. This might be a limitation of the API being used.")
        else:
            print("Invalid coordinates or missing data.")
    return country_dict
