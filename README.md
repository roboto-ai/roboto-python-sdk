# Roboto SDK

[Roboto](https://www.roboto.ai/) makes it easy to manage and analyze robotics data at scale 🤖

This package contains the official toolkit for interacting with Roboto. It consists of the `roboto` Python module and command line utility.

If this is your first time using Roboto, we recommend reading the [docs](https://docs.roboto.ai/) and exploring the [core concepts](https://docs.roboto.ai/learn/concepts.html). 

<img src="https://github.com/user-attachments/assets/5f9a87e5-9012-4ec4-9a67-abf5ef733f5b" width="700"/>

## Why Roboto?

Most robotics teams start with manual review: visualizing logs and replaying data. But that approach alone doesn’t scale. It makes it hard to catch issues or measure performance as your fleet grows. Roboto helps you move beyond that. It gives you the tools to automate analysis and scale up 🚀

You can ingest logs and efficiently extract data from them — but that’s just the beginning. Roboto lets you query data and define custom actions to post-process it, so you can identify events, generate KPIs, and more.

See below for supported data formats, installation instructions and getting started [examples](#getting-started).

## Data Formats

Roboto can ingest data from a variety of formats, each with corresponding actions  in the [Action Hub](https://app.roboto.ai/actions/hub).

| Format            | Extensions        | Status | Action                  |
| ----------------- | ----------------- | ------ | ----------------------- |
| **ROS 2**         | `.mcap`, `.db3`   | ✅      | `ros_ingestion`         |
| **ROS 1**         | `.bag`            | ✅      | `ros_ingestion`         |
| **PX4**           | `.ulg`            | ✅      | `ulog_ingestion`        |
| **Parquet**       | `.parquet`        | ✅      | `parquet_ingestion`     |
| **CSV**           | `.csv`            | ✅      | `csv_ingestion`         |
| **Journal**       | `.log`            | ✅      | `journal_log_ingestion` |

Roboto’s extensible design can also support custom formats. **[Reach out](https://www.roboto.ai/contact)** to discuss your use case.


## Install Roboto

To use the Roboto SDK and CLI:

- Sign up at [app.roboto.ai](https://app.roboto.ai) and create an access token ([docs](https://docs.roboto.ai/getting-started/programmatic-access.html))
- Save your access token to `~/.roboto/config.json`

### Python

If you want to interact with Roboto in a Python environment, such as a Jupyter notebook, we recommend installing the Python SDK released via [PyPI](https://pypi.org/project/roboto/):

```bash
pip install roboto
```

This will also install the CLI mentioned below. See the complete [SDK](https://docs.roboto.ai/reference/python-sdk.html) and [CLI](https://docs.roboto.ai/reference/cli.html) documentation.

### CLI

If you want to interact with Roboto on the command line, and don't need the Python SDK, we recommend installing the standalone CLI.

You can find all versions of pre-built binary artifacts on the [releases](https://github.com/roboto-ai/roboto-python-sdk/releases) page of this package. We currently build for Linux (`aarch64`, `x86_64`), Mac OS X (`aarch64, x86_64`) and Windows (`x86_64`). See installation instructions per platform below.

Installing the CLI will provide the `roboto` command line utility. You can see available commands with `roboto -h` or see the complete [CLI reference](https://docs.roboto.ai/reference/cli.html)  documentation.

#### Linux

- Go to the [latest release](https://github.com/roboto-ai/roboto-python-sdk/releases/latest) page for this package
- (apt) Download the relevant `roboto` `.deb` file for your platform
  - e.g. `roboto-linux-x86_64_0.9.2.deb` *(don't pick a `roboto-agent` release)*
  - Double click on the downloaded `deb` file and let `apt` take over
- (non-apt) Download the relevant `roboto` file for your platform
  - e.g. `roboto-linux-x86_64` *(don't pick a `roboto-agent` release)*
  - Move the downloaded file to `/usr/local/bin` or where ever makes sense for your platform

Coming soon: direct `apt-get install` support

#### Mac OS X

You can either use the [Homebrew](https://brew.sh/) package manager:

```bash
brew install roboto-ai/tap/roboto
```

Or download the relevant Mac binary from the [latest release](https://github.com/roboto-ai/roboto-python-sdk/releases/latest) page e.g. `roboto-macos-aarch64`

If you used Homebrew, you can also upgrade via `brew upgrade roboto`

#### Windows

- Go to the [latest release](https://github.com/roboto-ai/roboto-python-sdk/releases/latest) page for this package
- Download the `roboto-windows-x86_64.exe` file
- Move the downloaded `.exe` to a folder that is on your `PATH`, like `C:\Program Files\`

#### Upgrade CLI

The CLI will automatically check for updates and notify you when a new version is available.

If you installed the CLI with the SDK via `pip`, you can simply upgrade with `pip install --upgrade roboto`.

If you installed the CLI from a `.deb` or by adding an executable like `roboto-linux-x86_64` to your `PATH`, you can
upgrade by downloading the latest version and replacing the old executable.

For OS X Homebrew users, you can upgrade by running `brew upgrade roboto`.

### Getting Started

The CLI is convenient for quickly creating new datasets, uploading or downloading files, and running actions. The Python SDK has comprehensive support for all Roboto platform features and is great for data analysis and integration with your other tools.

#### CLI Example

With the Python SDK, or standalone CLI installed, you can use `roboto` on the command line.

The example below shows how to create a new dataset and upload a file to it.

```bash
> roboto datasets create --tag boston
{
  "administrator": "Roboto",
  "created": "2024-09-25T22:22:48.271387Z",
  "created_by": "benji@roboto.ai",
  "dataset_id": "ds_9ggdi910gntp",
  ...
  "tags": [
    "boston"
  ]
}

> roboto datasets upload-files -d ds_9ggdi910gntp -p scene57.bag
100.0%|█████████████████████████ | 58.9M/58.9M | 2.62MB/s | 00:23 | Src: 1 file
```

#### Python Example

With the Python SDK installed, you can import `roboto` into your Python runtime.

The example below shows how to access topic data for an ingested ROS bag file:

```python
from roboto import Dataset

ds = Dataset.from_id("ds_9ggdi910gntp")
bag = ds.get_file_by_path("scene57.bag")
steering_topic = bag.get_topic("/vehicle_monitor/steering")

steering_data = steering_topic.get_data(
    start_time="1714513576", # "<sec>.<nsec>" since epoch
    end_time="1714513590",
)
```

You can also create events:

```python
from roboto import Event

Event.create(
  start_time="1714513580", # "<sec>.<nsec>" since epoch
  end_time="1714513590", 
  name="Fast Turn",
  topic_ids=[steering_topic.topic_id]
)
```

Or even search for logs matching metadata and statistics with [RoboQL](https://docs.roboto.ai/roboql/overview.html):

```python
from roboto import query, RobotoSearch
roboto_search = RobotoSearch(query.client.QueryClient())

query = '''
dataset.tags CONTAINS 'boston' AND
topics[0].msgpaths[/vehicle_monitor/vehicle_speed.data].max > 20
'''

results = roboto_search.find_files(query)
```

See the [notebooks](https://github.com/roboto-ai/roboto-python-sdk/tree/main/examples) directory for complete examples!

## Learn More

For more information, check out:
* [General Docs](https://docs.roboto.ai/)
* [User Guides](https://docs.roboto.ai/user-guides/index.html)
* [Example Notebooks](https://github.com/roboto-ai/roboto-python-sdk/tree/main/examples)
* [SDK Reference](https://docs.roboto.ai/reference/python-sdk.html)
* [CLI Reference](https://docs.roboto.ai/reference/cli.html)
* [About Roboto](https://www.roboto.ai/about)

## Contact

If you'd like to get in touch with us, feel free to email us at info@roboto.ai, or join our community [Discord server](https://discord.gg/r8RXceqnqH).