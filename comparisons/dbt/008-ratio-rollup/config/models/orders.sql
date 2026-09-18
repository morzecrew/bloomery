select order_id, revenue, item_count, placed_on
from {{ source('bronze', 'corpus__orders') }}
