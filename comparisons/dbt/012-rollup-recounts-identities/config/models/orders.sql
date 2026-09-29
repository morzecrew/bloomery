select order_id, customer_id, amount, cast(ordered_on as timestamp) as ordered_on
from {{ source('bronze', 'corpus__orders') }}
