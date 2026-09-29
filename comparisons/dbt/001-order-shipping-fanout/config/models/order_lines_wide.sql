-- The wide mart: one row per order line, each carrying its order's shipping.
-- The join is many-to-one and correct; the copy of `shipping` on every line is
-- what the case is about.
select i.order_id, i.line_no, o.shipping, i.created_at
from {{ ref('order_items') }} as i
join {{ ref('orders') }} as o using (order_id)
