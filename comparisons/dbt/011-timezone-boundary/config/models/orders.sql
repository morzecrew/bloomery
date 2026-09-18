select order_id, revenue, placed_at
from {{ source('bronze', 'corpus__orders') }}
