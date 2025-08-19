# 0.25.3
## Features Added
  - Added `ActionStatsRecord` + an API to retrieve them for an org within a given time window.
  - Introduced `CanonicalDataType.Categorical` for data that can take a limited, fixed set of values. To be interpreted correctly by Roboto clients, a `MessagePathRecord` with this type must have a `"dictionary"` metadata key containing the list of possible values. This enables Roboto to map categorical values to indices and visualize the data as plots.

