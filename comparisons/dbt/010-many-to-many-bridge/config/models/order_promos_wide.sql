-- The bridged mart: one row per promotion applied, each carrying its order's
-- revenue. Both joins are many-to-one in the direction they are written.
select b.order_id, b.promo_id, p.label, o.revenue, b.applied_on
from {{ ref('order_promos') }} as b
join {{ ref('orders') }} as o on o.order_id = b.order_id
join {{ ref('promos') }} as p on p.promo_id = b.promo_id
