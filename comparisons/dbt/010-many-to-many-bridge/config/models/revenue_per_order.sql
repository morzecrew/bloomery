-- The project-authored reading at the grain revenue originates at.
select round(sum(revenue), 2) as revenue
from {{ ref('orders') }}
