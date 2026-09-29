-- The project-authored reading of the naive metric: add the two money columns
-- and sum. dbt Core renders no SQL for a metric, so this model is what produces
-- the number the naive definition describes.
select sum(amount_eur + fee_usd) as total_usd
from {{ ref('payments') }}
