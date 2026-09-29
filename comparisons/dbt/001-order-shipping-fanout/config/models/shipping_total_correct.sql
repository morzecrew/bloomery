-- The project-authored reading at the grain shipping originates at.
select sum(shipping) as shipping_total
from {{ ref('orders') }}
