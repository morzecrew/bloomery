-- The project-authored reading of the naive metric: average the published
-- per-order averages. dbt Core renders no SQL for a metric, so this model is
-- what produces the number the naive definition describes.
select cast(avg(average_item_price) as decimal(18, 8)) as average_item_price
from {{ ref('order_summaries') }}
