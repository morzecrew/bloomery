-- The project-authored reading of the question through the bridge. dbt Core
-- renders no SQL for a metric, so this model is what produces the number.
select round(sum(revenue), 2) as revenue
from {{ ref('order_promos_wide') }}
