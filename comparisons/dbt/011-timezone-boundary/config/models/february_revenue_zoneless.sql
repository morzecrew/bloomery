-- The project-authored reading of the zoneless metric: the published wall
-- clock taken at face value. dbt Core renders no SQL for a metric, so this
-- model is what produces the number the zoneless definition describes.
select sum(revenue) as february_revenue
from {{ ref('orders') }}
where cast(placed_at as timestamp) >= timestamp '2025-02-01'
  and cast(placed_at as timestamp) < timestamp '2025-03-01'
