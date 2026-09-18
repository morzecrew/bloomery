-- The project-authored reading of the naive metric: sum the balance column
-- across every day. dbt Core renders no SQL for a metric, so this model is
-- what produces the number the naive definition describes.
select sum(balance) as total_balance
from {{ ref('balances') }}
