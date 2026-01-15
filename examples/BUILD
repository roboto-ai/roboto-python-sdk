python_sources(
  name="notebook-utils",
  sources=["notebook_utils/**/*.py"],
  dependencies=[
    # build-support[sdk_examples] extras
    "//build-support:3rdparty-dev-tools#ipython",
    "//build-support:3rdparty-dev-tools#jupyter",
    "//build-support:3rdparty-dev-tools#matplotlib",
    "//build-support:3rdparty-dev-tools#pillow",
  ],
  skip_mypy=True,  # Example notebook utilities - not production code
)

resources(
    name="notebooks",
    sources=["*.ipynb"],
)

# To run:
# pants run packages/roboto/examples:jupyter
pex_binary(
  name="jupyter",
  dependencies=[
    ":notebooks",
    ":notebook-utils",
    "//packages/roboto/src/roboto:roboto-src",

    # roboto extras (optional deps)
    "//build-support:3rdparty#fsspec",
    "//build-support:3rdparty#numpy",
    "//build-support:3rdparty#pandas",
    "//build-support:3rdparty#pyarrow",
    "//build-support:3rdparty#stumpy",

    # build-support[sdk_examples] extras
    "//build-support:3rdparty-dev-tools#ipython",
    "//build-support:3rdparty-dev-tools#jupyter",
    "//build-support:3rdparty-dev-tools#matplotlib",
    "//build-support:3rdparty-dev-tools#pillow",
  ],
  script="jupyter",
  args=["lab", f"--notebook-dir='{build_file_dir()}'"],
  execution_mode="venv",
)