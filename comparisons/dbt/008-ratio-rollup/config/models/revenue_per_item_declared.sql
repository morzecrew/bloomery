-- The project-authored reading of the ratio metric: the quotient rebuilt at
-- the grain asked for, from operands that each sum.
select round(sum(revenue) / sum(item_count), 2) as revenue_per_item
from {{ ref('orders') }}
