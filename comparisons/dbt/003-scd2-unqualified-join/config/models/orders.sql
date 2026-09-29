select order_id, customer_id, amount, cast(created_at as timestamp) as created_at
from {{ source('bronze', 'corpus__orders') }}
