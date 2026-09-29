-- The project-authored composition: each measure aggregated at its own grain,
-- joined only afterwards.
select shipping.shipping_total, discounts.discount_total
from (select sum(shipping) as shipping_total from {{ ref('orders') }}) as shipping
cross join (select sum(discount) as discount_total from {{ ref('order_items') }}) as discounts
