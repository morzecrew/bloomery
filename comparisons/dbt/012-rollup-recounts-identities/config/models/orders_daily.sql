-- The daily pre-aggregate: each row a correct number about its day.
select ordered_on, sum(amount) as revenue, count(distinct customer_id) as buyers
from {{ ref('orders') }}
group by ordered_on
