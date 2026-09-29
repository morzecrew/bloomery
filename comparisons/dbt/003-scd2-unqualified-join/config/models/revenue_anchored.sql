-- The same join, read as of the order's own date.
select sum(o.amount) as revenue
from {{ ref('orders') }} as o
join {{ ref('customer_tier') }} as t
  on o.customer_id = t.customer_id
 and o.created_at >= t.valid_from
 and o.created_at < t.valid_to
