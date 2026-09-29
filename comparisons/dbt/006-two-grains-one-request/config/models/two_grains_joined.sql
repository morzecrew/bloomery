-- The project-authored reading of the question as one join: the only shape
-- that puts both columns in one relation. dbt Core renders no SQL for a
-- metric, so this model is what produces the numbers.
select sum(o.shipping) as shipping_total, sum(i.discount) as discount_total
from {{ ref('order_items') }} as i
join {{ ref('orders') }} as o using (order_id)
