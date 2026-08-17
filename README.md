# Roboto SDK

[Roboto](https://www.roboto.ai/) is the analytics engine for Physical AI: ingest, search, and analyze your robotics data at scale, and put AI agents to work on it 🤖

This package is the official Python SDK for Roboto. The `roboto` command line utility is distributed separately as standalone binaries (see [CLI](#cli) below).

If this is your first time using Roboto, start with the [docs](https://docs.roboto.ai/) and the [core concepts](https://docs.roboto.ai/learn/concepts.html).

<img src="https://github.com/user-attachments/assets/5f9a87e5-9012-4ec4-9a67-abf5ef733f5b" width="700"/>

## Why Roboto?

Most robotics teams start with manual review: visualizing logs and replaying data. But that approach alone doesn't scale; your fleet generates more data than your team can ever review. Roboto helps you go from raw logs to root cause 🚀

Ingest logs in every major robotics format, query data across your fleet, and define custom actions to post-process it: identify events, generate KPIs, and more.

You can also let AI agents do the analysis: they search your data, dig into signals, summarize and triage datasets, and detect events, whether in the Roboto web app, through this SDK, or from the [AI tools you already use](#connect-your-ai-tools).

See below for supported data formats, installation instructions, and getting started [examples](#getting-started).

## Connect Your AI Tools

The hosted Roboto MCP server brings Roboto to the AI you already work in. Connect it once, and Claude Code, Claude Desktop, Codex, Cursor, VS Code, or any other client that speaks the [Model Context Protocol](https://modelcontextprotocol.io) can search your Roboto data, explore datasets and files, and analyze topic data mid-conversation:

```bash
claude mcp add --transport http roboto https://mcp.roboto.ai/mcp
```

- **You authenticate as yourself** — sign in with your browser or use a personal access token; every tool call runs with your own permissions.
- **Read-only by design** — a curated set of search, retrieval, and analysis tools; nothing exposed over MCP can modify your data.
- **All of your organizations, one connection** — if you belong to several orgs, ask the AI to call `whoami` and `set_active_org` to switch between them.

See [Use the Roboto MCP Server](https://docs.roboto.ai/user-guides/use-roboto-mcp-server.html) for setup instructions per client, and the [Roboto MCP Server](https://docs.roboto.ai/learn/ai/mcp-server.html) docs for everything the AI can do once connected.

## Data Formats

Roboto ingests the following formats, each with a corresponding action in the [Action Hub](https://app.roboto.ai/actions/hub).

| Format            | Extensions        | Status | Action                  |
| ----------------- | ----------------- | ------ | ----------------------- |
| **ROS 2**         | `.mcap`, `.db3`   | ✅      | `ros_ingestion`         |
| **ROS 1**         | `.bag`            | ✅      | `ros_ingestion`         |
| **PX4**           | `.ulg`            | ✅      | `ulog_ingestion`        |
| **Parquet**       | `.parquet`        | ✅      | `parquet_ingestion`     |
| **CSV**           | `.csv`            | ✅      | `csv_ingestion`         |
| **ArduPilot**     | `.bin`, `.log`, `.tlog` | ✅ | `ardupilot_ingestion`   |
| **Video**         | `.mp4`, `.avi`, `.mkv`  | ✅ | `video_ingestion`       |
| **Journal**       | `.log`            | ✅      | `journal_log_ingestion` |

Roboto can also support custom formats. [Reach out](https://www.roboto.ai/contact) to discuss your use case.

## Install Roboto

To use the Roboto SDK or CLI:

- Sign up at [app.roboto.ai](https://app.roboto.ai) and create an access token ([docs](https://docs.roboto.ai/getting-started/programmatic-access.html))
- Save your access token to `~/.roboto/config.json`

### Python

The Roboto Python SDK is available on [PyPI](https://pypi.org/project/roboto/).

**Requirements:** Python 3.10+

**Installation:**

```shell
pip install roboto
```

> [!TIP]
>
> If `pip install roboto` fails or behaves unexpectedly, the two most common causes are a Python version below 3.10 and dependency conflicts from installing into your system Python or an existing environment.

To rule out both, confirm your Python version meets the requirement:

```shell
python3 -c "import sys; assert sys.version_info >= (3, 10), f'Python 3.10+ required, found {sys.version}'"
```

Create and activate a virtual environment:

```shell
# macOS/Linux
python3 -m venv .venv && source .venv/bin/activate

# Windows
python -m venv .venv && .venv\Scripts\activate
```

Then re-run `pip install roboto`.

**Optional features:**

`pip install roboto` installs the core SDK. Some functionality depends on heavier third-party libraries that ship as optional [extras](https://packaging.python.org/en/latest/tutorials/installing-packages/#installing-extras), so you install them only when you need them:

| Extra | Install | Enables |
|---|---|---|
| `analytics` | `pip install 'roboto[analytics]'` | Searching for similar signals (`roboto.analytics.find_similar_signals`) and reading topic data into pandas DataFrames (`Topic.get_data_as_df`, `MessagePath.get_data_as_df`). Adds `fsspec`, `numpy`, `orjson`, `pandas`, `pyarrow`, and `stumpy`. |
| `ingestion` | `pip install 'roboto[ingestion]'` | Parsing and writing topic data as Parquet, e.g. when building ingestion actions. Adds `pandas` and `pyarrow`. |
| `video` | `pip install 'roboto[video]'` | Extracting frames from video files (`roboto.experimental.video`). Adds `av`, `numpy`, and `pillow`. |

Without the matching extra, these code paths raise an `ImportError` naming the extra to install. For example, calling `find_similar_signals` without the `analytics` extra raises:

```
ImportError: Missing optional dependency 'stumpy'. Re-install roboto using pip or conda with 'roboto[analytics]' to install a compatible version.
```

The `examples` extra provides the tooling needed to run the SDK's example notebooks, namely `ipython`, `jupyter`, `matplotlib`, and `pillow`. Use `pip install 'roboto[examples]'` before trying out the included examples.

> [!IMPORTANT]
>
> Quote the package spec when installing an extra. Zsh (the default shell on macOS) treats the square brackets as a glob pattern, so an unquoted `pip install roboto[analytics]` fails with `zsh: no matches found: roboto[analytics]`. Quoting the spec (`pip install 'roboto[analytics]'`) avoids the error.

**Authentication (required):**

The SDK uses the access token you saved above; if you haven't created one yet, see [Setting up programmatic access](https://docs.roboto.ai/getting-started/programmatic-access.html). Verify your credentials are configured correctly:

```shell
python -m roboto.cli users whoami
```

See the complete [SDK documentation](https://docs.roboto.ai/reference/python-sdk.html).

### CLI

To use Roboto from the command line without the Python SDK, install the standalone CLI.

Pre-built binaries for every version are on the [releases](https://github.com/roboto-ai/roboto-python-sdk/releases) page of this package. We build for Linux (`aarch64`, `x86_64`), macOS (`aarch64`, `x86_64`), and Windows (`x86_64`). See per-platform installation instructions below.

The CLI provides the `roboto` command line utility. List available commands with `roboto -h`, or see the complete [CLI reference](https://docs.roboto.ai/reference/cli.html) documentation.

#### Linux

- Go to the [latest release](https://github.com/roboto-ai/roboto-python-sdk/releases/latest) page for this package
- (apt) Download the relevant `roboto` `.deb` file for your platform
  - e.g. `roboto-linux-x86_64_0.9.2.deb` (not a `roboto-agent` release)
  - Double-click the downloaded `.deb` file to install it with `apt`
- (non-apt) Download the relevant `roboto` file for your platform
  - e.g. `roboto-linux-x86_64` (not a `roboto-agent` release)
  - Move the downloaded file to `/usr/local/bin` or another directory on your `PATH`

Coming soon: direct `apt-get install` support

#### macOS

Install with the [Homebrew](https://brew.sh/) package manager:

```bash
brew install roboto-ai/tap/roboto
```

Or download the relevant Mac binary, e.g. `roboto-macos-aarch64`, from the [latest release](https://github.com/roboto-ai/roboto-python-sdk/releases/latest) page.

#### Windows

- Go to the [latest release](https://github.com/roboto-ai/roboto-python-sdk/releases/latest) page for this package
- Download the `roboto-windows-x86_64.exe` file
- Move the downloaded `.exe` to a folder on your `PATH`, like `C:\Program Files\`

#### Upgrade CLI

The CLI automatically checks for updates and notifies you when a new version is available.

Homebrew users can upgrade by running `brew upgrade roboto`. If you installed a `.deb` or a standalone executable, download the latest version and replace the old one.

## Getting Started

Use the CLI for quick tasks: creating datasets, uploading or downloading files, and running actions. Use the Python SDK for full platform coverage, data analysis, and integration with your other tools.

### CLI Example

The example below creates a new dataset and uploads a file to it. In a Python environment with the SDK installed, the same commands are available via `python -m roboto.cli`.

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

### Python Example

The example below accesses topic data from an ingested ROS bag file:

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

Or search for logs matching metadata and statistics with [RoboQL](https://docs.roboto.ai/roboql/overview.html):

```python
from roboto import query, RobotoSearch
roboto_search = RobotoSearch(query.client.QueryClient())

query = '''
dataset.tags CONTAINS 'boston' AND
topics[0].msgpaths[/vehicle_monitor/vehicle_speed.data].max > 20
'''

results = roboto_search.find_files(query)
```

Or put an [AI agent](https://docs.roboto.ai/learn/ai/index.html) to work on your data and stream its findings as it goes:

```python
from roboto.ai import AgentThread
from roboto.ai.agent_thread import AgentTextDeltaEvent

thread = AgentThread.start(
    "Look at dataset ds_9ggdi910gntp and check /vehicle_monitor/steering for anomalies."
)

for event in thread.events():
    if isinstance(event, AgentTextDeltaEvent):
        print(event.text, end="", flush=True)
```

The same agents are available in the web app's AI Chat and on the command line via `roboto chat start`.

See the [notebooks](https://github.com/roboto-ai/roboto-python-sdk/tree/main/examples) directory for complete examples!

## Learn More

For more information, check out:
* [General Docs](https://docs.roboto.ai/)
* [AI Agents](https://docs.roboto.ai/learn/ai/index.html)
* [Use the Roboto MCP Server](https://docs.roboto.ai/user-guides/use-roboto-mcp-server.html)
* [User Guides](https://docs.roboto.ai/user-guides/index.html)
* [Example Notebooks](https://github.com/roboto-ai/roboto-python-sdk/tree/main/examples)
* [SDK Reference](https://docs.roboto.ai/reference/python-sdk.html)
* [CLI Reference](https://docs.roboto.ai/reference/cli.html)
* [About Roboto](https://www.roboto.ai/about)

## Contact

Email us at info@roboto.ai or join our community [Discord server](https://discord.gg/r8RXceqnqH).
