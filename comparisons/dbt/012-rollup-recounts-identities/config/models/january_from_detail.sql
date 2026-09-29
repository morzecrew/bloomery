-- The project-authored reading over the orders themselves.
select count(distinct customer_id) as buyers, sum(amount) as revenue
from {{ ref('orders') }}
where ordered_on >= timestamp '2025-01-01' and ordered_on < timestamp '2025-02-01'
