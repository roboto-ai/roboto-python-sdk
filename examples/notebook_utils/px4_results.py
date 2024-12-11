# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import plotly.graph_objects as go
import requests
from tqdm import tqdm

def plot_indicators(indicators, row_count=1):
    """
    Plot multiple indicators in a single layout.
    
    Parameters:
        indicators (list): A list of dictionaries, each containing 'title', 'value', and optionally 'suffix'.
        row_count (int): Number of rows in the layout (default is 1 for a single row).
    """
    fig = go.Figure()
    col_count = len(indicators) // row_count if len(indicators) % row_count == 0 else len(indicators) // row_count + 1
    
    for i, indicator in enumerate(indicators):
        col = i % col_count
        row = i // col_count
        x_start, x_end = col / col_count, (col + 1) / col_count
        y_start, y_end = 1 - (row + 1) / row_count, 1 - row / row_count
        
        fig.add_trace(go.Indicator(
            mode="number",
            number={'suffix': indicator.get('suffix', '')},
            title={"text": indicator['title']},
            value=indicator['value'],
            domain={'x': [x_start, x_end], 'y': [y_start, y_end]}
        ))
    
    fig.update_layout(
        paper_bgcolor="white",
        margin={"t": 0, "b": 0, "l": 0, "r": 0},
        height=250
    )
    fig.show()


def create_bar_chart(x, y, title, xaxis_title, yaxis_title):
    fig = go.Figure([go.Bar(name='Count', x=x, y=y)])
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        xaxis_tickangle=-45
    )
    fig.show()

def get_countries_by_reverse_gps(latitude_list, longitude_list):
    country_dict = {}
    for lat, lon in tqdm(zip(latitude_list, longitude_list), total=len(latitude_list), desc="Processing locations"):
        if lat and lon and lat != 0 and lon != 0:
            url = f"https://photon.komoot.io/reverse?lat={lat}&lon={lon}&lang=en"
            response = requests.get(url)

            if response.status_code == 200:
                features = response.json().get('features', [])
                country = features[0].get('properties', {}).get('country') if features else None
                if country:
                    country_dict[country] = country_dict.get(country, 0) + 1
                else:
                    print("Country information not found. This might be a limitation of the API being used.")
        else:
            print("Invalid coordinates or missing data.")
    return country_dict
