-- The project-authored reading of the question with the join the ERD draws:
-- equality on the business key alone. dbt Core renders no SQL for a metric, so
-- this model is what produces the number.
select sum(o.amount) as revenue
from {{ ref('orders') }} as o
join {{ ref('customer_tier') }} as t on o.customer_id = t.customer_id
