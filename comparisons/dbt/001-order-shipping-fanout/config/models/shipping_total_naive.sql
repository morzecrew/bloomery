-- The project-authored reading of the question over the wide mart: sum the
-- shipping column the join put on every line. dbt Core renders no SQL for a
-- metric, so this model is what produces the number.
select sum(shipping) as shipping_total
from {{ ref('order_lines_wide') }}
