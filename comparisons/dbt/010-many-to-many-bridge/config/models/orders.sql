select order_id, revenue, cast(placed_on as timestamp) as placed_on
from {{ source('bronze', 'corpus__orders') }}
