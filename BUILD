python_tests(
    name="roboto-sdk-tests",
    sources=["test/**/test_*.py"],
)

python_distribution(
    name="roboto-py-sdk-dist",
    provides=python_artifact(
        name="roboto",
        python_requires=">=3.9,<4",
        version=env("VERSION"),
    ),
    dependencies=[
        "packages/roboto/src/roboto",
        "packages/roboto/src/roboto:py_typed",
    ],
    entry_points={
      "console_scripts": {
        "roboto": "roboto.cli:entry",
      }
    },
    repositories=[
      "https://upload.pypi.org/legacy/"
    ]
)
