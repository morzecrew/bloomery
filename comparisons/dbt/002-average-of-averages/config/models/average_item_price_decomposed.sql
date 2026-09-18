-- The project-authored reading of the decomposed metric: the ratio rebuilt
-- from its operands.
select cast(sum(unit_price) / count(*) as decimal(18, 8)) as average_item_price
from {{ ref('order_items') }}
