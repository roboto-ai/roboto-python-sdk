SDK usage examples
==================

This directory contains Jupyter notebooks demonstrating the use and features of the Roboto Python SDK.

## Setup

1. Setup your environment for [programmatic access to the Roboto platform](http://docs.roboto.ai/getting-started/programmatic-access.html)

2. Create a virtual environment using Python >= 3.10:
```bash
python -m venv .venv
```

3. Install the SDK with relevant pip extras:

_This assumes you're running this command from the root of the repository._

```bash
.venv/bin/python -m pip install .[analytics,examples]
```

## Running the examples

Start the Jupyter server and run the cells in notebooks of interest:
```bash
.venv/bin/jupyter lab --notebook-dir=examples
```

_If you're running the `jupyter lab` command from the `examples` directory itself, there's no need to specify the `--notebook-dir` argument. It's only necessary if you're running it from the root of the repository._

## Learn more

For more information, check out:
* [General Docs](https://docs.roboto.ai/)
* [User Guides](https://docs.roboto.ai/user-guides/index.html)
* [SDK Reference](https://docs.roboto.ai/reference/python-sdk/roboto/index.html)
* [CLI Reference](https://docs.roboto.ai/reference/cli.html)
* [About Roboto](https://www.roboto.ai/about)
