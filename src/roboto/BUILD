python_sources(
  name="roboto-src",
  sources=["*.py", "**/*.py"],
)

resource(
    name="py_typed",
    source="py.typed",
)

pex_binary(
    name="admin-agent",
    dependencies=[
        ":roboto-src",
    ],
    entry_point="roboto.upload_agent.__main__:main",
    execution_mode="venv",
    output_path="bin/roboto-agent-admin"
)