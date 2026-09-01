python_sources(
  name="roboto-src",
  sources=["*.py", "**/*.py"],
)

resource(
    name="py_typed",
    source="py.typed",
)

# Read by a test in this package and by a Vitest test in web-ui, which compare the filter
# vocabulary across the two hand-maintained schemas. There is no codegen between them.
resource(
    name="filter_comparators",
    source="query/filter_comparators.json",
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